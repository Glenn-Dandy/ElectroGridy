import pytest
from PyQt6.QtCore import QSettings

from sldgridy.fileio.json_format import (
    BASE_VERSION,
    FORMAT_VERSION,
    document_from_dict,
    document_to_dict,
)
from sldgridy.model.document import PAGES, Document, designation, new_page
from sldgridy.model.entities import Line
from sldgridy.model.geometry import Point
from sldgridy.model.sheet import column_at, column_edges, column_strip_entities
from sldgridy.ui.main_window import WORKSPACE_MLD, WORKSPACE_SLD, MainWindow
from sldgridy.ui.sheet_controller import page_insert_index


def doc_with_pages() -> Document:
    doc = Document.new("Blatt 1")
    doc.pages = [
        new_page("Einspeisung", "PV1", "UV1"),
        new_page("Zähler", "PV1", "UV1"),
        new_page("Wechselrichter", "PV1", "WR"),
        new_page("Übersicht"),
    ]
    return doc


def test_pages_are_numbered_per_plant_and_location():
    doc = doc_with_pages()
    p = doc.pages
    assert [doc.page_number(x.id) for x in p] == [(1, 2), (2, 2), (1, 1), (1, 1)]
    assert doc.page_label(p[1].id) == "=PV1 +UV1 /2"
    assert doc.page_label(p[3].id) == "/1"
    assert designation("", "WR") == "+WR"
    assert doc.layout(p[2].id) is p[2] and doc.kind_of(p[2].id) == PAGES
    values = doc.field_values(p[1].id)
    assert values["BLATT"] == "2 von 2" and values["TITEL"] == "Zähler"
    assert values["ZEICHNUNGSNR"] == "=PV1 +UV1"
    assert values["FORMAT"] == "A4 quer"
    # Pages are drawn on directly: no viewport, ten columns.
    assert not p[0].viewports() and p[0].columns == 10


def test_new_page_goes_behind_its_group():
    doc = doc_with_pages()
    p = doc.pages
    third = new_page("", "PV1", "UV1")
    assert page_insert_index(p, third, p[0]) == 1  # right after the current page
    assert page_insert_index(p, third, p[2]) == 2  # current is elsewhere: end of group
    assert page_insert_index(p, new_page("", "X"), None) == 4  # new group at the end


def test_column_grid():
    edges = column_edges(297, 210, 10)
    assert edges[0] == 20 and edges[-1] == pytest.approx(287) and len(edges) == 11
    assert column_at(297, 210, 10, 21) == 1
    assert column_at(297, 210, 10, 150) == 5
    assert column_at(297, 210, 10, 400) == 10
    assert len([e for e in column_strip_entities(297, 210, 10) if hasattr(e, "text")]) == 10
    assert column_strip_entities(297, 210, 0) == []


def test_pages_roundtrip_and_format_version():
    doc = doc_with_pages()
    doc.pages[0].entities.add(Line(id="l", p1=Point(30, 30), p2=Point(60, 30)))
    data = document_to_dict(doc)
    assert data["format_version"] == FORMAT_VERSION == 3
    again = document_from_dict(data)
    assert document_to_dict(again) == data
    assert [(x.plant, x.location, x.columns) for x in again.pages] == [
        ("PV1", "UV1", 10),
        ("PV1", "UV1", 10),
        ("PV1", "WR", 10),
        ("", "", 10),
    ]
    plain = document_to_dict(Document.new("Blatt 1"))
    assert plain["format_version"] == BASE_VERSION and "pages" not in plain
    assert document_from_dict(plain).pages == []


@pytest.fixture
def window(qapp):
    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    yield w
    w.undo_stack.setClean()
    w.close()


def test_mld_workspace_shows_pages(window, monkeypatch):
    sheets = window.sheets
    window.set_workspace(WORKSPACE_MLD)
    assert sheets.pages_mode and len(window.document.pages) == 1
    assert window.pages_dock.isVisible()
    assert [sheets.tabs.tabText(i) for i in range(sheets.tabs.count())] == ["/1"]
    assert window.sheets.current_sheet() is window.document.pages[0]
    assert sheets.menu.title() == "Sei&te"
    # New page with plant and location (dialog answered).
    monkeypatch.setattr(sheets, "_page_values", lambda title, page: ("PV1", "UV1", "Zähler"))
    sheets.new_sheet()
    monkeypatch.setattr(sheets, "_page_values", lambda title, page: ("PV1", "UV1", "Einspeisung"))
    sheets.new_sheet()
    texts = [sheets.tabs.tabText(i) for i in range(sheets.tabs.count())]
    assert texts == ["/1", "=PV1 +UV1 /1 Zähler", "=PV1 +UV1 /2 Einspeisung"]
    assert window.pages_dock.tree.topLevelItemCount() == 2
    sheets.show_sheet(window.document.pages[1].id)
    assert window.pages_dock.tree.currentItem().text(0) == "/1  Zähler"
    # Drawing on a page goes into the page.
    page = window.sheets.current_sheet()
    window.container.add(Line(id="x", p1=Point(30, 30), p2=Point(60, 30)))
    assert "x" in page.entities
    # Back in the circuit diagram the tabs are model and sheets again.
    window.set_workspace(WORKSPACE_SLD)
    assert [sheets.tabs.tabText(i) for i in range(sheets.tabs.count())] == ["Modell", "Blatt 1"]
    assert not window.pages_dock.isVisible() and window.space is window.model_view
    window.set_workspace(WORKSPACE_MLD)
    assert sheets.tabs.count() == 3


