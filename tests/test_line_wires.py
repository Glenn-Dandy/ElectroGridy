from electrogridy.model.entities import JunctionMark, Line, Polyline, Wire
from electrogridy.model.geometry import Point
from electrogridy.model.line_wires import lines_to_wires
from electrogridy.model.wires import tees


def line(lid, a, b, **kw):
    return Line(id=lid, p1=Point(*a), p2=Point(*b), **kw)


def test_pieces_meeting_end_to_end_become_one_wire():
    lines = [
        line("a", (0, 50), (0, 20), color="#ff0000"),
        line("b", (0, 20), (30, 20)),
        line("c", (30, 20), (60, 20)),  # straight on: the point goes
    ]
    conv = lines_to_wires(lines, [])
    assert sorted(conv.removed) == ["a", "b", "c"]
    (wire,) = conv.added
    assert isinstance(wire, Wire) and wire.color == "#ff0000"
    assert wire.points in (
        (Point(0, 50), Point(0, 20), Point(60, 20)),
        (Point(60, 20), Point(0, 20), Point(0, 50)),
    )


def test_imported_tee_diagonal_connects_the_branch_and_goes():
    """The branch stops 1.25 mm short of the rail, a diagonal joins it: after the
    conversion the branch ends on the rail and the project draws the T itself."""
    lines = [
        line("rail", (0, 10), (100, 10)),
        line("down", (40, 11.25), (40, 40)),
        line("diag", (40, 11.25), (41.25, 10)),  # towards the right
        line("down2", (70, 11.25), (70, 40)),
        line("diag2", (68.75, 10), (70, 11.25)),  # towards the left, drawn the other way
    ]
    conv = lines_to_wires(lines, [])
    assert conv.tees == 2 and conv.wires == 3
    wires = [e for e in conv.added if isinstance(e, Wire)]
    assert not [e for e in conv.added if isinstance(e, Line)]
    tops = [min(w.points, key=lambda p: p.y) for w in wires if w.points[0].x == w.points[-1].x]
    assert sorted((p.x, p.y) for p in tops) == [(40, 10), (70, 10)]
    (mark,) = [e for e in conv.added if isinstance(e, JunctionMark)]
    assert mark.position == Point(70, 10) and mark.side == -1
    found = {t.position: t.side for t in tees(conv.added)[1]}
    assert found == {Point(40, 10): (1.0, 0.0), Point(70, 10): (-1.0, 0.0)}


def test_branch_onto_an_existing_wire_and_slanted_lines_stay():
    rail = Wire(id="rail", points=(Point(0, 10), Point(100, 10)))
    lines = [
        line("down", (40, 11.25), (40, 40)),
        line("diag", (40, 11.25), (41.25, 10)),
        line("slant", (0, 0), (30, 20)),  # a drawn slanted line, no T
        Polyline(id="box", points=(Point(0, 0), Point(5, 0), Point(5, 5)), closed=True),
    ]
    conv = lines_to_wires(lines, [rail])
    assert "box" not in conv.removed
    (wire,) = [e for e in conv.added if isinstance(e, Wire)]
    assert Point(40, 10) in wire.points
    (kept,) = [e for e in conv.added if isinstance(e, Line)]
    assert (kept.p1, kept.p2) == (Point(0, 0), Point(30, 20))
