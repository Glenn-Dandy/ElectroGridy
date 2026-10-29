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
    DOC_PROJECT,
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
    schematic_outer,
    schematic_title_width,
)
from sldgridy.model.title_block import (
    schematic_title_block_definition,
    schematic_title_block_name,
)
from sldgridy.ui.main_window import MainWindow


def doc_with_pages() -> Document:
    """Blatt 1 (old drawing sheet), then three circuit diagram pages (A3)."""
    doc = Document.new("Blatt 1", kind=DOC_PROJECT)
    doc.sheets += [
        new_page(CIRCUIT, "Einspeisung", "PV1", "UV1", paper="A3"),
        new_page(CIRCUIT, "Zähler", "PV1", "UV1", paper="A3"),
        new_page(CIRCUIT, "Wechselrichter", "PV1", "WR", paper="A3"),
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
    # A4: margins 5 mm, top 15, then the 3.5 mm band.
    assert schematic_inner(297, 210) == (Point(8.5, 18.5), Point(288.5, 201.5))
    # A3: margins enlarged so that the page fitted onto A4 has exactly those.
    a, b = schematic_inner(420, 297)
    assert (a, b) == (Point(10.6, 24.7), Point(409.4, 286.4))
    assert row_count(420, 297) == 6 and row_count(297, 210) == 4
    edges = column_edges(420, 297, 10)
    assert edges[0] == 10.6 and edges[-1] == pytest.approx(409.4)
    assert column_at(420, 297, 10, 13) == 0
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
    w._set_document(Document.new("Blatt 1", kind=DOC_PROJECT), None)
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
    assert page.title_block == "Schriftfeld Schaltplan 398.8" in window.document.blocks
    answer(window, monkeypatch, PARTS)
    sheets.new_sheet()
    texts = [sheets.tabs.tabText(i) for i in range(sheets.tabs.count())]
    assert texts == ["Blatt 1", "2 Stromlaufplan Einspeisung", "3 Stückliste"]
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
    window.sheets.tabs.setCurrentIndex(0)
    assert window.canvas.paper_item is window.space.extra["paper"]
    window.activate_space(window.model_view)
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


def test_interruption_point_on_a_wire_end_takes_one_click(window, monkeypatch):
    from sldgridy.model.entities import InterruptionPoint, Wire

    answer(window, monkeypatch, CIRCUIT, "Eins")
    window.sheets.new_sheet()
    page = window.sheets.current_sheet()
    page.entities.add(Wire(id="w", points=(Point(100, 80), Point(200, 80), Point(200, 120))))
    monkeypatch.setattr(window, "ask_interruption_name", lambda: "K1")
    window.act_interruption.trigger()
    for end in (Point(100, 80), Point(200, 120)):
        window.tools.hover(end)
        (preview,) = window.tools.preview()
        window.tools.pick(end)
    window.tools.cancel()
    points = sorted(
        (e for e in page.entities if isinstance(e, InterruptionPoint)), key=lambda e: e.position.x
    )
    assert [(e.position, e.direction) for e in points] == [
        (Point(100, 80), 180),
        (Point(200, 120), 270),
    ]
    assert preview.direction == 270


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

    doc = Document.new("Blatt 1", kind=DOC_PROJECT)
    doc.sheets += [
        new_page(CIRCUIT, "Einspeisung", "PV1", paper="A3"),
        new_page(CIRCUIT, "Abgang", "PV1", paper="A3"),
    ]
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
        ["-Q1", "Hager", "B16", "Leitungsschutzschalter", "2", "0"],
        ["-X1:1", "", "", "Klemme", "3", "2"],
    ]
    # Target 1 is the side with the cable.
    assert terminal_rows(doc) == [["-X1", "1", "", "-M1:U", "-Q1:2", "-W1", "", "3", "2", ""]]
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


