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
