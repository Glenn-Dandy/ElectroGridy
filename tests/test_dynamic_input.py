import pytest

from electrogridy.model.geometry import Point
from electrogridy.tools.dynamic_input import (
    POLAR,
    SIZE,
    XY,
    DynamicInput,
    angle_of,
    format_number,
    parse_number,
)


def test_numbers_with_decimal_comma_or_point():
    assert parse_number("12,5") == 12.5
    assert parse_number("12.5") == 12.5
    assert parse_number("-") is None and parse_number("") is None
    assert format_number(1250.0) == "1250"
    assert format_number(12.345) == "12,35"
    assert format_number(12.5, decimal_comma=False) == "12.5"


def test_angles_count_counter_clockwise_with_y_down():
    a = Point(0, 0)
    assert angle_of(a, Point(10, 0)) == pytest.approx(0)
    assert angle_of(a, Point(0, -10)) == pytest.approx(90)  # up on screen
    assert angle_of(a, Point(-10, 0)) == pytest.approx(180)


def test_typed_length_keeps_mouse_direction():
    d = DynamicInput(POLAR)
    for c in "1250":
        d.type(c)
    p = d.constrain(Point(0, 0), Point(30, 40))  # mouse direction 3:4
    assert p.x == pytest.approx(750) and p.y == pytest.approx(1000)
    shown = d.shown(Point(0, 0), p, decimal_comma=True)
    assert shown["length"] == "1250"


def test_tab_then_angle_fixes_the_point():
    d = DynamicInput(POLAR)
    d.type("1")
    d.type("0")
    d.next_field()
    assert d.active_name == "angle"
    d.type("9")
    d.type("0")
    p = d.constrain(Point(5, 5), Point(100, 100))  # mouse no longer matters
    assert p.x == pytest.approx(5) and p.y == pytest.approx(-5)


def test_angle_only_projects_mouse_on_the_ray():
    d = DynamicInput(POLAR)
    d.next_field()
    d.type("0")
    p = d.constrain(Point(0, 0), Point(30, 25))
    assert p == Point(30, 0)


def test_rectangle_size_follows_mouse_side():
    d = DynamicInput(SIZE)
    d.type("4")
    d.type("0")
    d.next_field()
    d.type("2")
    d.type("0")
    assert d.constrain(Point(0, 0), Point(-5, -5)) == Point(-40, -20)


def test_xy_before_first_point_and_editing():
    d = DynamicInput(XY)
    d.type("1")
    d.type("2")
    d.backspace()
    d.next_field()
    d.type("7")
    assert d.constrain(None, Point(50, 60)) == Point(1, 7)
    assert not d.type("@")  # not part of a number: left to the command line
    d.set_mode(POLAR)
    assert not d.has_input() and d.active == 0
