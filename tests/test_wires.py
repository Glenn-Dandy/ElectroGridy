from dataclasses import replace

import pytest
from PyQt6.QtGui import QUndoStack

from blocks_fixtures import blocks
from sldgridy.fileio.files import load_library
from sldgridy.fileio.json_format import entity_from_dict, entity_to_dict
from sldgridy.fileio.paths import system_library_dir
from sldgridy.model.document import Document
from sldgridy.model.entities import BlockReference, Busbar, ConnectionPoint, Wire
from sldgridy.model.geometry import Point
from sldgridy.model.grips import move_grip
from sldgridy.model.snap import SnapMode, find_snap
from sldgridy.model.wires import (
    drag_end,
    elbow,
    follow_connections,
    junction_points,
    label_text,
    simplify,
)
from sldgridy.tools.controller import ToolController
from sldgridy.tools.draw import BusbarTool, WireTool
from sldgridy.tools.edit import MoveTool, RotateTool


def W(id_, *pts, **kw):
    return Wire(id=id_, points=tuple(Point(*p) for p in pts), **kw)


def test_elbow_and_simplify():
    assert elbow(Point(0, 0), Point(10, 0)) == [Point(10, 0)]
    assert elbow(Point(0, 0), Point(10, 5)) == [Point(10, 0), Point(10, 5)]
    assert elbow(Point(0, 0), Point(3, 10)) == [Point(0, 10), Point(3, 10)]
    pts = [Point(0, 0), Point(5, 0), Point(5, 0), Point(10, 0), Point(10, 5)]
    assert simplify(pts) == (Point(0, 0), Point(10, 0), Point(10, 5))


def test_junction_t_and_crossing():
    a = W("a", (0, 0), (20, 0))
    b = W("b", (10, 0), (10, 10))  # ends on a: T junction
    c = W("c", (5, -5), (5, 5))  # crosses a without ending: no junction
    assert junction_points([a, b, c]) == [Point(10, 0)]


def test_junction_three_ends_but_not_two():
    a = W("a", (0, 0), (10, 0))
    b = W("b", (10, 0), (10, 10))
    assert junction_points([a, b]) == []
    c = W("c", (10, 0), (20, 0))
    assert junction_points([a, b, c]) == [Point(10, 0)]


def test_label_on_longest_segment():
    w = W("w", (0, 0), (0, 30), (5, 30), label="NYY-J 5x16")
    t = label_text(w)
    assert t.rotation == 90 and t.position == Point(-1, 15) and t.halign == "center"
    h = W("h", (0, 0), (40, 0), label="X", label_side=-1)
    t = label_text(h)
    assert t.rotation == 0 and t.position == Point(20, 3.5)
    assert label_text(W("n", (0, 0), (1, 0))) is None


def test_drag_end_keeps_orthogonal():
    w = W("w", (0, 0), (10, 0), (10, 20))
    moved = drag_end(w, -1, Point(15, 25))
    assert moved.points == (Point(0, 0), Point(15, 0), Point(15, 25))
    single = W("s", (0, 0), (0, 20))
    assert drag_end(single, -1, Point(5, 25)).points == (
        Point(0, 0),
        Point(0, 25),
        Point(5, 25),
    )
    assert drag_end(single, 0, Point(0, -5)).points == (Point(0, -5), Point(0, 20))


def test_follow_connections_of_moved_block():
    b = blocks()
    ref = BlockReference(id="r", name="Sicherung", insert=Point(0, 0))
    wire = W("w", (0, 10), (0, 30), (20, 30))  # starts at connection 2
    other = W("o", (50, 50), (60, 50))
    moved = ref.translated(5, 0)
    (new,) = follow_connections([ref, wire, other], [ref], [moved], b)
    assert new.points[0] == Point(5, 10)
    assert all(p.x == q.x or p.y == q.y for p, q in zip(new.points, new.points[1:], strict=False))


