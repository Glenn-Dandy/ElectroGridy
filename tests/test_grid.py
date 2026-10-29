import pytest

from electrogridy.view.grid import grid_lines, visible_grid_step


def test_base_step_kept_when_dense_enough():
    # 5 mm at 3.78 px/mm = 18.9 px
    assert visible_grid_step(5.0, 3.78, 8.0) == 5.0


def test_step_grows_in_1_2_5_sequence():
    # 5 mm at 0.5 px/mm = 2.5 px -> 10 mm = 5 px -> 25 mm = 12.5 px
    assert visible_grid_step(5.0, 0.5, 8.0) == 25.0
    # 5 mm at 0.01 px/mm -> needs 800 mm -> 1000 mm (5 * 2 * 100)
    assert visible_grid_step(5.0, 0.01, 8.0) == 1000.0


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        visible_grid_step(0.0, 1.0, 8.0)


def test_grid_lines_cover_range_inclusive():
    assert grid_lines(-7.0, 12.0, 5.0) == [-5.0, 0.0, 5.0, 10.0]
    assert grid_lines(0.0, 10.0, 5.0) == [0.0, 5.0, 10.0]
