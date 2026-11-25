"""Circuit diagram symbols in projects: own terminal names, terminal names at the poles,
the contact mirror per pole under the attributes and the device window."""

from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from electrogridy.fileio.files import load_library
from electrogridy.fileio.json_format import entity_from_dict, entity_to_dict
from electrogridy.model.blocks import world_connections
from electrogridy.model.devices import poles
from electrogridy.model.document import DOC_PROJECT, DOC_SLD, Document
from electrogridy.model.entities import BlockReference, Line, Text
from electrogridy.model.geometry import Point

MLD = Path(__file__).parents[1] / "src/electrogridy/resources/library/mld_symbole.grdylib"


def mld_blocks() -> dict:
    return {b.name: b for b in load_library(MLD)[1]}


def symbol(rid, name, x, y, bmk, **kw) -> BlockReference:
    return BlockReference(id=rid, name=name, insert=Point(x, y), attributes=(("BMK", bmk),), **kw)


def project(kind=DOC_PROJECT) -> Document:
    doc = Document.new("Seite 1", kind=kind)
    doc.blocks.update(mld_blocks())
    return doc


def test_own_terminal_names_are_saved_and_used():
    ref = symbol("q", "Leitungsschutzschalter 1-polig", 0, 0, "-Q1", terminal_labels=(("1", "L1"),))
    again = entity_from_dict(entity_to_dict(ref))
    assert again.terminal_labels == (("1", "L1"),)
    assert "terminal_labels" not in entity_to_dict(replace(ref, terminal_labels=()))
    names = [c.name for c in world_connections(ref, mld_blocks())]
    assert names == ["L1", "2"]


def test_poles_of_contacts():
    blocks = mld_blocks()
    main = symbol("k", "Schütz Hauptkontakte 3-polig", 0, 0, "-K1")
    assert poles(blocks[main.name], main) == (("1", "2"), ("3", "4"), ("5", "6"))
    changeover = symbol("w", "Wechsler", 0, 0, "-K1")
    assert poles(blocks[changeover.name], changeover) == (("11", "12/14"),)
    renamed = replace(changeover, terminal_labels=(("11", "21"),))
    assert poles(blocks[changeover.name], renamed) == (("21", "12/14"),)


def _texts(doc, ref):
    from electrogridy.view.display import expand_for_display

    return [p for p in expand_for_display(doc, ref) if isinstance(p, Text)]


def test_terminal_names_at_the_poles_only_on_project_pages(qapp):
    doc = project()
    upright = symbol("q1", "Leitungsschutzschalter 1-polig", 50, 50, "-Q1")
    doc.sheets[0].entities.add(upright)
    names = {t.text: t for t in _texts(doc, upright) if ":pole:" in t.id}
    assert set(names) == {"1", "2"}
    top, bottom = names["1"], names["2"]
    assert top.halign == "right" and top.position.x < 50  # left of the pole
    assert top.position.y > 50 and bottom.position.y < 65  # just inside its ends
    lying = symbol("q2", "Leitungsschutzschalter 1-polig", 150, 50, "-Q2", rotation=90)
    doc.sheets[0].entities.add(lying)
    texts = _texts(doc, lying)
    one = next(t for t in texts if ":pole:" in t.id and t.text == "1")
    bmk = next(t for t in texts if t.text == "-Q2")
    assert one.valign == "bottom" and bmk.position.y < one.position.y - one.height  # above it
    overview = project(DOC_SLD)
    overview.sheets[0].entities.add(upright)
    assert not [t for t in _texts(overview, upright) if ":pole:" in t.id]


def test_contact_mirror_under_the_attributes(qapp):
    from electrogridy.view.display import expand_for_display

    doc = project()
    coil = symbol("coil", "Schützspule", 50, 50, "-K2")
    doc.sheets[0].entities.add(coil)
    doc.sheets[0].entities.add(symbol("main", "Schütz Hauptkontakte 3-polig", 120, 50, "-K2"))
    doc.sheets[0].entities.add(symbol("no", "Schließer", 180, 50, "-K2"))
    parts = expand_for_display(doc, coil)
    texts = {t.text: t for t in parts if isinstance(t, Text) and ":xref" in t.id}
    assert {"1", "2", "3", "4", "5", "6", "13", "14"} <= set(texts)
    bmk = next(t for t in parts if isinstance(t, Text) and t.text == "-K2")
    first = texts["1"]
    assert first.position.y > bmk.position.y  # under -K2
    assert first.position.x > 50  # beside the coil, not on its wire
    rows = sorted({round(t.position.y, 2) for t in texts.values()})
    assert len(rows) == 4  # one line per pole
    glyphs = [p for p in parts if isinstance(p, Line) and ":xref" in p.id]
    assert len(glyphs) == 4 * 3


def test_device_window_turns_mirrors_and_names(qapp):
    from electrogridy.ui.device_dialog import DeviceDialog

    blocks = mld_blocks()
    ref = symbol("no", "Schließer", 0, 0, "-K1")
    dialog = DeviceDialog(ref, blocks, {"BMK": "-K1"}, ["-K1", "-K2"])
    assert dialog.device is not None
    assert [dialog.device.itemText(i) for i in range(dialog.device.count())] == ["-K1", "-K2"]
    dialog.device.setCurrentText("-K2")
    dialog.turn(1)
    assert dialog.reference().rotation == 90
    dialog.mirror()
    result = dialog.reference()
    assert result.rotation == 270 and result.mirrored_x
    dialog._terminals["13"].setText("43")
    dialog._terminals["14"].setText("")  # empty: the name of the symbol
    result = dialog.reference()
    assert result.terminal_labels == (("13", "43"),)
    assert dict(result.attributes)["BMK"] == "-K2"
    assert not dialog.preview.pixmap().isNull()
    breaker = symbol("q", "Leitungsschutzschalter 3-polig", 0, 0, "-Q1")
    plain = DeviceDialog(breaker, blocks, {"BMK": "-Q1"}, [])
    assert plain.device is None and len(plain._terminals) == 6


@pytest.fixture
def window(qapp):
    from electrogridy.ui.main_window import MainWindow

    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document(DOC_PROJECT)
    w.sheets.show_sheet(w.document.sheets[-1].id)
    qapp.processEvents()
    yield w
    for space in w.spaces():
        space.stack.setClean()
    w.undo_stack.setClean()
    w.close()


def test_double_click_turns_the_device_and_wires_follow(window, monkeypatch):
    from electrogridy.commands.entities import AddEntitiesCommand
    from electrogridy.model.entities import Wire
    from electrogridy.ui.device_dialog import DeviceDialog

    window.document.blocks.update(mld_blocks())
    coil = symbol("coil", "Schützspule", 50, 50, "-K1")
    wire = Wire(id="w", points=(Point(50, 65), Point(50, 90)))
    window.push(AddEntitiesCommand(window.container, [coil, wire], "test"))
    assert window.blocks.main_devices() == ["-K1"]

    def accept(dialog):
        dialog.turn(-1)
        dialog._terminals["A1"].setText("X1")
        return DeviceDialog.DialogCode.Accepted

    monkeypatch.setattr(DeviceDialog, "exec", accept)
    assert window.blocks.edit_entity(window.container.get("coil"))
    turned = window.container.get("coil")
    assert turned.rotation == 270 and turned.terminal_labels == (("A1", "X1"),)
    a2 = next(c for c in world_connections(turned, window.document.blocks) if c.name == "A2")
    moved = window.container.get("w")
    assert a2.position in (moved.points[0], moved.points[-1])  # the wire followed
    window.act_undo.trigger()
    assert window.container.get("coil").rotation == 0
