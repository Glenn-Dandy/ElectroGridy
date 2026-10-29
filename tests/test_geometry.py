import pytest

from electrogridy.model.geometry import (
    Point,
    angle_deg,
    distance,
    ortho,
    point_at_angle,
    quarters_towards,
    rotate_quarter,
    snap_to_grid,
)


def test_distance():
    assert distance(Point(0, 0), Point(3, 4)) == 5


@pytest.mark.parametrize(
    ("quarters", "expected"),
    [(0, Point(11, 5)), (1, Point(10, 4)), (2, Point(9, 5)), (3, Point(10, 6)), (5, Point(10, 4))],
)
def test_rotate_quarter_counter_clockwise_on_screen(quarters, expected):
    # Point right of the center goes up (smaller y) on the first quarter turn.
    assert rotate_quarter(Point(11, 5), Point(10, 5), quarters) == expected


def test_angle_deg_screen_orientation():
    c = Point(0, 0)
    assert angle_deg(c, Point(1, 0)) == 0
    assert angle_deg(c, Point(0, -1)) == 90  # up on screen
    assert angle_deg(c, Point(-1, 0)) == 180
    assert angle_deg(c, Point(0, 1)) == 270


def test_point_at_angle_inverse_of_angle_deg():
    p = point_at_angle(Point(2, 3), 4, 90)
    assert p.x == pytest.approx(2)
    assert p.y == pytest.approx(-1)


def test_snap_to_grid():
    assert snap_to_grid(Point(3.7, -1.3), 2.5) == Point(2.5, -2.5)
    assert snap_to_grid(Point(1.2, 1.3), 2.5) == Point(0.0, 2.5)
    # Midpoints round consistently upwards.
    assert snap_to_grid(Point(1.25, 3.75), 2.5) == Point(2.5, 5.0)
    with pytest.raises(ValueError):
        snap_to_grid(Point(0, 0), 0)


def test_ortho_picks_dominant_axis():
    base = Point(10, 10)
    assert ortho(base, Point(20, 13)) == Point(20, 10)
    assert ortho(base, Point(12, -5)) == Point(10, -5)


def test_quarters_towards():
    c = Point(0, 0)
    assert quarters_towards(c, Point(10, 1)) == 0
    assert quarters_towards(c, Point(1, -10)) == 1
    assert quarters_towards(c, Point(-10, 2)) == 2
    assert quarters_towards(c, Point(0, 10)) == 3