def test_follow_translates_wire_between_two_moved_blocks():
    b = blocks()
    r1 = BlockReference(id="r1", name="Sicherung", insert=Point(0, 0))
    r2 = BlockReference(id="r2", name="Sicherung", insert=Point(0, 20))
    wire = W("w", (0, 10), (0, 20))
    new = follow_connections(
        [r1, r2, wire], [r1, r2], [r1.translated(3, 4), r2.translated(3, 4)], b
    )
    assert new[0].points == (Point(3, 14), Point(3, 24))


def test_wire_and_busbar_roundtrip_and_grips():
    w = W("w", (0, 0), (10, 0), label="L1", label_side=-1)
    bb = Busbar(id="b", p1=Point(0, 0), p2=Point(50, 0), lineweight=0.7)
    for e in (w, bb):
        assert entity_from_dict(entity_to_dict(e)) == e
    assert move_grip(w, 1, Point(10, 5)).points == (Point(0, 0), Point(10, 0), Point(10, 5))


def test_busbar_accepts_snap_anywhere():
    bb = Busbar(id="b", p1=Point(0, 0), p2=Point(50, 0))
    hit = find_snap(Point(17.3, 0.4), [bb], aperture=1)
    assert hit.mode is SnapMode.BUSBAR and hit.point == Point(17.3, 0)
    # With grid snap the point stays on the grid along the bar.
    assert find_snap(Point(17.3, 0.4), [bb], aperture=1, grid=2.5).point == Point(17.5, 0)


class Ctx:
    def __init__(self):
        self.document = Document.new("Blatt 1")
        self.stack = QUndoStack()
        self.selection = []

    container = property(lambda self: self.document.model_space)
    current_layer = property(lambda self: "0")
    block_definitions = property(lambda self: self.document.blocks)

    def push(self, c):
        self.stack.push(c)

    def selected_ids(self):
        return list(self.selection)

    def ask_text(self, *a):
        return None

    def message(self, t):
        pass


def test_wire_tool_inserts_corners():
    ctx = Ctx()
    tools = ToolController(ctx)
    tools.start(WireTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(20, 10))
    tools.pick(Point(20, 30))
    tools.finish()
    (wire,) = list(ctx.container)
    assert wire.points == (Point(0, 0), Point(20, 0), Point(20, 30))


def test_busbar_tool_is_orthogonal_and_thick():
    ctx = Ctx()
    tools = ToolController(ctx)
    tools.start(BusbarTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(40, 3))
    (bar,) = list(ctx.container)
    assert (bar.p1, bar.p2, bar.lineweight) == (Point(0, 0), Point(40, 0), 0.7)


def test_move_and_rotate_tool_drag_attached_wires():
    ctx = Ctx()
    ctx.document.blocks.update(blocks())
    ms = ctx.container
    ms.add(BlockReference(id="r", name="Sicherung", insert=Point(0, 0)))
    ms.add(W("w", (0, 10), (0, 30)))
    ctx.selection = ["r"]
    tools = ToolController(ctx)
    tools.start(MoveTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(0, -5))
    assert ms.get("w").points == (Point(0, 5), Point(0, 30))
    ctx.stack.undo()
    assert ms.get("w").points == (Point(0, 10), Point(0, 30))
    tools.start(RotateTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(10, 0.1))  # 0 quarters: nothing
    assert ms.get("w").points == (Point(0, 10), Point(0, 30))


def test_standalone_connection_point_drags_wire():
    a = ConnectionPoint(id="c", name="1", position=Point(0, 0))
    w = W("w", (0, 0), (10, 0))
    (new,) = follow_connections([a, w], [a], [a.translated(0, 5)], {})
    assert new.points[0] == Point(0, 5)


