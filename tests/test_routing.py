from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.entities import BlockReference, ConnectionPoint, Wire
from sldgridy.model.geometry import Point
from sldgridy.model.routing import (
    Pin,
    connect,
    cut_wire,
    open_wires,
    pin_at,
    pins_of,
    pole_group,
    route,
    split_wire,
)


def P(x, y):
    return Point(x, y)


def three_pole(name="Q"):
    """Three poles 5 mm apart: 1, 3, 5 on top (pointing up), 2, 4, 6 below."""
    cps = []
    for i, x in enumerate((0, 5, 10)):
        cps.append(ConnectionPoint(id=f"t{i}", name=str(2 * i + 1), position=P(x, 0), direction=90))
        cps.append(
            ConnectionPoint(id=f"b{i}", name=str(2 * i + 2), position=P(x, 15), direction=270)
        )
    return BlockDefinition(name=name, entities=tuple(cps))


def test_split_and_cut_keep_label_on_the_longer_piece():
    wire = Wire(id="w", points=(P(0, 0), P(0, 40), P(30, 40)), label="NYM")
    a, b = split_wire(wire, P(0, 10))
    assert a.points == (P(0, 0), P(0, 10)) and b.points == (P(0, 10), P(0, 40), P(30, 40))
    assert (a.label, b.label) == ("", "NYM") and a.id == "w" and b.id != "w"
    assert split_wire(wire, P(0, 0)) is None and split_wire(wire, P(5, 5)) is None
    a, b = cut_wire(wire, P(0, 25), P(0, 10))
    assert a.points == (P(0, 0), P(0, 10)) and b.points == (P(0, 25), P(0, 40), P(30, 40))


def test_symbol_placed_into_wires_opens_each_pole_but_not_a_rail():
    blocks = {"Q": three_pole()}
    ref = BlockReference(id="q", name="Q", insert=P(0, 20))
    conductors = [Wire(id=f"w{x}", points=(P(x, 0), P(x, 60))) for x in (0, 5, 10)]
    rail = Wire(id="rail", points=(P(-10, 20), P(30, 20)))  # under all top terminals
    pins = [
        ConnectionPoint(id="", name=p.name, position=p.position, direction=p.direction)
        for p in pins_of([ref], blocks)
    ]
    removed, added = open_wires([*conductors, rail], pins)
    assert sorted(removed) == ["w0", "w10", "w5"]
    assert sorted((w.points[0].x, w.points[0].y, w.points[-1].y) for w in added) == [
        (0, 0, 20), (0, 35, 60), (5, 0, 20), (5, 35, 60), (10, 0, 20), (10, 35, 60)
    ]  # fmt: skip


def test_route_between_facing_and_parallel_pins():
    a = Pin("a", "2", P(0, 15), 270)  # pointing down
    b = Pin("b", "1", P(20, 40), 90)  # below, pointing up
    assert route(a, b) == (P(0, 15), P(0, 27.5), P(20, 27.5), P(20, 40))
    straight = Pin("b", "1", P(0, 40), 90)
    assert route(a, straight) == (P(0, 15), P(0, 40))
    side = Pin("b", "1", P(30, 30), 180)  # pointing left
    assert route(a, side) == (P(0, 15), P(0, 30), P(30, 30))
    same_way = Pin("b", "1", P(20, 10), 270)  # also pointing down, higher up
    assert route(a, same_way) == (P(0, 15), P(0, 20), P(20, 20), P(20, 10))


def test_connect_wires_all_poles_without_crossings():
    blocks = {"Q": three_pole("Q"), "K": three_pole("K")}
    refs = [
        BlockReference(id="q", name="Q", insert=P(0, 0)),
        BlockReference(id="k", name="K", insert=P(20, 40)),
    ]
    pins = pins_of(refs, blocks)
    start, end = pin_at(pins, P(0, 15)), pin_at(pins, P(20, 40))
    assert [p.name for p in pole_group(pins, start)] == ["2", "4", "6"]
    paths = connect(pins, start, end)
    assert [(p[0], p[-1]) for p in paths] == [
        (P(0, 15), P(20, 40)), (P(5, 15), P(25, 40)), (P(10, 15), P(30, 40))
    ]  # fmt: skip
    lanes = [p[1].y for p in paths]
    # Wires run to the right: the right pole turns first, so no run crosses another.
    assert lanes[0] > lanes[1] > lanes[2]
    straight = connect(pins, start, pin_at(pins, P(20, 40)))
    assert len(straight) == 3


