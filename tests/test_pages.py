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


# -- step 3: devices and cross references ----------------------------------------


def roles_doc() -> Document:
    from sldgridy.model.blocks import BlockDefinition
    from sldgridy.model.container import EntityContainer
    from sldgridy.model.entities import BlockReference, ConnectionPoint, Rectangle

    doc = doc_with_pages()

    def block(name, function, contact="", terminals=("A1", "A2")):
        cps = [
            ConnectionPoint(id=f"c{i}", name=t, position=Point(0, 10 * i))
            for i, t in enumerate(terminals)
        ]
        return BlockDefinition(
            name=name,
            entities=EntityContainer([Rectangle(id="r", p1=Point(-2, 0), p2=Point(2, 10)), *cps]),
            function=function,
            contact=contact,
        )

    doc.blocks["Spule"] = block("Spule", "main")
    doc.blocks["Schließer"] = block("Schließer", "aux", "no", ("13", "14"))
    doc.blocks["Öffner"] = block("Öffner", "aux", "nc", ("21", "22"))
    doc.blocks["Schütz SLD"] = block("Schütz SLD", "")

    def ref(rid, name, bmk, x, y=60):
        return BlockReference(id=rid, name=name, insert=Point(x, y), attributes=(("BMK", bmk),))

    p = doc.pages
    p[0].entities.add(ref("coil", "Spule", "-K1", 40))  # page /1, column 1
    p[1].entities.add(ref("no", "Schließer", "-K1", 150))  # page /2, column 5
    p[2].entities.add(ref("nc", "Öffner", "-K1", 280))  # =PV1 +WR /1, column 10
    doc.model_space.add(ref("sld", "Schütz SLD", "-K1", 0, 0))
    doc.model_space.add(ref("sld2", "Schütz SLD", "-K2", 0, 50))
    doc.model_space.add(ref("sld3", "Schütz SLD", "-K2", 0, 80))
    return doc


def test_device_occurrences_and_cross_references():
    from sldgridy.model.devices import crossref_texts, crossrefs, devices, problems

    doc = roles_doc()
    found = devices(doc)
    assert list(found) == ["-K1", "-K2"]
    assert [o.where for o in found["-K1"]] == ["model", "page", "page", "page"]
    xr = crossrefs(doc)
    assert xr["coil"] == ["S 13-14  /2.5", "Ö 21-22  =PV1 +WR /1.10"]
    assert xr["no"] == ["/1.1"]
    assert xr["nc"] == ["=PV1 +UV1 /1.1"]
    assert "sld" not in xr  # the circuit diagram shows no mirror
    assert problems(doc) == {"-K2": ["sld_twice"]}
    texts = crossref_texts(doc.pages[0].entities.get("coil"), doc.blocks, xr["coil"])
    assert [t.text for t in texts] == xr["coil"]
    assert texts[0].position.y > 70  # under the symbol (it reaches down to 70)


def test_block_role_is_saved():
    from sldgridy.fileio.json_format import block_from_dict, block_to_dict

    doc = roles_doc()
    again = block_from_dict(block_to_dict(doc.blocks["Öffner"]))
    assert (again.function, again.contact) == ("aux", "nc")
    plain = block_to_dict(doc.blocks["Schütz SLD"])
    assert "function" not in plain and "contact" not in plain


def test_device_dock_rename_everywhere(window):
    from sldgridy.model.devices import devices

    window._set_document(roles_doc(), None)
    dock = window.devices_dock
    dock.show()
    dock.rebuild()
    assert dock.tree.topLevelItemCount() == 2
    assert dock.rename("-K1", "-K5")
    assert "-K5" in devices(window.document) and "-K1" not in devices(window.document)
    assert window.crossref_lines()["coil"][0].startswith("S 13-14")
    window.act_undo.trigger()  # one step for all places
    assert "-K1" in devices(window.document)
    # Jump to the contact on page 2 of =PV1 +UV1.
    (occ,) = [o for o in devices(window.document)["-K1"] if o.entity_id == "no"]
    window.go_to_occurrence(occ)
    assert window.workspace == WORKSPACE_MLD
    assert window.sheets.current_sheet() is window.document.pages[1]
    assert window.selected_ids() == ["no"]


# -- step 4: nets and reports ----------------------------------------------------


