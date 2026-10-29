import pytest
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QGraphicsScene

from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Line, Rectangle
from electrogridy.model.geometry import Point
from electrogridy.view.canvas import Canvas
from electrogridy.view.items import EntityItem
from electrogridy.view.render import Style, make_pen
from electrogridy.view.scene_sync import SceneSync
from factories import sample_entities


def style(_e):
    return Style(QColor("black"), 0.25)


@pytest.fixture
def setup(qapp):
    scene = QGraphicsScene()
    container = EntityContainer()
    sync = SceneSync(scene, container, style)
    canvas = Canvas(scene)
    canvas.resize(800, 600)
    canvas.show()
    qapp.processEvents()
    yield canvas, scene, container, sync
    canvas.close()


def entity_items(scene):
    return [i for i in scene.items() if isinstance(i, EntityItem)]


def test_scene_follows_container(setup):
    _, scene, container, _ = setup
    for e in sample_entities():
        container.add(e)
    assert len(entity_items(scene)) == len(sample_entities())
    container.replace(container.get("l1").translated(0, 100))
    assert scene.items(QPointF(5, 100))  # moved line is hit at its new place
    container.remove("l1")
    assert len(entity_items(scene)) == len(sample_entities()) - 1


def test_z_order_follows_container_order(setup):
    _, _, container, sync = setup
    a = Line(id="a", p1=Point(0, 0), p2=Point(1, 0))
    b = Line(id="b", p1=Point(0, 0), p2=Point(1, 0))
    container.add(a)
    container.add(b)
    assert sync.item("b").zValue() > sync.item("a").zValue()
    container.remove("a")
    container.add(a, 1)
    assert sync.item("a").zValue() > sync.item("b").zValue()


def test_pen_is_real_mm_but_at_least_one_pixel():
    assert make_pen(QColor("black"), 0.5, 10.0).widthF() == pytest.approx(0.5)
    assert make_pen(QColor("black"), 0.25, 1.0).widthF() == pytest.approx(1.0)


def test_constrain_snaps_to_grid(setup):
    canvas, *_ = setup
    canvas.snap_spacing = 2.5
    assert canvas.constrain(QPointF(3.7, 1.3)) == QPointF(2.5, 2.5)
    canvas.snap_enabled = False
    assert canvas.constrain(QPointF(3.7, 1.3)) == QPointF(3.7, 1.3)


def test_window_selection_needs_full_containment(setup):
    canvas, scene, container, _ = setup
    container.add(Rectangle(id="inside", p1=Point(10, 10), p2=Point(20, 20)))
    container.add(Rectangle(id="partly", p1=Point(25, 10), p2=Point(60, 20)))
    canvas.select_in_rect(QRectF(0, 0, 40, 40), crossing=False)
    assert {i.entity_id for i in scene.selectedItems()} == {"inside"}
    canvas.select_in_rect(QRectF(0, 0, 40, 40), crossing=True)
    assert {i.entity_id for i in scene.selectedItems()} == {"inside", "partly"}


def view_point(canvas, x, y) -> QPoint:
    return canvas.map_from_scene_f(QPointF(x, y)).toPoint()


def test_click_selects_and_drag_right_to_left_crosses(setup):
    canvas, scene, container, _ = setup
    canvas.fit_rect(QRectF(0, 0, 100, 100))
    container.add(Line(id="a", p1=Point(10, 50), p2=Point(90, 50)))
    container.add(Line(id="b", p1=Point(10, 70), p2=Point(90, 70)))
    vp = canvas.viewport()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=view_point(canvas, 50, 50))
    assert [i.entity_id for i in scene.selectedItems()] == ["a"]
    QTest.mouseClick(
        vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, view_point(canvas, 50, 70)
    )
    assert {i.entity_id for i in scene.selectedItems()} == {"a", "b"}
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=view_point(canvas, 50, 20))
    assert scene.selectedItems() == []
    # Crossing from right to left touching only line b.
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=view_point(canvas, 60, 80))
    QTest.mouseMove(vp, view_point(canvas, 40, 65))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=view_point(canvas, 40, 65))
    assert [i.entity_id for i in scene.selectedItems()] == ["b"]
