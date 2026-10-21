import pytest
from PyQt6.QtCore import QSettings

from sldgridy.fileio.json_format import (
    BASE_VERSION,
    FORMAT_VERSION,
    document_from_dict,
    document_to_dict,
)
from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.document import (
    CABLES,
    CIRCUIT,
    COVER,
    PARTS,
    TERMINALS,
    TOC,
    Document,
    new_page,
)
from sldgridy.model.entities import AttributeDefinition, BlockReference, Line
from sldgridy.model.geometry import Point
from sldgridy.model.sheet import (
    column_at,
    column_edges,
    row_count,
    schematic_frame_entities,
    schematic_inner,
)
from sldgridy.ui.main_window import MainWindow


def doc_with_pages() -> Document:
    """Blatt 1 (old drawing sheet), then three circuit diagram pages."""
    doc = Document.new("Blatt 1")
    doc.sheets += [
        new_page(CIRCUIT, "Einspeisung", "PV1", "UV1"),
        new_page(CIRCUIT, "Zähler", "PV1", "UV1"),
        new_page(CIRCUIT, "Wechselrichter", "PV1", "WR"),
    ]
    return doc


# -- step 1: pages ----------------------------------------------------------------------


def test_pages_are_numbered_through_the_project():
    doc = doc_with_pages()
    p = doc.sheets
    assert [doc.page_number(x.id) for x in p] == [1, 2, 3, 4]
    assert doc.page_label(p[2].id) == "/3"
    doc.properties["ORT"] = "Erfurt"
    values = doc.field_values(p[2].id)
    assert (values["BLATTNR"], values["VON"], values["BLATT"]) == ("3", "4", "3 von 4")
    assert values["ANLAGE"] == "PV1" and values["ORT"] == "UV1"
    assert values["SEITENTYP"] == "Stromlaufplan" and values["TITEL"] == "Zähler"
    assert values["FORMAT"] == "A3 quer"
    assert doc.field_values(p[0].id)["ORT"] == "Erfurt"  # the project's place
    assert not p[1].viewports() and p[1].columns == 10


def test_circuit_diagram_frame():
    a, b = schematic_inner(420, 297)
    assert (a, b) == (Point(10, 20), Point(410, 287))  # 5 mm margins, top 15, 5 mm band
    assert row_count(420, 297) == 6 and row_count(297, 210) == 4
    edges = column_edges(420, 297, 10)
    assert edges[0] == 10 and edges[-1] == pytest.approx(410)
    assert column_at(420, 297, 10, 12) == 0
    assert column_at(420, 297, 10, 200) == 4
    assert column_at(420, 297, 10, 999) == 9
    assert column_at(420, 297, 0, 50) is None
    texts = {e.text for e in schematic_frame_entities(420, 297, 10) if hasattr(e, "text")}
    assert {"0", "9", "A", "F"} <= texts and "G" not in texts


def test_pages_roundtrip_and_format_version():
    doc = doc_with_pages()
    doc.sheets[1].entities.add(Line(id="l", p1=Point(30, 30), p2=Point(60, 30)))
    data = document_to_dict(doc)
    assert data["format_version"] == FORMAT_VERSION == 3
    again = document_from_dict(data)
    assert document_to_dict(again) == data
    assert [(x.kind, x.frame, x.plant, x.location) for x in again.sheets[1:]] == [
        (CIRCUIT, "schematic", "PV1", "UV1"),
        (CIRCUIT, "schematic", "PV1", "UV1"),
        (CIRCUIT, "schematic", "PV1", "WR"),
    ]
    plain = document_to_dict(Document.new("Blatt 1"))
    assert plain["format_version"] == BASE_VERSION  # still readable by 1.2


def test_pages_of_development_versions_are_taken_over():
    data = document_to_dict(Document.new("Blatt 1"))
    data["format_version"] = 3
    data["pages"] = [
        {"id": "p1", "name": "Einspeisung", "paper": "A4", "orientation": "landscape",
         "plant": "PV1", "columns": 10, "entities": []},
        {"id": "p2", "name": "Stückliste", "paper": "A4", "orientation": "landscape",
         "report": "parts", "entities": []},
    ]  # fmt: skip
    doc = document_from_dict(data)
    assert [(s.name, s.kind, s.frame) for s in doc.sheets] == [
        ("Blatt 1", "", ""),
        ("Einspeisung", CIRCUIT, "schematic"),
        ("Stückliste", PARTS, "schematic"),
    ]


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


