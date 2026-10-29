import pytest
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt
from PyQt6.QtTest import QTest

from electrogridy.fileio.json_format import entity_from_dict, entity_to_dict
from electrogridy.model.entities import Busbar, JunctionMark, Line, Polyline, Wire
from electrogridy.model.geometry import Point
from electrogridy.model.snap import SnapMode, find_snap
from electrogridy.model.wires import junction_points, remove_vertex
from electrogridy.ui.main_window import MainWindow
from electrogridy.ui.point_menu import point_actions
from waiting import wait_until

BAR = Busbar(id="bar", p1=Point(0, 50), p2=Point(100, 50))


def W(id_, *pts):
    return Wire(id=id_, points=tuple(Point(*p) for p in pts))


# -- model ------------------------------------------------------------------


def test_perpendicular_foot_beats_free_bus_bar_point():
    hit = find_snap(Point(12.7, 50.5), [BAR], aperture=4, base=Point(10, 0), grid=2.5)
    assert hit.mode is SnapMode.PERPENDICULAR and hit.point == Point(10, 50)
    # Far from the foot the free point on the bar (on the grid) is offered.
    hit = find_snap(Point(31.1, 50.5), [BAR], aperture=4, base=Point(10, 0), grid=2.5)
    assert hit.mode is SnapMode.BUSBAR and hit.point == Point(30, 50)


def test_perpendicular_onto_wire_and_needs_base():
    wire = W("w", (0, 20), (50, 20))  # midpoint at 25, away from the foot at 30
    hit = find_snap(Point(30.4, 21), [wire], aperture=2, base=Point(30, 0))
    assert hit.mode is SnapMode.PERPENDICULAR and hit.point == Point(30, 20)
    without_nearest = frozenset(m for m in SnapMode if m is not SnapMode.NEAREST)
    assert find_snap(Point(30.4, 21), [wire], aperture=2, modes=without_nearest) is None
    # Nearest: on the wire, the free coordinate on the grid.
    hit = find_snap(Point(30.4, 21), [wire], aperture=2, grid=2.5)
    assert hit.mode is SnapMode.NEAREST and hit.point == Point(30, 20)


def test_connection_points_still_win():
    from electrogridy.model.snap import SnapHit

    hit = find_snap(
        Point(10.5, 50.5),
        [BAR],
        aperture=4,
        base=Point(10, 0),
        extra=lambda e: [SnapHit(Point(11, 50), SnapMode.CONNECTION)],
    )
    assert hit.mode is SnapMode.CONNECTION


def test_wire_on_bus_bar_gets_a_dot():
    assert junction_points([BAR, W("w", (20, 0), (20, 50))]) == [Point(20, 50)]


def test_marks_force_and_suppress_dots():
    a, b = W("a", (0, 0), (20, 0)), W("b", (10, -10), (10, 10))  # plain crossing
    assert junction_points([a, b]) == []
    force = JunctionMark(id="m", position=Point(10, 0), connected=True)
    assert junction_points([a, b, force]) == [Point(10, 0)]
    t = W("t", (10, 0), (10, 10))  # T junction
    suppress = JunctionMark(id="s", position=Point(10, 0), connected=False)
    assert junction_points([a, t]) == [Point(10, 0)]
    assert junction_points([a, t, suppress]) == []


def test_junction_mark_roundtrip():
    m = JunctionMark(id="m", position=Point(1, 2), connected=False)
    assert entity_from_dict(entity_to_dict(m)) == m


def test_remove_corner_keeps_wire_orthogonal():
    w = W("w", (0, 0), (10, 0), (10, 10), (20, 10))
    new = remove_vertex(w, 1)
    pts = new.points
    assert pts[0] == Point(0, 0) and pts[-1] == Point(20, 10)
    assert all(p.x == q.x or p.y == q.y for p, q in zip(pts, pts[1:], strict=False))
    assert Point(10, 0) not in pts
    assert remove_vertex(W("s", (0, 0), (5, 0)), 1) is None
    assert remove_vertex(w, 3).points[-1] == Point(10, 10)


# -- user interface ---------------------------------------------------------


@pytest.fixture
def window(qapp):
    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    w.canvas.fit_rect(QRectF(-10, -10, 120, 80))
    yield w
    w.undo_stack.setClean()
    w.close()


def vp(window, x, y):
    return window.canvas.map_from_scene_f(QPointF(x, y)).toPoint()