def wired_doc() -> Document:
    """-Q1 (page 1) -> wire -> interruption L1 ... L1 (page 2) -> terminal -X1:1 ->
    cable -W1 (NYY-J 3x2,5) -> motor -M1."""
    from sldgridy.model.blocks import BlockDefinition
    from sldgridy.model.container import EntityContainer
    from sldgridy.model.entities import BlockReference, ConnectionPoint, InterruptionPoint, Wire

    doc = Document.new("Blatt 1")
    doc.pages = [new_page("Einspeisung", "PV1", "UV1"), new_page("Abgang", "PV1", "UV1")]

    def block(name, function="", terminals=("1", "2")):
        cps = [
            ConnectionPoint(id=f"c{i}", name=t, position=Point(0, 10 * i))
            for i, t in enumerate(terminals)
        ]
        return BlockDefinition(name=name, entities=EntityContainer(cps), function=function)

    doc.blocks["LS"] = block("LS", "main")
    doc.blocks["Klemme"] = block("Klemme", "terminal")
    doc.blocks["Motor"] = block("Motor", "main", ("U",))

    def ref(rid, name, bmk, x, y, typ=""):
        attrs = (("BMK", bmk),) + ((("TYP", typ),) if typ else ())
        return BlockReference(id=rid, name=name, insert=Point(x, y), attributes=attrs)

    p1, p2 = doc.pages
    p1.entities.add(ref("q1", "LS", "-Q1", 50, 40, "B16"))  # pins at (50,40) and (50,50)
    p1.entities.add(Wire(id="w1", points=(Point(50, 50), Point(50, 70), Point(270, 70))))
    p1.entities.add(InterruptionPoint(id="i1", name="L1", position=Point(270, 70)))
    p2.entities.add(InterruptionPoint(id="i2", name="L1", position=Point(30, 70), direction=180))
    p2.entities.add(Wire(id="w2", points=(Point(30, 70), Point(100, 70), Point(100, 80))))
    p2.entities.add(ref("x1", "Klemme", "-X1:1", 100, 80))  # pins (100,80), (100,90)
    p2.entities.add(
        Wire(id="w3", points=(Point(100, 90), Point(100, 120)), label="NYY-J 3x2,5", cable="-W1")
    )
    p2.entities.add(ref("m1", "Motor", "-M1", 100, 120, "1,5 kW"))
    doc.model_space.add(ref("q1sld", "LS", "-Q1", 0, 0, "B16"))
    return doc


def test_nets_follow_wires_and_interruption_points():
    from sldgridy.model.netlist import netlist

    nl = netlist(wired_doc())
    net = nl.net_of_pin("q1", "2")
    names = {f"{p.bmk}:{p.name}" for p in nl.pins_of_net(net)}
    assert names == {"-Q1:2", "-X1:1:1"}  # across the page via L1
    assert {f"{p.bmk}:{p.name}" for p in nl.pins_of_net(nl.net_of_pin("m1", "U"))} == {
        "-X1:1:2",
        "-M1:U",
    }


def test_report_rows():
    from sldgridy.model.reports import cable_rows, parts_rows, terminal_rows, toc_rows

    doc = wired_doc()
    assert toc_rows(doc) == [["=PV1 +UV1", "/1", "Einspeisung"], ["=PV1 +UV1", "/2", "Abgang"]]
    assert parts_rows(doc) == [
        ["1", "1", "LS", "", "B16", "-Q1"],
        ["2", "1", "Motor", "", "1,5 kW", "-M1"],
    ]
    assert terminal_rows(doc) == [["-X1", "1", "-Q1:2", "-M1:U", "=PV1 +UV1 /2.3"]]
    assert cable_rows(doc) == [["-W1", "NYY-J 3x2,5", "1", "-X1:1", "-M1", "=PV1 +UV1 /2.3"]]


def test_report_pages_and_csv(window, tmp_path):
    import csv

    window._set_document(wired_doc(), None)
    window.set_workspace(WORKSPACE_MLD)
    kinds = window.reports.create_pages()
    assert kinds == ["toc", "parts", "terminals", "cables"]
    pages = window.document.pages
    assert [p.report for p in pages] == ["", "", "toc", "parts", "terminals", "cables"]
    assert pages[2].name == "Inhaltsverzeichnis"
    texts = {e.text for e in pages[2].entities if hasattr(e, "text")}
    assert {"Stückliste", "/4"} <= texts  # the contents list the reports too
    # Creating them again replaces them; one undo removes all.
    window.reports.create_pages()
    assert len(window.document.pages) == 6
    window.act_undo.trigger()
    assert len(window.document.pages) == 6  # back to the first report set
    files = window.reports.export_csv(tmp_path)
    assert [f.name for f in files] == [
        "inhalt.csv",
        "stueckliste.csv",
        "klemmenplan.csv",
        "kabelliste.csv",
    ]
    with (tmp_path / "kabelliste.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0][0] == "Kabel" and rows[1][:3] == ["-W1", "NYY-J 3x2,5", "1"]