def test_shipped_library_complete():
    path = system_library_dir() / "din_en_60617.sldglib"
    title, defs = load_library(path)
    names = {d.name for d in defs}
    required = {
        "Leitungsschutzschalter",
        "Schmelzsicherung",
        "NH-Sicherungslasttrenner",
        "Lasttrennschalter",
        "Leistungsschalter",
        "Schütz",
        "Fehlerstromschutzschalter",
        "Überspannungsableiter",
        "Netzanschluss",
        "Hausanschlusskasten",
        "Zähler Bezug",
        "Zähler Lieferung",
        "Zähler Zweirichtung",
        "Stromwandler",
        "Transformator",
        "PV-Generator",
        "Wechselrichter",
        "Batteriespeicher",
        "Generator",
        "NA-Schutz",
        "Kuppelschalter",
        "Motor",
        "Verbraucher",
        "Ladeeinrichtung",
        "Wärmepumpe",
        "Erdung",
        "Potentialausgleichsschiene",
    }
    assert required <= names
    for d in defs:
        tags = {a.tag for a in d.attribute_definitions()}
        assert tags >= {"BMK", "TYP", "WERT"}, d.name
        assert d.connection_points(), d.name
        for c in d.connection_points():
            for v in (c.position.x, c.position.y):
                assert v / 2.5 == pytest.approx(round(v / 2.5)), (d.name, c.name)


def test_load_break_circles_centred_on_the_contact_below_the_bar():
    _, defs = load_library(system_library_dir() / "din_en_60617.sldglib")
    from sldgridy.model.entities import Circle, Line

    for d in defs:
        circles = [e for e in d.entities if isinstance(e, Circle) and e.radius == 0.75]
        for c in circles:
            assert c.center.y == 5, d.name  # centred on the switch contact
            top = c.center.y - c.radius
            bars = [
                e
                for e in d.entities
                if isinstance(e, Line) and e.p1.y == e.p2.y == top and e.p1.x == -1.25
            ]
            assert bars, d.name  # disconnector bar on top of the circle
            fixed = [e for e in d.entities if isinstance(e, Line) and e.p1 == Point(0, 0)]
            assert fixed and fixed[0].p2 == Point(0, top), d.name


def test_circuit_breaker_has_thermal_and_magnetic_release():
    _, defs = load_library(system_library_dir() / "din_en_60617.sldglib")
    ls = {d.name: d for d in defs}["Leitungsschutzschalter"]
    ids = {e.id for e in ls.entities}
    assert {"thermal", "magnetic", "link"} <= ids
    assert not ids & {"l6", "l7", "r8", "l9"}  # no breaker X, box or dashed link any more


def test_measuring_relays_and_pv_category():
    _, defs = load_library(system_library_dir() / "din_en_60617.sldglib")
    by = {d.name: d for d in defs}
    relay = by["Messrelais"]
    assert {a.tag for a in relay.attribute_definitions()} == {"BMK", "TYP", "WERT", "FUNKTION"}
    assert {c.name for c in relay.connection_points()} == {"1", "2", "3", "A"}
    assert {c.name for c in by["NA-Schutzrelais"].connection_points()} == {"1", "2", "3", "A"}
    pv = {d.name for d in defs if d.category == "Photovoltaik"}
    assert {"PV-Generator", "Wechselrichter", "NA-Schutzrelais"} <= pv
    assert "PV-Modul" not in by  # not a standard symbol: in the further symbols library


