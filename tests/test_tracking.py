import pytest
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt
from PyQt6.QtTest import QTest

from electrogridy.model.entities import Line
from electrogridy.model.geometry import Point
from electrogridy.model.tracking import MAX_ACQUIRED, toggle_acquired, track
from electrogridy.ui.main_window import MainWindow
from waiting import wait_until

P = Point(10, 20)


def test_vertical_alignment_keeps_grid_along_line():
    r = track(Point(10.4, 51.3), [P], tolerance=1, grid=2.5)
    assert r.point == Point(10, 52.5)
    assert [(line.origin, line.vertical) for line in r.lines] == [(P, True)]


def test_horizontal_alignment_without_grid():
    r = track(Point(33.3, 19.6), [P], tolerance=1)
    assert r.point == Point(33.3, 20) and not r.lines[0].vertical


def test_intersection_of_two_tracks():
    a, b = Point(10, 0), Point(0, 30)
    r = track(Point(10.3, 29.8), [a, b], tolerance=1, grid=2.5)
    assert r.point == Point(10, 30) and len(r.lines) == 2


def test_with_ortho_meets_the_track():
    base = Point(0, 50)
    r = track(Point(9.7, 50.8), [P], tolerance=1, ortho_base=base)
    assert r.point == Point(10, 50)
    assert track(Point(30, 50.5), [P], tolerance=1, ortho_base=base) is None


def test_far_from_any_alignment():
    assert track(Point(40, 40), [P], tolerance=1) is None
    assert track(Point(40, 40), [], tolerance=1) is None


def test_toggle_acquired():
    pts = []
    for i in range(MAX_ACQUIRED + 1):
        pts = toggle_acquired(pts, Point(i, i))
    assert len(pts) == MAX_ACQUIRED and pts[0] == Point(MAX_ACQUIRED, MAX_ACQUIRED)
    assert toggle_acquired(pts, pts[1]) == [pts[0], pts[2]]


@pytest.fixture
def window(qapp):
    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    w.canvas.fit_rect(QRectF(0, 0, 100, 100))
    yield w
    w.undo_stack.setClean()
    w.close()


def vp(window, x, y):
    return window.canvas.map_from_scene_f(QPointF(x, y)).toPoint()


def test_hover_acquires_point_and_line_follows_track(window):
    window.document.model_space.add(Line(id="a", p1=Point(20, 20), p2=Point(20, 40)))
    window.act_line.trigger()
    viewport = window.canvas.viewport()
    QTest.mouseMove(viewport, vp(window, 20.3, 40.2))  # rest on the end point
    assert wait_until(lambda: window.canvas.acquired == [Point(20, 40)])
    # Start a line somewhere else, then move along the vertical track of (20, 40).
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 50, 70))
    QTest.mouseMove(viewport, vp(window, 20.6, 71.1))
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 20.6, 71.1))
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    new = [e for e in window.document.model_space if e.id != "a"][0]
    assert new.p2 == Point(20, 70)
    assert window.canvas.acquired == []  # cleared when the command ends


def test_tracking_can_be_switched_off(window):
    window.canvas.acquired = [Point(20, 40)]
    window.act_otrack.setChecked(False)
    assert window.canvas.acquired == []
    assert window.canvas.constrain(QPointF(20.6, 71.1)) == QPointF(20, 70)  # grid only


def test_no_tracking_point_without_command(window):
    window.document.model_space.add(Line(id="a", p1=Point(20, 20), p2=Point(20, 40)))
    viewport = window.canvas.viewport()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 20, 30))  # select
    QTest.mouseMove(viewport, vp(window, 20.3, 40.2))  # rest on the end point / grip
    QTest.qWait(500)
    assert window.canvas.acquired == []
    # Dragging the grip: the end point moves freely, without a tracking point.
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 20, 40))
    assert window.tools.active is not None
    QTest.qWait(500)
    assert window.canvas.acquired == []
    window.tools.cancel()


def test_text_reference_point_snaps_and_tracks(window):
    """Texts take part in the tracking at their reference point (Florian 2026-10-28)."""
    from electrogridy.model.entities import Text
    from electrogridy.model.snap import SnapMode, find_snap

    text = Text(id="t", position=Point(30, 20), text="-X1", height=2.5)
    hit = find_snap(Point(30.3, 20.2), [text], 1.0)
    assert hit is not None and (hit.point, hit.mode) == (Point(30, 20), SnapMode.INSERTION)
    assert find_snap(Point(30.3, 20.2), [text], 1.0, frozenset({SnapMode.ENDPOINT})) is None

    window.document.model_space.add(text)
    window.act_line.trigger()
    viewport = window.canvas.viewport()
    QTest.mouseMove(viewport, vp(window, 30.2, 20.2))  # rest on the text's point
    assert wait_until(lambda: window.canvas.acquired == [Point(30, 20)])
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 60, 60))
    QTest.mouseMove(viewport, vp(window, 30.6, 61.1))
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 30.6, 61.1))
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    new = [e for e in window.document.model_space if isinstance(e, Line)][0]
    assert new.p2.x == 30  # straight below the text's reference point
