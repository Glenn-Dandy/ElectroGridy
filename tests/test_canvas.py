import pytest
from PyQt6.QtCore import QPointF, QRectF

from electrogridy.view.canvas import MAX_ZOOM, MIN_ZOOM, Canvas


@pytest.fixture
def canvas(qapp):
    c = Canvas()
    c.resize(800, 600)
    c.show()
    qapp.processEvents()
    yield c
    c.close()


def test_initial_zoom_is_physical_size(canvas):
    assert canvas.zoom() == pytest.approx(1.0)
    assert canvas.transform().m11() == pytest.approx(canvas.px_per_mm())


def test_zoom_keeps_point_under_cursor(canvas):
    view_pos = QPointF(200.0, 150.0)
    before = canvas.map_to_scene_f(view_pos)
    canvas.zoom_at(2.5, view_pos)
    after = canvas.map_to_scene_f(view_pos)
    tolerance_mm = 1.0 / canvas.transform().m11()  # one pixel
    assert after.x() == pytest.approx(before.x(), abs=tolerance_mm)
    assert after.y() == pytest.approx(before.y(), abs=tolerance_mm)
    assert canvas.zoom() == pytest.approx(2.5)


def test_zoom_is_clamped(canvas):
    canvas.zoom_at(1e9, QPointF(10, 10))
    assert canvas.zoom() == pytest.approx(MAX_ZOOM)
    canvas.zoom_at(1e-12, QPointF(10, 10))
    assert canvas.zoom() == pytest.approx(MIN_ZOOM)


def test_zoom_emits_signal(canvas):
    seen = []
    canvas.zoom_changed.connect(seen.append)
    canvas.zoom_at(2.0, QPointF(0, 0))
    assert seen == [pytest.approx(2.0)]


def test_fit_rect_shows_whole_a0_sheet(canvas):
    sheet = QRectF(0, 0, 1189, 841)
    canvas.fit_rect(sheet)
    top_left = canvas.map_from_scene_f(sheet.topLeft())
    bottom_right = canvas.map_from_scene_f(sheet.bottomRight())
    vp = canvas.viewport().rect()
    assert top_left.x() >= -1 and top_left.y() >= -1
    assert bottom_right.x() <= vp.width() + 1 and bottom_right.y() <= vp.height() + 1
    center = canvas.map_to_scene_f(QPointF(vp.width() / 2, vp.height() / 2))
    assert center.x() == pytest.approx(594.5, abs=2)
    assert center.y() == pytest.approx(420.5, abs=2)


def test_y_axis_points_down(canvas):
    upper = canvas.map_to_scene_f(QPointF(100, 100))
    lower = canvas.map_to_scene_f(QPointF(100, 300))
    assert lower.y() > upper.y()


def test_grid_spacing_must_be_positive(canvas):
    with pytest.raises(ValueError):
        canvas.set_grid_spacing(0)


def test_render_does_not_fail(canvas):
    canvas.zoom_extents()
    image = canvas.grab()
    assert not image.isNull()
