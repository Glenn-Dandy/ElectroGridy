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