def test_page_print_list(window):
    from sldgridy.ui.print_dialog import PrintDialog

    window.set_workspace(WORKSPACE_MLD)
    dialog = PrintDialog(
        window.document,
        window.sheets.current_sheet(),
        parent=window,
        layouts=window.sheets.layouts(),
        pages=True,
    )
    assert dialog.rb_all.text() == "Alle Seiten" and not dialog.rb_model.isVisibleTo(dialog)
    dialog.rb_all.setChecked(True)
    assert dialog.sheets() == window.document.pages


# -- step 2: interruption points ------------------------------------------------


def ip(pid, name, x, y, direction=0):
    from sldgridy.model.entities import InterruptionPoint

    return InterruptionPoint(id=pid, name=name, position=Point(x, y), direction=direction)


def test_interruption_pairs_refer_to_each_other():
    from sldgridy.model.interruptions import interruption_targets, partner, unpaired_names

    doc = doc_with_pages()
    p = doc.pages  # /1 /2 of =PV1 +UV1, /1 of =PV1 +WR, /1 without designation
    p[0].entities.add(ip("a", "L1", 280, 50))  # column 10 of page /1
    p[1].entities.add(ip("b", "L1", 25, 50, 180))  # column 1 of page /2
    p[2].entities.add(ip("c", "N", 150, 60))
    targets = interruption_targets(doc)
    assert targets["a"] == ("/2.1", p[1].id)
    assert targets["b"] == ("/1.10", p[0].id)
    assert "c" not in targets and unpaired_names(doc) == ["N"]
    # Into another location: the designation is written in front.
    p[0].entities.add(ip("d", "N", 270, 80))
    assert interruption_targets(doc)["d"] == ("=PV1 +WR /1.5", p[2].id)
    assert partner(doc, "c")[1].id == "d"
    # Reordering pages changes the references.
    doc.move_layout(PAGES, 1, 0)
    assert interruption_targets(doc)["a"][0] == "/1.1"
    assert interruption_targets(doc)["b"][0] == "/2.10"


def test_interruption_geometry_and_file():
    from sldgridy.fileio.json_format import entity_from_dict, entity_to_dict
    from sldgridy.model.entities import Text
    from sldgridy.model.interruptions import interruption_geometry

    point = ip("a", "L1", 100, 50, 90)
    texts = [e.text for e in interruption_geometry(point, "/2.1") if isinstance(e, Text)]
    assert texts == ["L1  /2.1"]
    assert entity_from_dict(entity_to_dict(point)) == point
    assert point.rotated(Point(0, 0), 1).direction == 180
    assert point.mirrored(Point(0, 0), False).direction == 90


def test_interruption_tool_and_jump(window, monkeypatch):
    from PyQt6.QtTest import QTest

    from sldgridy.model.entities import InterruptionPoint

    window.set_workspace(WORKSPACE_MLD)
    assert window.act_interruption.isVisible()
    sheets = window.sheets
    monkeypatch.setattr(sheets, "_page_values", lambda title, page: ("", "", "Zwei"))
    first = window.document.pages[0]
    names = iter(["L1", "L1"])
    monkeypatch.setattr(window, "ask_interruption_name", lambda: next(names))
    sheets.show_sheet(first.id)
    window.act_interruption.trigger()
    window.tools.pick(Point(280, 50))
    window.tools.pick(Point(290, 50))  # runs on to the right
    window.tools.cancel()
    sheets.new_sheet()
    second = sheets.current_sheet()
    window.act_interruption.trigger()
    window.tools.pick(Point(25, 50))
    window.tools.pick(Point(15, 50))
    window.tools.cancel()
    (a,) = [e for e in first.entities if isinstance(e, InterruptionPoint)]
    (b,) = [e for e in second.entities if isinstance(e, InterruptionPoint)]
    assert (a.direction, b.direction) == (0, 180)
    assert window.interruption_targets()[a.id][0] == "/2.1"
    QTest.qWait(10)  # the other page's point is redrawn with its reference
    # Double click (edit) on the point jumps to its partner.
    window._edit_entity(b.id)
    assert sheets.current_sheet() is first
    assert window.selected_ids() == [a.id]
