import pytest

from electrogridy.model.paper import PAPER_FORMATS, Orientation, sheet_size


def test_a0_landscape_is_1189_by_841():
    assert sheet_size("A0", Orientation.LANDSCAPE) == (1189.0, 841.0)


def test_a4_portrait_is_210_by_297():
    assert sheet_size("A4", Orientation.PORTRAIT) == (210.0, 297.0)


@pytest.mark.parametrize("paper", sorted(PAPER_FORMATS))
def test_orientation_swaps_sides(paper):
    w, h = sheet_size(paper, Orientation.PORTRAIT)
    assert sheet_size(paper, Orientation.LANDSCAPE) == (h, w)
    assert w < h


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        sheet_size("B5", Orientation.PORTRAIT)