def test_rail_arrows_point_the_way_the_conductor_flows():
    from sldgridy.model.entities import InterruptionPoint, Line
    from sldgridy.model.interruptions import interruption_geometry

    def head(direction):
        parts = interruption_geometry(
            InterruptionPoint(id="i", name="L1", position=P(100, 50), direction=direction), None
        )
        wings = [e for e in parts if isinstance(e, Line) and "wing" in e.id]
        return wings[0].p1, {(round(w.p2.x - w.p1.x, 3)) for w in wings}

    # Right end: head at the tip beyond the conductor end, wings back to the left.
    tip, dx = head(0)
    assert tip == P(102.5, 50) and dx == {-1.768}
    # Left end (coming from the previous page): head on the conductor end, pointing
    # right as well.
    tip, dx = head(180)
    assert tip == P(100, 50) and dx == {-1.768}


def terminal_block():
    from sldgridy.model.entities import AttributeDefinition, Circle

    return BlockDefinition(
        name="Klemme",
        function="terminal",
        entities=(
            Circle(id="c", center=P(0, 2.5), radius=1.0),
            ConnectionPoint(id="a", name="1", position=P(0, 0), direction=90),
            ConnectionPoint(id="b", name="2", position=P(0, 5), direction=270),
            AttributeDefinition(id="att_bmk", tag="BMK", default="-X1:1", position=P(2.25, 2.5)),
        ),
    )


def terminal(ref_id, bmk, x, y, rotation=0):
    return BlockReference(
        id=ref_id,
        name="Klemme",
        insert=P(x, y),
        rotation=rotation,
        attributes=(("BMK", bmk),),
    )


def test_terminals_on_one_line_are_labelled_as_a_row():
    from sldgridy.model.terminals import row_labels

    blocks = {"Klemme": terminal_block()}
    entities = [
        terminal("c", "-X1:3", 10, 50),
        terminal("a", "-X1:1", 0, 50),
        terminal("b", "-X1:2", 5, 50),
        terminal("far", "-X1:4", 40, 50),  # same line, but further away
        terminal("low", "-X1:5", 0, 80),  # another line
        terminal("x2", "-X2:1", 15, 50),  # another strip
        terminal("turned", "-X1:6", 0, 100, rotation=90),  # in a horizontal wire
    ]
    labels = row_labels(entities, blocks)
    assert labels["a"] == ("-X1", "1")
    assert labels["b"] == ("", "2") and labels["c"] == ("", "3")
    assert labels["far"] == ("-X1", "4")
    assert labels["low"] == ("-X1", "5")
    assert labels["x2"] == ("-X2", "1")
    assert "turned" not in labels


def test_terminal_row_texts_replace_the_bmk(qapp):
    from sldgridy.model.document import DOC_PROJECT, Document
    from sldgridy.model.entities import Text
    from sldgridy.view.display import expand_for_display

    doc = Document.new_project()
    doc.blocks["Klemme"] = terminal_block()
    page = doc.sheets[1]
    first, second = terminal("a", "-X1:1", 50, 50), terminal("b", "-X1:2", 55, 50)
    page.entities.add(first)
    page.entities.add(second)
    assert doc.kind == DOC_PROJECT

    def texts(ref):
        return [
            (e.text, e.halign, e.position.x)
            for e in expand_for_display(doc, ref)
            if isinstance(e, Text)
        ]

    assert texts(first) == [("-X1", "right", 48.4), ("1", "left", 51.6)]
    assert texts(second) == [("2", "left", 56.6)]
