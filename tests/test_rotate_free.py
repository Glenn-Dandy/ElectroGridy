import math

import pytest

from electrogridy.model.entities import BlockReference, Line, Polyline, Rectangle, Text, Wire
from electrogridy.model.geometry import Point
from electrogridy.model.rotate import quarter_turns, rotate_entity, rotate_point
from electrogridy.model.snap import circle_hits


def test_rotate_point_counter_clockwise_with_y_down():
    p = rotate_point(Point(10, 0), Point(0, 0), 90)
    assert p.x == pytest.approx(0) and p.y == pytest.approx(-10)  # up on screen
    p = rotate_point(Point(10, 0), Point(0, 0), 30)
    assert p.x == pytest.approx(10 * math.cos(math.radians(30)))
    assert p.y == pytest.approx(-5)


def test_free_angles_per_entity_kind():
    line = Line(id="l", p1=Point(0, 0), p2=Point(10, 0))
    turned = rotate_entity(line, Point(0, 0), 45)
    assert turned.p2.x == pytest.approx(turned.p2.x) and turned.p2.y < 0
    rect = Rectangle(id="r", p1=Point(0, 0), p2=Point(20, 10), lineweight=0.5)
    poly = rotate_entity(rect, Point(0, 0), 30)
    assert isinstance(poly, Polyline) and poly.closed and len(poly.points) == 4
    assert poly.id == "r" and poly.lineweight == 0.5
    text = rotate_entity(Text(id="t", position=Point(0, 0), text="A"), Point(0, 0), 12.5)
    assert text.rotation == pytest.approx(12.5)
    ref = BlockReference(id="b", name="X", insert=Point(0, 0))
    assert rotate_entity(ref, Point(0, 0), 30) is None  # blocks only in quarter steps
    assert rotate_entity(ref, Point(0, 0), 90).rotation == 90
    wire = Wire(id="w", points=(Point(0, 0), Point(10, 0)))
    assert rotate_entity(wire, Point(0, 0), 45) is None
    assert quarter_turns(180) == 2 and quarter_turns(30) is None


def test_circle_of_a_fixed_length_crosses_edges():
    edge = Line(id="e", p1=Point(-100, -30), p2=Point(100, -30))
    hits = circle_hits(Point(0, 0), 50, [edge])
    assert sorted(round(h.x) for h in hits) == [-40, 40]
    assert all(h.y == pytest.approx(-30) for h in hits)
