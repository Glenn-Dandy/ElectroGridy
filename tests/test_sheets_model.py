import pytest
from PyQt6.QtGui import QUndoStack

from electrogridy.commands.sheets import (
    AddSheetCommand,
    ChangeDocumentPropertiesCommand,
    ChangeSheetCommand,
    MoveSheetCommand,
    NavigateViewportCommand,
    RemoveSheetCommand,
)
from electrogridy.fileio.json_format import document_from_dict, document_to_dict
from electrogridy.fileio.templates import load_frame, save_frame
from electrogridy.model.document import Document, new_sheet
from electrogridy.model.entities import Line, Viewport
from electrogridy.model.geometry import Point
from electrogridy.model.paper import Orientation
from electrogridy.model.sheet import frame_corners, frame_entities, title_block_insert
from electrogridy.model.title_block import TITLE_BLOCK_NAME, TITLE_BLOCK_WIDTH


def vp(**kw) -> Viewport:
    base = dict(id="v", p1=Point(20, 10), p2=Point(120, 60), center=Point(0, 0), scale=1.0)
    base.update(kw)
    return Viewport(**base)


@pytest.mark.parametrize(
    ("scale", "model", "sheet"),
    [
        (1.0, Point(0, 0), Point(70, 35)),
        (1.0, Point(10, -5), Point(80, 30)),
        (0.5, Point(10, -5), Point(75, 32.5)),
        (2.0, Point(10, -5), Point(90, 25)),
    ],
)
def test_viewport_model_to_sheet(scale, model, sheet):
    v = vp(scale=scale)
    assert v.model_to_sheet(model) == sheet
    back = v.sheet_to_model(sheet)
    assert back.x == pytest.approx(model.x) and back.y == pytest.approx(model.y)


def test_viewport_model_rect_and_contains():
    v = vp(scale=0.5, center=Point(100, 100))
    assert v.model_rect() == (Point(0, 50), Point(200, 150))
    assert v.contains(Point(50, 30)) and not v.contains(Point(5, 30))


def test_frame_margins_iso_5457():
    a, b = frame_corners(1189, 841)
    assert (a, b) == (Point(20, 10), Point(1179, 831))
    assert title_block_insert(1189, 841) == Point(1179, 831)
    assert len(frame_entities(1189, 841)) == 5


def test_new_document_sheet_has_viewport_and_title_block():
    doc = Document.new("Blatt 1")
    sheet = doc.sheets[0]
    (v,) = sheet.viewports()
    assert (v.p1, v.p2, v.scale) == (Point(20, 10), Point(1179, 831), 1.0)
    # Model origin at the frame's top left corner.
    assert v.model_to_sheet(Point(0, 0)) == Point(20, 10)
    tb = doc.blocks[TITLE_BLOCK_NAME]
    tags = {a.tag for a in tb.attribute_definitions()}
    assert tags == {
        "PROJEKT",
        "FIRMA",
        "BEARBEITER",
        "TITEL",
        "ZEICHNUNGSNR",
        "DATUM",
        "GEPRUEFT",
        "AENDERUNG",
        "BLATT",
        "FORMAT",
    }
    frame = [e for e in tb.entities if e.id == "frame"][0]
    assert abs(frame.p2.x - frame.p1.x) == TITLE_BLOCK_WIDTH


def test_field_values_with_sheet_numbers():
    doc = Document.new("Blatt 1")
    doc.insert_sheet(1, new_sheet("Blatt 2", "A3", Orientation.PORTRAIT))
    doc.properties["PROJEKT"] = "PV Nord"
    doc.sheets[1].fields["TITEL"] = "Übersicht"
    values = doc.field_values(doc.sheets[1].id)
    assert values["PROJEKT"] == "PV Nord" and values["TITEL"] == "Übersicht"
    assert values["BLATT"] == "2 von 2" and values["FORMAT"] == "A3 hoch"
    assert doc.field_values(doc.sheets[0].id)["BLATT"] == "1 von 2"


def check(doc, command):
    stack = QUndoStack()
    before = document_to_dict(doc)
    stack.push(command)
    after = document_to_dict(doc)
    assert after != before
    stack.undo()
    assert document_to_dict(doc) == before
    stack.redo()
    assert document_to_dict(doc) == after


def two_sheets():
    doc = Document.new("Blatt 1")
    doc.insert_sheet(1, new_sheet("Blatt 2"))
    return doc


def test_sheet_commands():
    doc = two_sheets()
    check(doc, AddSheetCommand(doc, 1, new_sheet("Neu"), "add"))
    doc = two_sheets()
    check(doc, RemoveSheetCommand(doc, doc.sheets[0].id, "remove"))
    doc = two_sheets()
    check(doc, MoveSheetCommand(doc, 0, 1, "move"))
    doc = two_sheets()
    sid = doc.sheets[0].id
    check(doc, ChangeSheetCommand(doc, sid, "fmt", paper="A3", orientation=Orientation.PORTRAIT))
    check(doc, ChangeSheetCommand(doc, sid, "fields", fields={"TITEL": "X"}))
    check(doc, ChangeSheetCommand(doc, sid, "name", name="Übersicht"))
    check(doc, ChangeDocumentPropertiesCommand(doc, {"FIRMA": "FS Solartechnik"}, "props"))


def test_last_sheet_cannot_be_removed():
    doc = Document.new("Blatt 1")
    with pytest.raises(ValueError):
        RemoveSheetCommand(doc, doc.sheets[0].id, "remove")


def test_viewport_navigation_merges():
    doc = Document.new("Blatt 1")
    container = doc.sheets[0].entities
    v = doc.sheets[0].viewports()[0]
    stack = QUndoStack()
    from dataclasses import replace

    stack.push(NavigateViewportCommand(container, replace(v, scale=0.5), "z"))
    stack.push(NavigateViewportCommand(container, replace(v, scale=0.25), "z"))
    assert stack.count() == 1 and container.get(v.id).scale == 0.25
    stack.undo()
    assert container.get(v.id).scale == 1.0


def test_document_with_sheets_roundtrip():
    doc = two_sheets()
    doc.properties["FIRMA"] = "FS"
    doc.sheets[1].fields["TITEL"] = "T"
    doc.sheets[1].entities.add(Line(id="l", p1=Point(0, 0), p2=Point(1, 1)))
    data = document_to_dict(doc)
    again = document_from_dict(data)
    assert document_to_dict(again) == data
    assert [s.id for s in again.sheets] == [s.id for s in doc.sheets]


def test_frame_template_roundtrip(tmp_path):
    doc = Document.new("Blatt 1")
    sheet = doc.sheets[0]
    sheet.entities.add(Line(id="legend", p1=Point(30, 30), p2=Point(60, 30)))
    sheet.fields["TITEL"] = "nicht in der Vorlage"
    path = tmp_path / "rahmen.grdyframe"
    save_frame(sheet, doc.blocks, path, "Mein Rahmen")
    name, loaded, blocks = load_frame(path)
    assert name == "Mein Rahmen"
    assert loaded.paper == "A0" and loaded.fields == {}
    assert loaded.id != sheet.id
    assert {e.id for e in loaded.entities} == {e.id for e in sheet.entities}
    assert [b.name for b in blocks] == [TITLE_BLOCK_NAME]


def test_paper_of_a_pdf_page():
    from electrogridy.model.paper import Orientation, paper_of

    assert paper_of(420.2, 296.8) == ("A3", Orientation.LANDSCAPE)
    assert paper_of(210, 297) == ("A4", Orientation.PORTRAIT)
    assert paper_of(215.9, 279.4) is None  # Letter