def strip_doc() -> Document:
    """A 24 V rail feeding -X1:1..3 (each on to a device), two PE terminals and -X1:6
    with cable -W1 (core bl) to -Y4."""
    from sldgridy.model.entities import Wire

    doc = Document.new("Blatt 1", kind=DOC_PROJECT)
    doc.sheets.append(new_page(CIRCUIT, "Steuerung", paper="A3"))
    page = doc.sheets[1]
    doc.blocks["Klemme"] = block("Klemme", "terminal", terminals=("1", "2"))
    doc.blocks["Klemme PE"] = block("Klemme PE", "terminal", terminals=("1", "2"))
    doc.blocks["Gerät"] = block("Gerät", "main", terminals=("1",))
    page.entities.add(ref("g1", "Gerät", "-G1", 20, 60))
    page.entities.add(Wire(id="rail", points=(Point(20, 60), Point(300, 60))))
    for n, x in ((1, 50), (2, 100), (3, 150)):
        page.entities.add(Wire(id=f"a{n}", points=(Point(x, 60), Point(x, 80))))
        page.entities.add(ref(f"x{n}", "Klemme", f"-X1:{n}", x, 80))
        page.entities.add(Wire(id=f"b{n}", points=(Point(x, 90), Point(x, 110))))
        page.entities.add(ref(f"y{n}", "Gerät", f"-Y{n}", x, 110))
    page.entities.add(ref("pe4", "Klemme PE", "-X1:4", 200, 80))
    page.entities.add(ref("pe5", "Klemme PE", "-X1:5", 220, 80))
    page.entities.add(ref("x6", "Klemme", "-X1:6", 250, 80))
    page.entities.add(
        Wire(
            id="c6",
            points=(Point(250, 90), Point(250, 110)),
            cable="-W1",
            core="bl",
            label="ÖLFLEX 3G1,5",
        )
    )
    page.entities.add(ref("y4", "Gerät", "-Y4", 250, 110))
    return doc


def test_terminal_plan_targets_bridges_and_cables():
    from sldgridy.model.terminal_plan import plan_pages, terminal_plan

    (plan,) = terminal_plan(strip_doc())
    assert plan.strip == "-X1"
    rows = {r.number: r for r in plan.rows}
    # Each terminal shows its nearest device, not the whole rail; the source a bridged
    # run shares only once.
    assert [(rows[n].target1, rows[n].target2) for n in "123"] == [
        ("-G1:1", "-Y1:1"),
        ("", "-Y2:1"),
        ("", "-Y3:1"),
    ]
    assert plan.bridges == [(0, 2)]  # 1 to 3 on one rail
    assert plan.pe_rows == [3, 4] and rows["4"].color == "PE"
    # The cable side is target 1.
    assert (rows["6"].target1, rows["6"].cores1) == ("-Y4:1", {"-W1": "bl"})
    assert plan.cables1 == [("-W1", "ÖLFLEX 3G1,5")] and plan.cables2 == []
    assert [first for _p, first in plan_pages([plan] * 2)] == [0, 0]
    many = plan.rows * 9  # 54 rows, 24 per page: three pages
    assert len(plan_pages([type(plan)("-X2", many, [], [], [], [])])) == 3


def test_terminal_plan_page_follows_the_form():
    from sldgridy.model.entities import Circle, Text
    from sldgridy.model.reports import generated_entities, pages_needed, report_rows

    doc = strip_doc()
    page = new_page(TERMINALS, paper="A3")
    doc.sheets.append(page)
    parts = generated_entities(doc, page, lambda kind: report_rows(doc, kind))
    texts = {e.text for e in parts if isinstance(e, Text)}
    assert {"Klemmleiste:", "-X1", "Ziel 1", "Ziel 2", "Farbe", "-W1", "bl", "-Y4:1"} <= texts
    assert {"ÖLFLEX 3G1,5", "PE", "6", "Blatt", "Pfad"} <= texts
    circles = [e for e in parts if isinstance(e, Circle)]
    # Six terminals; 1 to 3 and the PE pair bridged (inner dot), one junction dot each.
    assert len([c for c in circles if c.radius > 1]) == 6
    assert len([c for c in circles if 0.4 < c.radius < 1]) == 5
    assert pages_needed(doc, TERMINALS, 0) == 1
    # Within the inner frame, above the title block.
    a, b = schematic_inner(*page.size)
    ys = [y for e in parts if hasattr(e, "p1") for y in (e.p1.y, e.p2.y)]
    assert min(ys) >= a.y - 1e-6 and max(ys) <= b.y - 20 + 1e-6


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


def test_rail_ends_refer_to_the_neighbouring_pages():
    from sldgridy.model.interruptions import interruption_targets

    doc = doc_with_pages()
    p = doc.sheets
    for page in p[1:]:  # L1 across pages 2, 3 and 4
        page.entities.add(ip(f"l{page.id}", "L1", 25, 30, 180))
        page.entities.add(ip(f"r{page.id}", "L1", 390, 30, 0))
    targets = interruption_targets(doc)
    assert f"l{p[1].id}" not in targets and f"r{p[3].id}" not in targets  # chain ends
    assert targets[f"r{p[1].id}"][0] == "/3.0" and targets[f"l{p[2].id}"][0] == "/2.9"
    alone = doc_with_pages()
    alone.sheets[1].entities.add(ip("x", "N", 25, 30, 180))
    alone.sheets[1].entities.add(ip("y", "N", 390, 30, 0))
    assert interruption_targets(alone) == {}  # one rail on one page
    # A conductor leaving on the right and coming back further down on the left of the
    # same page is a pair, not a rail.
    jump = doc_with_pages()
    jump.sheets[1].entities.add(ip("o", "K1", 300, 30, 0))
    jump.sheets[1].entities.add(ip("i", "K1", 50, 80, 180))
    targets = interruption_targets(jump)
    assert (targets["o"][0], targets["i"][0]) == ("/2.0", "/2.7")