def test_further_symbols_library():
    title, defs = load_library(system_library_dir() / "weitere_symbole.sldglib")
    assert title == "SLD: Weitere Symbole (nicht nach DIN EN 60617)"
    by = {d.name: d for d in defs}
    shu = by["Selektiver Hauptschalter netzunabhängig"]
    sha = by["Selektiver Hauptschalter netzabhängig"]
    assert shu.category == sha.category == "Zählervorsicherung"
    assert by["PV-Modul"].category == "Photovoltaik"
    module = by["PV-Modul"]
    assert [(c.position, c.direction) for c in module.connection_points()] == [(Point(0, 0), 270)]
    triangle = next(e for e in module.entities if e.id == "tri")
    assert triangle.points[:2] == (Point(-5, -17.5), Point(5, -17.5))  # flush with the corners
    assert triangle.points[2] == Point(0, -11.25)  # apex half a grid step above the middle
    for d in defs:
        assert {a.tag for a in d.attribute_definitions()} >= {"BMK", "TYP", "WERT"}, d.name
        for c in d.connection_points():
            for v in (c.position.x, c.position.y):
                assert v / 2.5 == pytest.approx(round(v / 2.5)), (d.name, c.name)
    assert {c.name: c.position for c in shu.connection_points()} == {
        "1": Point(0, 0),
        "2": Point(0, 15),
    }
    assert {c.name: c.position for c in sha.connection_points()}["N"] == Point(2.5, 15)
    assert not any(getattr(e, "text", "") in ("1", "2") for e in sha.entities)


def test_circuit_breaker_thermal_release_parallel_to_link():
    import math

    _, defs = load_library(system_library_dir() / "din_en_60617.sldglib")
    ls = {d.name: d for d in defs}["Leitungsschutzschalter"]
    link = next(e for e in ls.entities if e.id == "link")
    thermal = next(e for e in ls.entities if e.id == "thermal")
    ldir = math.atan2(link.p2.y - link.p1.y, link.p2.x - link.p1.x)
    for a, b in zip(thermal.points, thermal.points[1:], strict=False):
        seg = math.atan2(b.y - a.y, b.x - a.x)
        diff = math.degrees(seg - ldir) % 180
        assert min(diff, 180 - diff) < 0.5 or abs(diff - 90) < 0.5  # parallel or square


def test_circuit_breaker_arrowhead_centred_on_link():
    import math

    _, defs = load_library(system_library_dir() / "din_en_60617.sldglib")
    ls = {d.name: d for d in defs}["Leitungsschutzschalter"]
    link = next(e for e in ls.entities if e.id == "link")
    tip, b1, b2 = next(e for e in ls.entities if e.id == "magnetic").points
    mid = Point((b1.x + b2.x) / 2, (b1.y + b2.y) / 2)
    assert mid.x == pytest.approx(link.p2.x, abs=1e-3) and mid.y == pytest.approx(
        link.p2.y, abs=1e-3
    )
    # The tip continues the link direction.
    d_link = math.atan2(link.p2.y - link.p1.y, link.p2.x - link.p1.x)
    d_tip = math.atan2(tip.y - mid.y, tip.x - mid.x)
    assert abs(d_link - d_tip) < 1e-3


def test_current_transformer_has_measuring_connection():
    _, defs = load_library(system_library_dir() / "din_en_60617.sldglib")
    ct = {d.name: d for d in defs}["Stromwandler"]
    conns = {c.name: (c.position, c.direction) for c in ct.connection_points()}
    assert conns["S"] == (Point(5, 7.5), 0)
    assert {"1", "2"} <= set(conns)


BOX_DEVICES = [
    "Wechselrichter",
    "Generatoranschlusskasten",
    "NA-Schutz",
    "NA-Schutzrelais",
    "PV-Generator",
    "Verbraucher",
    "Wärmepumpe",
    "Ladeeinrichtung",
    "Messrelais",
    "Schutzrelais",
    "Kurzschlussanzeiger",
    "Zähler Bezug",
    "Zähler Lieferung",
    "Zähler Zweirichtung",
]