def answer(window, monkeypatch, kind=CIRCUIT, name="", plant="", location="", viewport=False):
    from sldgridy.model.paper import Orientation
    from sldgridy.ui.page_dialog import PageSpec

    spec = PageSpec(kind, name, plant, location, "A3", Orientation.LANDSCAPE, viewport)
    monkeypatch.setattr(window.sheets, "_page_spec", lambda title, default, new: spec)


def test_new_pages_with_types(window, monkeypatch):
    sheets = window.sheets
    answer(window, monkeypatch, CIRCUIT, "Einspeisung", "PV1", "UV1")
    sheets.new_sheet()
    page = sheets.current_sheet()
    assert (page.kind, page.frame, page.paper) == (CIRCUIT, "schematic", "A3")
    assert page.title_block == "Schriftfeld Schaltplan 400" in window.document.blocks
    answer(window, monkeypatch, PARTS)
    sheets.new_sheet()
    texts = [sheets.tabs.tabText(i) for i in range(sheets.tabs.count())]
    assert texts == ["Modell", "Blatt 1", "2 Stromlaufplan Einspeisung", "3 Stückliste"]
    # Drawing on a page goes into the page.
    sheets.show_sheet(page.id)
    window.container.add(Line(id="x", p1=Point(30, 30), p2=Point(60, 30)))
    assert "x" in page.entities
    # Editing the type of an old sheet gives it the circuit diagram frame.
    sheets.show_sheet(window.document.sheets[0].id)
    answer(window, monkeypatch, CIRCUIT, "Übersicht")
    sheets.rename_sheet()
    first = window.document.sheets[0]
    assert (first.kind, first.frame, first.name) == (CIRCUIT, "schematic", "Übersicht")
    window.act_undo.trigger()
    assert (first.kind, first.frame) == ("", "")
    window.pages_dock.show()
    window.pages_dock.rebuild()
    assert window.pages_dock.tree.topLevelItemCount() == 3


def test_page_print_list(window):
    from sldgridy.ui.print_dialog import PrintDialog

    dialog = PrintDialog(window.document, window.sheets.current_sheet(), parent=window)
    assert dialog.rb_all.text() == "Alle Seiten"
    dialog.rb_all.setChecked(True)
    assert dialog.sheets() == window.document.sheets


def test_grid_shows_on_paper(window):
    window.sheets.tabs.setCurrentIndex(1)
    assert window.canvas.paper_item is window.space.extra["paper"]
    window.sheets.tabs.setCurrentIndex(0)
    assert window.canvas.paper_item is None


# -- step 2: interruption points ----------------------------------------------------


def ip(pid, name, x, y, direction=0):
    from sldgridy.model.entities import InterruptionPoint

    return InterruptionPoint(id=pid, name=name, position=Point(x, y), direction=direction)


def test_interruption_pairs_refer_to_each_other():
    from sldgridy.model.interruptions import interruption_targets, partner, unpaired_names

    doc = doc_with_pages()
    p = doc.sheets
    p[1].entities.add(ip("a", "L1", 400, 50))  # page 2, column 9
    p[2].entities.add(ip("b", "L1", 15, 50, 180))  # page 3, column 0
    p[3].entities.add(ip("c", "N", 200, 60))
    targets = interruption_targets(doc)
    assert targets["a"] == ("/3.0", p[2].id)
    assert targets["b"] == ("/2.9", p[1].id)
    assert "c" not in targets and unpaired_names(doc) == ["N"]
    p[1].entities.add(ip("d", "N", 270, 80))
    assert interruption_targets(doc)["d"] == ("/4.4", p[3].id)
    assert partner(doc, "c")[1].id == "d"
    doc.move_sheet(2, 1)  # page order changes the references
    assert interruption_targets(doc)["a"][0] == "/2.0"


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
    from sldgridy.model.entities import InterruptionPoint

    sheets = window.sheets
    assert window.act_interruption.isVisible()
    answer(window, monkeypatch, CIRCUIT, "Eins")
    sheets.new_sheet()
    first = sheets.current_sheet()
    names = iter(["L1", "L1"])
    monkeypatch.setattr(window, "ask_interruption_name", lambda: next(names))
    window.act_interruption.trigger()
    window.tools.pick(Point(400, 50))
    window.tools.pick(Point(405, 50))
    window.tools.cancel()
    answer(window, monkeypatch, CIRCUIT, "Zwei")
    sheets.new_sheet()
    second = sheets.current_sheet()
    window.act_interruption.trigger()
    window.tools.pick(Point(15, 50))
    window.tools.pick(Point(5, 50))
    window.tools.cancel()
    (a,) = [e for e in first.entities if isinstance(e, InterruptionPoint)]
    (b,) = [e for e in second.entities if isinstance(e, InterruptionPoint)]
    assert (a.direction, b.direction) == (0, 180)
    assert window.interruption_targets()[a.id][0] == "/3.0"
    window._edit_entity(b.id)
    assert sheets.current_sheet() is first
    assert window.selected_ids() == [a.id]