def test_new_project_is_a4_and_the_cover_fits_a3_and_a4():
    from sldgridy.model.entities import Text
    from sldgridy.model.paper import Orientation
    from sldgridy.model.reports import cover_entities
    from sldgridy.model.title_block import SCHEMATIC_TITLE_HEIGHT

    doc = Document.new_project()
    cover, page = doc.sheets
    assert (page.paper, page.orientation) == ("A4", Orientation.LANDSCAPE)
    doc.properties.update({"ADRESSE": "Weg 1, 99087 Erfurt, Haus 2", "FIRMA": "FS"})
    for sheet in (cover, new_page(COVER, paper="A3")):
        _a, b = schematic_inner(*sheet.size)
        texts = [e for e in cover_entities(doc, sheet) if isinstance(e, Text)]
        assert max(t.position.y for t in texts) < b.y - SCHEMATIC_TITLE_HEIGHT


def test_a3_page_fitted_onto_a4_prints_with_the_standard_margins():
    from sldgridy.printing.layout import fit

    (page,) = fit(420, 297, 210, 297)
    a, b = schematic_outer(420, 297)
    left, top = page.to_page(a.x, a.y)
    right, bottom = page.to_page(b.x, b.y)
    assert (page.width, page.height) == (297, 210)
    assert left == pytest.approx(5, abs=0.05) and 297 - right == pytest.approx(5, abs=0.05)
    assert top == pytest.approx(15, abs=0.05) and 210 - bottom == pytest.approx(5, abs=0.05)


def test_title_blocks_of_older_files_follow_the_frame():
    doc = Document.new_project()
    old = schematic_title_block_definition(400)
    doc.blocks[old.name] = old
    for page in doc.sheets:
        page.title_block = old.name
    name = schematic_title_block_name(schematic_title_width(297, 210))  # A4 landscape
    del doc.blocks[name]
    assert doc.fit_schematic_title_blocks()
    assert {p.title_block for p in doc.sheets} == {name}
    assert old.name not in doc.blocks and name in doc.blocks
    assert not doc.fit_schematic_title_blocks()


def test_logos_of_company_and_customer_in_the_title_block(qapp, tmp_path, monkeypatch):
    from PyQt6.QtGui import QColor, QImage

    from sldgridy.fileio.files import load_library
    from sldgridy.fileio.paths import user_library_dir
    from sldgridy.model.entities import RasterImage
    from sldgridy.model.title_block import LOGO_CATEGORY, schematic_logo_boxes
    from sldgridy.ui.sheet_dialogs import FieldsDialog
    from sldgridy.view.display import title_block_parts

    QSettings().clear()
    window = MainWindow()
    try:
        window.new_document(DOC_PROJECT)
        page = window.document.sheets[-1]
        window.sheets.show_sheet(page.id)
        # A wide PNG and an SVG become blocks in "Eigene Logos", category Logos.
        png = tmp_path / "firma.png"
        image = QImage(800, 100, QImage.Format.Format_ARGB32)
        image.fill(QColor("#1565c0"))
        image.save(str(png))
        svg = tmp_path / "kunde.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="red"/></svg>'
        )
        names = iter(["Firma", "Kunde"])
        monkeypatch.setattr(
            "PyQt6.QtWidgets.QInputDialog.getText", lambda *a, **k: (next(names), True)
        )
        # From the menu (dev6 hung there: triggered(False) came in as the path).
        monkeypatch.setattr(
            "PyQt6.QtWidgets.QFileDialog.getOpenFileName", lambda *a, **k: (str(png), "")
        )
        window.blocks.act_import_logo.trigger()
        assert window.blocks.import_logo(svg) == "Kunde"
        title, mine = load_library(user_library_dir() / "logos.sldglib")
        assert title == "Eigene Logos"
        logos = {b.name: b for b in mine if b.category == LOGO_CATEGORY}
        assert set(logos) == {"Firma", "Kunde"}
        assert isinstance(next(iter(logos["Kunde"].entities)), RasterImage)
        assert set(window.blocks.available_logos()) >= {"Firma", "Kunde"}

        # Chosen while filling in the title block: copied into the drawing.
        def answer(dialog):
            dialog.logos["FIRMA"].choose("Firma")
            dialog.logos["KUNDE"].choose("Kunde")
            return 1

        monkeypatch.setattr(FieldsDialog, "exec", answer)
        window.sheets.edit_fields()
        doc = window.document
        assert doc.properties["FIRMA_LOGO"] == "Firma" and "Kunde" in doc.blocks
        pictures = [p for p in title_block_parts(doc, page) if isinstance(p, RasterImage)]
        assert len(pictures) == 2
        # Inside its box, as large as fits: the wide logo fills the width.
        width = schematic_title_width(*page.size)
        a, b = schematic_logo_boxes(width)["FIRMA"]
        insert = schematic_inner(*page.size)[1]
        firma = min(pictures, key=lambda p: p.p1.x)
        left, right = sorted((firma.p1.x, firma.p2.x))
        assert left == pytest.approx(a.x + insert.x) and right == pytest.approx(b.x + insert.x)
        window.act_undo.trigger()  # one step: properties and logo blocks
        assert "FIRMA_LOGO" not in doc.properties and "Kunde" not in doc.blocks
    finally:
        window.undo_stack.setClean()
        window.close()


