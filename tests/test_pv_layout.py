import pytest

from electrogridy.model.geometry import Point
from electrogridy.model.pv_layout import (
    LayoutParams,
    contains,
    layout_modules,
    polygon_area,
    rect_corners,
    take_modules,
)

MODULE = (1134.0, 1762.0)  # width × height, portrait


def rect(x, y, w, h):
    return rect_corners(x, y, w, h)


def test_polygon_helpers():
    square = rect(0, 0, 10, 10)
    assert polygon_area(square) == pytest.approx(100)
    assert contains(square, Point(5, 5)) and contains(square, Point(0, 5))
    assert not contains(square, Point(11, 5))


def test_rectangular_roof_fills_rows_and_columns():
    # 8 m × 5 m roof, 300 mm edge, 20 mm gaps:
    # width: 7400 usable → 6 modules (6×1134 + 5×20 = 6904); height: 4400 → 2 rows.
    roof = rect(0, 0, 8000, 5000)
    modules = layout_modules(roof, [], LayoutParams(*MODULE))
    assert len(modules) == 12
    xs = sorted({p.x for p in modules})
    assert all(b - a == pytest.approx(1154) for a, b in zip(xs, xs[1:], strict=False))
    # Centred: equal space left and right.
    left = min(xs)
    right = 8000 - (max(xs) + MODULE[0])
    assert left == pytest.approx(right, abs=150)


def test_landscape_orientation_uses_turned_size():
    roof = rect(0, 0, 8000, 5000)
    params = LayoutParams(width=MODULE[1], height=MODULE[0])
    modules = layout_modules(roof, [], params)
    # 7400 / 1782 → 4 per row; 4400 / 1154 → 3 rows.
    assert len(modules) == 12


def test_trapezoid_roof_keeps_the_edge_distance():
    # Wider at the eaves (bottom) than at the ridge (top).
    roof = [Point(2000, 0), Point(6000, 0), Point(8000, 5000), Point(0, 5000)]
    params = LayoutParams(*MODULE)
    modules = layout_modules(roof, [], params)
    assert 0 < len(modules) < 12
    for p in modules:
        for corner in rect(p.x, p.y, *MODULE):
            assert contains(roof, corner)


def test_obstacle_keeps_its_distance():
    roof = rect(0, 0, 8000, 5000)
    chimney = rect(3800, 1800, 600, 600)
    params = LayoutParams(*MODULE)
    free = layout_modules(roof, [], params)
    blocked = layout_modules(roof, [chimney], params)
    assert len(blocked) < len(free)
    for p in blocked:
        x0, y0, x1, y1 = p.x, p.y, p.x + MODULE[0], p.y + MODULE[1]
        overlap_x = x0 < 4400 + 200 and x1 > 3800 - 200
        overlap_y = y0 < 2400 + 200 and y1 > 1800 - 200
        assert not (overlap_x and overlap_y)


def test_roof_too_small_gives_nothing():
    assert layout_modules(rect(0, 0, 1000, 1000), [], LayoutParams(*MODULE)) == []


def test_take_a_number_of_modules_rows_from_the_top():
    # 3 rows of 6 on a 8 m × 7 m roof.
    roof = rect(0, 0, 8000, 7000)
    modules = layout_modules(roof, [], LayoutParams(*MODULE))
    assert len(modules) == 18
    assert take_modules(modules, 0) == modules and len(take_modules(modules, 99)) == 18
    ten = take_modules(modules, 10)
    assert len(ten) == 10
    ys = sorted({p.y for p in modules})
    top = [p for p in ten if p.y == ys[0]]
    second = sorted((p for p in ten if p.y == ys[1]), key=lambda p: p.x)
    assert len(top) == 6 and len(second) == 4 and not [p for p in ten if p.y == ys[2]]
    # The partial row sits in the middle of its row.
    row = sorted((p for p in modules if p.y == ys[1]), key=lambda p: p.x)
    assert second == row[1:5]


def test_big_field_is_fast():
    import time

    # About 1200 modules: used to take over two minutes and froze the program.
    roof = rect(0, 0, 62000, 42000)
    start = time.perf_counter()
    modules = layout_modules(roof, [rect(20000, 20000, 800, 800)], LayoutParams(*MODULE))
    assert len(modules) > 1150
    assert time.perf_counter() - start < 15  # a few seconds even on slow CI machines