# -- step 3: devices and cross references ----------------------------------------------


def block(name, function, contact="", terminals=("A1", "A2")):
    from sldgridy.model.blocks import BlockDefinition
    from sldgridy.model.container import EntityContainer
    from sldgridy.model.entities import ConnectionPoint, Rectangle

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


def ref(rid, name, bmk, x, y=60, **attrs):
    from sldgridy.model.entities import BlockReference

    values = (("BMK", bmk), *attrs.items())
    return BlockReference(id=rid, name=name, insert=Point(x, y), attributes=tuple(values))


def roles_doc() -> Document:
    doc = doc_with_pages()
    doc.blocks["Spule"] = block("Spule", "main")
    doc.blocks["Schließer"] = block("Schließer", "aux", "no", ("13", "14"))
    doc.blocks["Öffner"] = block("Öffner", "aux", "nc", ("21", "22"))
    doc.blocks["Schütz SLD"] = block("Schütz SLD", "")
    p = doc.sheets
    p[1].entities.add(ref("coil", "Spule", "-K1", 40))  # page 2, column 0
    p[2].entities.add(ref("no", "Schließer", "-K1", 210))  # page 3, column 5
    p[3].entities.add(ref("nc", "Öffner", "-K1", 395))  # page 4, column 9
    doc.model_space.add(ref("sld", "Schütz SLD", "-K1", 0, 0))
    doc.model_space.add(ref("sld2", "Schütz SLD", "-K2", 0, 50))
    doc.model_space.add(ref("sld3", "Schütz SLD", "-K2", 0, 80))
    return doc


def test_device_occurrences_and_cross_references():
    from sldgridy.model.devices import crossref_texts, crossrefs, devices, problems

    doc = roles_doc()
    found = devices(doc)
    assert list(found) == ["-K1", "-K2"]
    assert [o.where for o in found["-K1"]] == ["model", "sheet", "sheet", "sheet"]
    xr = crossrefs(doc)
    assert xr["coil"] == ["S 13-14  /3.5", "Ö 21-22  /4.9"]
    assert xr["no"] == ["/2.0"] and xr["nc"] == ["/2.0"]
    assert "sld" not in xr
    assert problems(doc) == {"-K2": ["sld_twice"]}
    texts = crossref_texts(doc.sheets[1].entities.get("coil"), doc.blocks, xr["coil"])
    assert [t.text for t in texts] == xr["coil"]
    assert texts[0].position.y > 70  # under the symbol


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
    window.act_undo.trigger()
    assert "-K1" in devices(window.document)
    (occ,) = [o for o in devices(window.document)["-K1"] if o.entity_id == "no"]
    window.go_to_occurrence(occ)
    assert window.sheets.current_sheet() is window.document.sheets[2]
    assert window.selected_ids() == ["no"]


# -- step 4: nets and lists ---------------------------------------------------------


def wired_doc() -> Document:
    """-Q1 (page 2) -> wire -> L1 ... L1 (page 3) -> terminal -X1:1 -> cable -W1 -> -M1."""
    from sldgridy.model.entities import InterruptionPoint, Wire

    doc = Document.new("Blatt 1")
    doc.sheets += [new_page(CIRCUIT, "Einspeisung", "PV1"), new_page(CIRCUIT, "Abgang", "PV1")]
    doc.blocks["LS"] = block("LS", "main", terminals=("1", "2"))
    doc.blocks["Klemme"] = block("Klemme", "terminal", terminals=("1", "2"))
    doc.blocks["Motor"] = block("Motor", "main", terminals=("U",))
    doc.blocks["LS"].description = "Leitungsschutzschalter"
    p1, p2 = doc.sheets[1], doc.sheets[2]
    p1.entities.add(ref("q1", "LS", "-Q1", 50, 40, TYP="B16", HERSTELLER="Hager"))
    p1.entities.add(Wire(id="w1", points=(Point(50, 50), Point(50, 70), Point(400, 70))))
    p1.entities.add(InterruptionPoint(id="i1", name="L1", position=Point(400, 70)))
    p2.entities.add(InterruptionPoint(id="i2", name="L1", position=Point(15, 70), direction=180))
    p2.entities.add(Wire(id="w2", points=(Point(15, 70), Point(100, 70), Point(100, 80))))
    p2.entities.add(ref("x1", "Klemme", "-X1:1", 100, 80))
    p2.entities.add(
        Wire(id="w3", points=(Point(100, 90), Point(100, 120)), label="NYY-J 3x2,5", cable="-W1")
    )
    p2.entities.add(ref("m1", "Motor", "-M1", 100, 120, TYP="1,5 kW"))
    doc.model_space.add(ref("q1sld", "LS", "-Q1", 0, 0))
    return doc