def test_logos_from_my_symbols_move_to_my_logos(tmp_path):
    from sldgridy.fileio.files import load_library, save_library
    from sldgridy.fileio.library_merge import move_category
    from sldgridy.model.blocks import BlockDefinition

    symbols, logos = tmp_path / "eigene.sldglib", tmp_path / "logos.sldglib"
    save_library(
        [BlockDefinition("Logo A", category="Logos"), BlockDefinition("Schalter")],
        symbols,
        "Eigene Symbole",
    )
    save_library([BlockDefinition("Logo A", category="Logos", description="anders")], logos, "L")
    assert move_category(symbols, logos, "Logos", "Eigene Logos") == 1
    assert [b.name for b in load_library(symbols)[1]] == ["Schalter"]
    assert sorted(b.name for b in load_library(logos)[1]) == ["Logo A", "Logo A (2)"]
    assert move_category(symbols, logos, "Logos", "Eigene Logos") == 0


def test_logo_dialog_shows_the_library(qapp):
    from PyQt6.QtGui import QColor, QImage

    from sldgridy.model.blocks import BlockDefinition
    from sldgridy.model.container import EntityContainer
    from sldgridy.ui.picture_import import picture_entity
    from sldgridy.ui.sheet_dialogs import LogoDialog

    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("#1565c0"))
    logos = {
        n: BlockDefinition(n, entities=EntityContainer([picture_entity(image, 40, False)]))
        for n in ("A", "B")
    }
    dialog = LogoDialog("B", lambda: logos, None)
    assert dialog.list.count() == 2 and dialog.chosen() == "B" and dialog.empty.isHidden()
    dialog._none()
    assert dialog.chosen() == ""
    assert not LogoDialog("", lambda: {}, None).empty.isHidden()


def test_title_block_texts_fit_their_fields(qapp):
    from PyQt6.QtGui import QColor, QImage

    from sldgridy.model.blocks import BlockDefinition
    from sldgridy.model.container import EntityContainer
    from sldgridy.model.entities import RasterImage, Text
    from sldgridy.ui.picture_import import picture_entity
    from sldgridy.view.display import title_block_parts
    from sldgridy.view.render import text_width

    doc = Document.new_project()
    page = doc.sheets[1]
    image = QImage(300, 300, QImage.Format.Format_ARGB32)
    image.fill(QColor("#2e7d32"))
    doc.blocks["Logo"] = BlockDefinition(
        "Logo", entities=EntityContainer([picture_entity(image, 40, False)]), category="Logos"
    )
    long_name = "Stadtwerke Musterstadt GmbH"
    doc.properties.update({"KUNDE": long_name, "KUNDE_LOGO": "Logo", "PROJEKT": "TST"})
    parts = title_block_parts(doc, page)
    texts = {p.text: p for p in parts if isinstance(p, Text)}
    (logo,) = [p for p in parts if isinstance(p, RasterImage)]
    name, project = texts[long_name], texts["TST"]
    assert name.position.x > max(logo.p1.x, logo.p2.x)  # right of the logo
    assert 1.2 < name.height < 2.5  # made smaller until it fits
    from sldgridy.model.title_block import schematic_text_boxes

    width = schematic_title_width(*page.size)
    right = schematic_text_boxes(width)["KUNDE"][1] + schematic_inner(*page.size)[1].x
    assert name.position.x + text_width(name.text, name.height) <= right + 0.01
    # Far too long: not below the readable height.
    doc.properties["KUNDE"] = "Stadtwerke Musterstadt Netzgesellschaft mbH und Co. KG"
    parts = title_block_parts(doc, page)
    assert min(p.height for p in parts if isinstance(p, Text) and p.id == "att_kunde") == 1.2
    assert project.height == 5.0  # a few letters: large
    assert "A4 quer" not in texts and "Stromlaufplan" in texts  # page type, no format