@pytest.mark.parametrize("name", BOX_DEVICES)
def test_box_devices_have_four_connections_on_the_edges(name):
    from sldgridy.model.entities import Line, Rectangle

    _, defs = load_library(system_library_dir() / "din_en_60617.sldglib")
    d = {x.name: x for x in defs}[name]
    box = max(
        (e for e in d.entities if isinstance(e, Rectangle)),
        key=lambda r: abs(r.p2.x - r.p1.x) * abs(r.p2.y - r.p1.y),
    )
    x0, x1 = sorted((box.p1.x, box.p2.x))
    y0, y1 = sorted((box.p1.y, box.p2.y))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    conns = {(c.position.x, c.position.y): c.direction for c in d.connection_points()}
    assert conns == {(cx, y0): 90, (cx, y1): 270, (x0, cy): 180, (x1, cy): 0}
    assert "1" in {c.name for c in d.connection_points()}
    assert d.base_point == Point(0, 0)
    # No wire stubs: no line ends at a connection point outside the box.
    for line in (e for e in d.entities if isinstance(e, Line)):
        for p in (line.p1, line.p2):
            assert not (p.y < y0 - 1e-6 or p.y > y1 + 1e-6) or p.x != cx, name


def test_label_alignment_along_segment():
    h = W("h", (0, 0), (40, 0), label="X", label_align="left")
    t = label_text(h)
    assert t.halign == "left" and t.position == Point(2.5, -1)
    t = label_text(replace(h, label_align="right"))
    assert t.halign == "right" and t.position == Point(37.5, -1)
    # Vertical labels read bottom to top: left is the lower end.
    v = W("v", (0, 0), (0, 30), label="X", label_align="left", label_height=3.5)
    t = label_text(v)
    assert t.halign == "left" and t.position == Point(-1, 27.5) and t.height == 3.5
    assert label_text(replace(v, label_align="right")).position == Point(-1, 2.5)


@pytest.mark.parametrize(
    "library, name",
    [
        ("weitere_symbole", "PV-Modul"),
        ("din_en_60617", "Wechselrichter"),
        ("weitere_symbole", "Wallbox AC-gekoppelt"),
        ("weitere_symbole", "DC-Solarspeicher"),
    ],
)
def test_manufacturer_attribute_between_designation_and_type(library, name):
    _, defs = load_library(system_library_dir() / f"{library}.sldglib")
    definition = {d.name: d for d in defs}[name]
    atts = definition.attribute_definitions()
    assert [a.tag for a in atts][:4] == ["BMK", "HERSTELLER", "TYP", "WERT"]
    ys = [a.position.y for a in atts[:4]]
    assert all(b - a == pytest.approx(3.5) for a, b in zip(ys, ys[1:], strict=False))


def test_label_position_start_end_and_free():
    # Down 40 mm, then right 60 mm (like a feeder leaving a panel).
    w = W("w", (0, 0), (0, 40), (60, 40), label="NYY-J 5x16")
    t = label_text(replace(w, label_pos="start"))
    # Vertical first segment runs downwards: the text reads upwards, so it ends at the anchor.
    assert t.rotation == 90 and t.position == Point(-1, 2.5) and t.halign == "right"
    t = label_text(replace(w, label_pos="end"))
    assert t.rotation == 0 and t.position == Point(57.5, 39) and t.halign == "right"
    t = label_text(replace(w, label_pos="free", label_at=70))  # 30 mm into the bottom part
    assert t.rotation == 0 and t.position == Point(30, 39) and t.halign == "center"
    t = label_text(replace(w, label_pos="free", label_at=500))  # clamped to the end
    assert t.position.x == pytest.approx(60)


def test_label_grip_moves_label_along_wire():
    from sldgridy.model.grips import grip_points, move_grip

    w = W("w", (0, 0), (0, 40), (60, 40), label="X")
    # Ends, label point, then one grip per segment (the bottom one avoids the label).
    assert grip_points(w) == [
        Point(0, 0),
        Point(60, 40),
        Point(30, 40),
        Point(0, 20),
        Point(15, 40),
    ]
    assert grip_points(W("n", (0, 0), (0, 40))) == [Point(0, 0), Point(0, 40), Point(0, 20)]
    moved = move_grip(w, 2, Point(25, 43))  # beside the bottom segment
    assert moved.label_pos == "free" and moved.label_at == pytest.approx(65)
    assert grip_points(moved)[2] == Point(25, 40)
    assert moved.points == w.points