def click(window, x, y, button=Qt.MouseButton.LeftButton):
    QTest.mouseMove(window.canvas.viewport(), vp(window, x, y))
    QTest.mouseClick(window.canvas.viewport(), button, pos=vp(window, x, y))


def wires(window):
    return [e for e in window.document.model_space if isinstance(e, Wire)]


def test_wire_meets_bus_bar_at_right_angle(window):
    window.document.model_space.add(BAR)
    window.act_wire.trigger()
    click(window, 10, 0)
    click(window, 12.2, 50.6)  # near, but not exactly above the start point
    window.tools.finish()
    (wire,) = wires(window)
    assert wire.points == (Point(10, 0), Point(10, 50))
    assert Point(10, 50) in junction_points(window.document.model_space)


def test_clicked_point_is_not_a_tracking_source(window):
    window.document.model_space.add(Line(id="l", p1=Point(20, 10), p2=Point(20, 30)))
    window.act_line.trigger()
    QTest.mouseMove(window.canvas.viewport(), vp(window, 20.3, 30.2))
    assert wait_until(lambda: window.canvas.acquired == [Point(20, 30)])
    QTest.mouseClick(
        window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=vp(window, 20.3, 30.2)
    )
    assert window.canvas.acquired == []
    QTest.qWait(500)
    assert window.canvas.acquired == []  # resting on the clicked point does not re-acquire
    # Free movement: no tracking pull towards x = 20 from the start point.
    window.act_osnap.setChecked(False)
    assert window.canvas.constrain(QPointF(21.3, 51.1)) == QPointF(22.5, 50)
    window.tools.cancel()


def action(window, p, text):
    for label, callback in point_actions(window, p):
        if text in label:
            return callback
    raise AssertionError([label for label, _ in point_actions(window, p)])


def test_point_menu_separate_and_connect(window):
    ms = window.document.model_space
    ms.add(W("a", (0, 0), (40, 0)))
    ms.add(W("t", (20, 0), (20, 20)))
    action(window, Point(20, 0), "Trennen")()
    assert junction_points(ms) == []
    action(window, Point(20, 0), "Trennung aufheben")()
    assert junction_points(ms) == [Point(20, 0)]
    ms.add(W("c", (30, -10), (30, 10)))  # crossing without dot
    action(window, Point(30, 0), "Verbinden")()
    assert Point(30, 0) in junction_points(ms)
    window.act_undo.trigger()
    assert Point(30, 0) not in junction_points(ms)


def test_point_menu_remove_point_and_extend(window):
    ms = window.document.model_space
    ms.add(W("w", (0, 0), (10, 0), (10, 10)))
    ms.add(Polyline(id="p", points=(Point(50, 0), Point(60, 0), Point(60, 10))))
    action(window, Point(10, 0), "Punkt entfernen (Leitung)")()
    assert Point(10, 0) not in ms.get("w").points
    action(window, Point(60, 0), "Punkt entfernen (Polylinie)")()
    assert ms.get("p").points == (Point(50, 0), Point(60, 10))
    action(window, Point(60, 10), "Verlängern (Polylinie)")()
    click(window, 70, 10)
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    assert ms.get("p").points[-1] == Point(70, 10)
    action(window, Point(0, 0), "Verlängern (Leitung)")()
    click(window, -10, 5)
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    pts = ms.get("w").points
    assert pts[0] == Point(-10, 5)
    assert all(p.x == q.x or p.y == q.y for p, q in zip(pts, pts[1:], strict=False))


def test_right_click_without_command_opens_point_menu(window, monkeypatch):
    shown = []
    monkeypatch.setattr(window, "_show_point_menu", lambda p, g: shown.append(p))
    window.canvas.point_menu_requested.disconnect()
    window.canvas.point_menu_requested.connect(window._show_point_menu)
    click(window, 20, 20, Qt.MouseButton.RightButton)
    assert shown


def test_osnap_menu_controls_modes(window):
    menu = window.osnap_menu
    menu.mode_actions[SnapMode.BUSBAR].setChecked(False)
    assert SnapMode.BUSBAR not in window.canvas.osnap_modes
    assert window.btn_osnap.menu() is menu


def test_new_snap_modes_enabled_for_old_settings(qapp):
    QSettings().clear()
    QSettings().setValue("view/osnap_modes", ["connection", "endpoint"])
    w = MainWindow()
    try:
        modes = w.canvas.osnap_modes
        assert SnapMode.PERPENDICULAR in modes and SnapMode.BUSBAR in modes
        assert SnapMode.MIDPOINT not in modes
    finally:
        w.close()