def test_older_title_block_of_the_same_width_is_replaced_on_opening():
    """dev9 kept the old layout ("A4 quer", page type in the number field) in files
    whose width had not changed (Florian's screenshot 2026-10-28)."""
    from sldgridy.model.entities import AttributeDefinition

    doc = Document.new_project()
    name = doc.sheets[1].title_block
    old = doc.blocks[name].copy()
    old.description = f"Schriftfeld für Schaltpläne, {name.split()[-1]} mm breit"
    old.entities.add(AttributeDefinition(id="att_format", tag="FORMAT", position=Point(-50, -5)))
    doc.blocks[name] = old
    data = document_to_dict(doc)
    loaded = document_from_dict(data)
    assert loaded.fit_schematic_title_blocks()
    tags = {a.tag for a in loaded.blocks[name].attribute_definitions()}
    assert "FORMAT" not in tags and "PROJEKT" in tags
    assert not loaded.fit_schematic_title_blocks()  # current now: nothing to do


def test_customer_with_address_in_several_lines(qapp):
    from sldgridy.model.entities import Text
    from sldgridy.model.reports import cover_entities
    from sldgridy.model.title_block import LOGO_BOTTOM, LOGO_TOP
    from sldgridy.ui.sheet_dialogs import FieldsDialog, MultiLineEdit
    from sldgridy.view.display import title_block_parts

    customer = "Stadtwerke Musterstadt\nHauptstraße 12\n07407 Rudolstadt"
    dialog = FieldsDialog({"KUNDE": customer}, {}, "Blatt")
    edit = dialog._doc_edits["KUNDE"]
    assert isinstance(edit, MultiLineEdit) and dialog.properties()["KUNDE"] == customer
    doc = Document.new_project()
    doc.properties["KUNDE"] = customer
    page = doc.sheets[1]
    lines = [
        p
        for p in title_block_parts(doc, page)
        if isinstance(p, Text) and p.id.startswith("att_kunde")
    ]
    assert [t.text for t in lines] == customer.split("\n")
    assert len({t.position.x for t in lines}) == 1 and len({t.height for t in lines}) == 1
    ys = [t.position.y for t in lines]
    assert ys == sorted(ys)  # top to bottom
    bottom = schematic_inner(*page.size)[1].y
    h = lines[0].height
    assert (
        ys[0] - h / 2 >= bottom + LOGO_TOP - 0.01 and ys[-1] + h / 2 <= bottom + LOGO_BOTTOM + 0.01
    )
    cover = {t.text for t in cover_entities(doc, doc.sheets[0]) if isinstance(t, Text)}
    assert set(customer.split("\n")) <= cover


def test_company_in_several_lines(qapp):
    from sldgridy.model.entities import Text
    from sldgridy.model.reports import cover_entities
    from sldgridy.ui.sheet_dialogs import FieldsDialog, MultiLineEdit
    from sldgridy.view.display import title_block_parts

    company = "Elektro Muster GmbH\nIndustriestraße 5"
    dialog = FieldsDialog({"FIRMA": company}, {}, "Blatt")
    assert isinstance(dialog._doc_edits["FIRMA"], MultiLineEdit)
    doc = Document.new_project()
    doc.properties["FIRMA"] = company
    lines = [
        p.text
        for p in title_block_parts(doc, doc.sheets[1])
        if isinstance(p, Text) and p.id.startswith("att_firma")
    ]
    assert lines == company.split("\n")
    cover = [t.text for t in cover_entities(doc, doc.sheets[0]) if isinstance(t, Text)]
    assert cover.index("Industriestraße 5") == cover.index("Elektro Muster GmbH") + 1
    # The plain title block has one line for the company: the lines joined by commas.
    plain = Document.new("Blatt 1")
    plain.properties["FIRMA"] = company
    texts = {getattr(p, "text", None) for p in title_block_parts(plain, plain.sheets[0])}
    assert "Elektro Muster GmbH, Industriestraße 5" in texts