def test_nets_follow_wires_and_interruption_points():
    from sldgridy.model.netlist import netlist

    nl = netlist(wired_doc())
    names = {f"{p.bmk}:{p.name}" for p in nl.pins_of_net(nl.net_of_pin("q1", "2"))}
    assert names == {"-Q1:2", "-X1:1:1"}
    assert {f"{p.bmk}:{p.name}" for p in nl.pins_of_net(nl.net_of_pin("m1", "U"))} == {
        "-X1:1:2",
        "-M1:U",
    }


def test_list_rows():
    from sldgridy.model.reports import cable_rows, parts_rows, terminal_rows, toc_rows

    doc = wired_doc()
    assert toc_rows(doc)[1] == ["=PV1", "", "2", "Stromlaufplan", "Einspeisung", "", ""]
    assert parts_rows(doc) == [
        ["-M1", "", "1,5 kW", "Motor", "3", "2"],
        ["-Q1", "Hager", "B16", "Leitungsschutzschalter", "2", "1"],
        ["-X1:1", "", "", "Klemme", "3", "2"],
    ]
    assert terminal_rows(doc) == [["-X1", "1", "-Q1:2", "-M1:U", "3", "2"]]
    assert cable_rows(doc) == [["-W1", "NYY-J 3x2,5", "1", "-X1:1", "-M1", "3"]]


def test_generated_pages_follow_the_project():
    from sldgridy.model.entities import Text
    from sldgridy.model.reports import generated_entities, report_rows, table_area

    doc = wired_doc()
    parts = new_page(PARTS)
    cover = new_page(COVER)
    doc.sheets += [parts, cover]
    doc.properties.update({"KUNDE": "Stadtwerke", "FIRMA": "FS", "ADRESSE": "Weg 1, 99087 Erfurt"})

    def texts(page):
        rows = lambda kind: report_rows(doc, kind)  # noqa: E731
        return [
            e.text for e in generated_entities(doc, page, rows, helpers=True) if isinstance(e, Text)
        ]

    assert {"Stückliste", "BMK", "-Q1", "Hager"} <= set(texts(parts))
    assert {"Stadtwerke", "Weg 1", "99087 Erfurt", "5"} <= set(texts(cover))
    # A long list on one page: the rest is announced (screen only).
    many = table_area(parts).rows + 3
    rows_of = lambda kind: [[f"-K{i}", "", "", "", "", ""] for i in range(many)]  # noqa: E731
    shown = [
        e.text for e in generated_entities(doc, parts, rows_of, helpers=True) if isinstance(e, Text)
    ]
    assert any("3" in t and "Zeilen" in t for t in shown)
    printed = [e.text for e in generated_entities(doc, parts, rows_of) if isinstance(e, Text)]
    assert not any("Zeilen" in t for t in printed)


def test_complete_pages_and_csv(window, tmp_path):
    import csv

    window._set_document(wired_doc(), None)
    added = window.reports.complete_pages()
    assert added == [COVER, TOC, PARTS, TERMINALS, CABLES]
    kinds = [p.kind for p in window.document.sheets]
    assert kinds == [COVER, TOC, "", CIRCUIT, CIRCUIT, PARTS, TERMINALS, CABLES]
    assert window.reports.complete_pages() == []  # nothing missing any more
    window.act_undo.trigger()
    window.act_undo.trigger()
    assert len(window.document.sheets) == 3
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


def test_suggest_bmk_counts_up_and_contacts_take_the_last():
    from sldgridy.model.devices import suggest_bmk

    doc = Document()
    assert suggest_bmk(doc, "-Q1") == "-Q1"
    doc.blocks["S"] = BlockDefinition(
        name="S",
        entities=(AttributeDefinition(id="a", tag="BMK", default="-Q1", position=Point(0, 0)),),
    )
    for i, bmk in enumerate(("-Q1", "-Q3", "-X1:1", "-X1:2", "-X10:7")):
        doc.model_space.add(
            BlockReference(id=f"r{i}", name="S", insert=Point(0, 0), attributes=(("BMK", bmk),))
        )
    assert suggest_bmk(doc, "-Q1") == "-Q4"
    assert suggest_bmk(doc, "-Q1", "aux") == "-Q3"
    assert suggest_bmk(doc, "-X1:1") == "-X1:3"
    assert suggest_bmk(doc, "-X1:PE") == "-X1:PE"
    assert suggest_bmk(doc, "-K1") == "-K1"