def test_segment_grip_moves_segment_and_keeps_the_ends():
    from sldgridy.model.grips import grip_points, move_grip
    from sldgridy.model.wires import move_segment

    # Junction at the left, across to x = 70, up to a battery at (70, 20).
    w = W("w", (0, 40), (70, 40), (70, 20))
    assert move_segment(w, 1, Point(40, 30)).points == (
        Point(0, 40),
        Point(40, 40),
        Point(40, 20),
        Point(70, 20),  # the end stays at the battery, a short piece leads to it
    )
    # The middle segment of a Z shape just moves; the neighbours stretch.
    z = W("z", (0, 0), (0, 20), (50, 20), (50, 40))
    assert move_segment(z, 1, Point(25, 30)).points == (
        Point(0, 0),
        Point(0, 30),
        Point(50, 30),
        Point(50, 40),
    )
    # Through the grips: index 2 is the first segment grip of an unlabelled wire.
    grips = grip_points(z)
    assert grips[3] == Point(25, 20)
    moved = move_grip(z, 3, Point(25, 30))
    assert moved.points[0] == z.points[0] and moved.points[-1] == z.points[-1]


def test_branch_follows_moved_wire_unless_separated():
    from sldgridy.model.entities import JunctionMark
    from sldgridy.model.wires import follow_wires, move_segment

    main = W("main", (0, 0), (0, 100))  # vertical LAN trunk
    branch = W("lan", (0, 40), (35, 40))  # T branch to the battery
    other = W("x", (50, 0), (50, 10))  # not attached
    mark = JunctionMark(id="m", position=Point(0, 40), connected=True)
    entities = [main, branch, other, mark]

    # Moved as a whole 10 mm to the left: the branch end and the dot go along.
    moved = main.translated(-10, 0)
    result = {e.id: e for e in follow_wires(entities, [main], [moved])}
    assert result["lan"].points == (Point(-10, 40), Point(35, 40))
    assert result["m"].position == Point(-10, 40)
    assert "x" not in result

    # Shifting one segment of an L-shaped trunk moves the branch on it.
    trunk = W("main", (0, 0), (0, 100), (60, 100))
    shifted = move_segment(trunk, 0, Point(-20, 50))
    result = {e.id: e for e in follow_wires([trunk, branch], [trunk], [shifted])}
    assert result["lan"].points[0] == Point(-20, 40)

    # Separated: the branch stays.
    cut = JunctionMark(id="m", position=Point(0, 40), connected=False)
    assert follow_wires([main, branch, cut], [main], [moved]) == []

    # End to end: a wire continuing at the moved end follows that end.
    tail = W("tail", (0, 100), (0, 130))
    stretched = replace(main, points=(Point(0, 0), Point(0, 110)))
    result = {e.id: e for e in follow_wires([main, tail], [main], [stretched])}
    assert result["tail"].points == (Point(0, 110), Point(0, 130))


def test_connection_mark_on_a_crossing_stays_on_the_crossing():
    from sldgridy.model.entities import JunctionMark
    from sldgridy.model.wires import follow_marks

    v = W("v", (0, 0), (0, 60))
    h = W("h", (-30, 30), (30, 30))
    mark = JunctionMark(id="m", position=Point(0, 30), connected=True)
    entities = [v, h, mark]
    (moved,) = follow_marks(entities, [v.translated(10, 0)])
    assert moved.position == Point(10, 30)
    (moved,) = follow_marks(entities, [h.translated(0, 10)])
    assert moved.position == Point(0, 40)
    # Moved away so far that they no longer cross: the mark stays.
    assert follow_marks(entities, [v.translated(100, 0)]) == []
    # A separation mark is not a connection and stays where it is.
    cut = JunctionMark(id="m", position=Point(0, 30), connected=False)
    assert follow_marks([v, h, cut], [v.translated(10, 0)]) == []
