import pytest

from electrogridy.model.entities import Arc, Circle, Line, Polyline, Rectangle
from electrogridy.model.geometry import Point
from electrogridy.model.primitives import ArcPrim, Segment, intersect
from electrogridy.model.snap import SnapHit, SnapMode, find_snap


def approx_point(p: Point, x: float, y: float) -> bool:
    return p.x == pytest.approx(x, abs=1e-9) and p.y == pytest.approx(y, abs=1e-9)


def test_segment_segment_intersection():
    (p,) = intersect(Segment(Point(0, 0), Point(10, 10)), Segment(Point(0, 10), Point(10, 0)))
    assert approx_point(p, 5, 5)
    assert intersect(Segment(Point(0, 0), Point(1, 0)), Segment(Point(0, 1), Point(1, 1))) == []
    assert intersect(Segment(Point(0, 0), Point(1, 0)), Segment(Point(5, -1), Point(5, 1))) == []


def test_segment_circle_intersection():
    pts = intersect(Segment(Point(-10, 0), Point(10, 0)), ArcPrim(Point(0, 0), 5, 0, 360))
    assert sorted((round(p.x, 9), round(p.y, 9)) for p in pts) == [(-5, 0), (5, 0)]


def test_segment_arc_respects_arc_range():
    # Upper half arc (0..180 degrees, y negative on screen).
    arc = ArcPrim(Point(0, 0), 5, 0, 180)
    pts = intersect(Segment(Point(0, -10), Point(0, 10)), arc)
    assert len(pts) == 1 and approx_point(pts[0], 0, -5)


def test_circle_circle_intersection():
    pts = intersect(ArcPrim(Point(0, 0), 5, 0, 360), ArcPrim(Point(8, 0), 5, 0, 360))
    assert sorted((round(p.x, 9), round(p.y, 9)) for p in pts) == [(4, -3), (4, 3)]


def test_endpoint_snap_picks_nearest():
    lines = [Line(id="a", p1=Point(0, 0), p2=Point(10, 0))]
    hit = find_snap(Point(9.2, 0.5), lines, aperture=2)
    assert hit == SnapHit(Point(10, 0), SnapMode.ENDPOINT)


def test_midpoint_and_center():
    rect = Rectangle(id="r", p1=Point(0, 0), p2=Point(20, 10))
    hit = find_snap(Point(10.3, 0.2), [rect], aperture=2)
    assert hit == SnapHit(Point(10, 0), SnapMode.MIDPOINT)
    circle = Circle(id="c", center=Point(50, 50), radius=1)
    assert find_snap(Point(50.4, 50), [circle], aperture=2).mode is SnapMode.CENTER


def test_arc_endpoints_and_midpoint():
    arc = Arc(id="a", center=Point(0, 0), radius=10, start_angle=0, end_angle=90)
    assert find_snap(Point(0.3, -9.8), [arc], aperture=1) == SnapHit(
        Point(pytest.approx(0, abs=1e-9), -10), SnapMode.ENDPOINT
    )
    hit = find_snap(Point(7, -7), [arc], aperture=1)
    assert hit.mode is SnapMode.MIDPOINT


def test_intersection_between_entities():
    a = Line(id="a", p1=Point(0, 5), p2=Point(20, 5))
    b = Polyline(id="b", points=(Point(10, 0), Point(10, 20)))
    hit = find_snap(Point(10.4, 5.3), [a, b], aperture=1)
    assert hit.mode is SnapMode.INTERSECTION and approx_point(hit.point, 10, 5)


def test_modes_can_be_disabled():
    lines = [Line(id="a", p1=Point(0, 0), p2=Point(10, 0))]
    assert find_snap(Point(10, 0.1), lines, 1, frozenset({SnapMode.MIDPOINT})) is None


def test_connection_points_have_priority():
    line = Line(id="a", p1=Point(0, 0), p2=Point(10, 0))

    def extra(_e):
        return [SnapHit(Point(10.8, 0), SnapMode.CONNECTION)]

    hit = find_snap(Point(10.1, 0), [line], aperture=2, extra=extra)
    assert hit.mode is SnapMode.CONNECTION


def test_nearest_on_a_sloped_line_and_a_circle():
    line = Line(id="l", p1=Point(0, 0), p2=Point(40, -30))
    hit = find_snap(Point(29, -20), [line], aperture=3, grid=2.5)
    assert hit.mode is SnapMode.NEAREST
    # Exactly on the line, the foot of the cursor (not a grid point beside it).
    assert hit.point.x * -30 == pytest.approx(hit.point.y * 40)
    assert hit.point.x == pytest.approx(28.16)
    circle = Circle(id="c", center=Point(0, 0), radius=10)
    hit = find_snap(Point(7.5, 7.5), [circle], aperture=3)
    assert hit.mode is SnapMode.NEAREST
    assert (hit.point.x**2 + hit.point.y**2) == pytest.approx(100)


def test_characteristic_points_beat_nearest():
    line = Line(id="l", p1=Point(0, 0), p2=Point(40, -30))
    hit = find_snap(Point(1, -1.5), [line], aperture=3)
    assert hit.mode is SnapMode.ENDPOINT


def test_detailed_symbol_does_not_hang_the_snap():
    # A device drawing as one symbol: thousands of short edges close together. All
    # pairs were tested for intersections on every mouse move (2026-10-25, hang).
    import time

    from electrogridy.model.blocks import BlockDefinition, expand
    from electrogridy.model.container import EntityContainer
    from electrogridy.model.entities import BlockReference, Line

    lines = [
        Line(id=f"l{i}", p1=Point(i % 60, i // 60), p2=Point(i % 60 + 0.7, i // 60 + 0.9))
        for i in range(3000)
    ]
    blocks = {"Gerät": BlockDefinition(name="Gerät", entities=EntityContainer(lines))}
    ref = BlockReference(id="r", name="Gerät", insert=Point(0, 0))
    start = time.perf_counter()
    for aperture in (1.0, 10.0, 100.0):
        hit = find_snap(Point(30.1, 20.1), [ref], aperture, decompose=lambda e: expand(e, blocks))
        assert hit is not None
    assert time.perf_counter() - start < 2.0
