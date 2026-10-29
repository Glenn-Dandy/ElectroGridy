import pytest

from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Arc, Line, Rectangle, Text
from electrogridy.model.geometry import Point


def test_translate_keeps_id():
    line = Line(id="a", p1=Point(0, 0), p2=Point(10, 0))
    moved = line.translated(5, -2)
    assert moved.id == "a"
    assert (moved.p1, moved.p2) == (Point(5, -2), Point(15, -2))


def test_with_new_id_changes_only_id():
    line = Line(id="a", p1=Point(0, 0), p2=Point(10, 0))
    copy = line.with_new_id()
    assert copy.id != "a"
    assert (copy.p1, copy.p2) == (line.p1, line.p2)


def test_rotate_line_quarter_turn():
    line = Line(id="a", p1=Point(0, 0), p2=Point(10, 0))
    r = line.rotated(Point(0, 0), 1)
    assert (r.p1, r.p2) == (Point(0, 0), Point(0, -10))


def test_rotate_rectangle_stays_axis_aligned():
    rect = Rectangle(id="r", p1=Point(0, 0), p2=Point(20, 10))
    r = rect.rotated(Point(0, 0), 1)
    assert (r.p1, r.p2) == (Point(0, 0), Point(10, -20))


def test_rotate_arc_shifts_angles():
    arc = Arc(id="a", center=Point(5, 5), radius=3, start_angle=300, end_angle=30)
    r = arc.rotated(Point(0, 0), 1)
    assert r.center == Point(5, -5)
    assert (r.start_angle, r.end_angle) == (30, 120)
    assert arc.sweep == 90


def test_full_arc_sweep_is_360():
    assert Arc(id="a", center=Point(0, 0), radius=1, start_angle=10, end_angle=10).sweep == 360


def test_rotate_text_accumulates_rotation():
    t = Text(id="t", position=Point(1, 0), text="X", rotation=270)
    r = t.rotated(Point(0, 0), 3)
    assert r.rotation == 180
    assert r.position == Point(0, 1)


def test_container_add_remove_replace_notifies():
    events = []
    c = EntityContainer()
    c.subscribe(lambda ev, e: events.append((ev, e.id)))
    a = Line(id="a", p1=Point(0, 0), p2=Point(1, 0))
    b = Line(id="b", p1=Point(0, 0), p2=Point(2, 0))
    c.add(a)
    c.add(b, 0)
    assert [e.id for e in c] == ["b", "a"]
    c.replace(a.translated(1, 1))
    assert c.get("a").p1 == Point(1, 1)
    assert c.remove("b") == (0, b)
    assert events == [("added", "a"), ("added", "b"), ("changed", "a"), ("removed", "b")]


def test_container_rejects_duplicate_ids():
    c = EntityContainer([Line(id="a", p1=Point(0, 0), p2=Point(1, 0))])
    with pytest.raises(ValueError):
        c.add(Line(id="a", p1=Point(0, 0), p2=Point(1, 0)))
