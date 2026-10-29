import pytest
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QComboBox, QLineEdit, QPushButton

from blocks_fixtures import blocks
from electrogridy.model.entities import BlockReference, Busbar, Wire
from electrogridy.model.geometry import Point
from electrogridy.ui.main_window import MainWindow


@pytest.fixture
def window(qapp):
    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    w.canvas.fit_rect(QRectF(-20, -20, 160, 120))
    yield w
    w.undo_stack.setClean()
    w.close()


def vp(window, x, y):
    return window.canvas.map_from_scene_f(QPointF(x, y)).toPoint()


def click(window, x, y, button=Qt.MouseButton.LeftButton):
    QTest.mouseClick(window.canvas.viewport(), button, pos=vp(window, x, y))


def wires(window):
    return [e for e in window.document.model_space if isinstance(e, Wire)]


def test_draw_wire_from_connection_point(window):
    window.document.blocks.update(blocks())
    window.document.model_space.add(BlockReference(id="r", name="Sicherung", insert=Point(50, 20)))
    window.act_snap.setChecked(False)
    window.act_wire.trigger()
    click(window, 50.6, 30.5)  # snaps to connection 2 at (50, 30)
    click(window, 80.3, 60.2)
    click(window, 0, 0, Qt.MouseButton.RightButton)
    (wire,) = wires(window)
    assert wire.points[0] == Point(50, 30)
    assert len(wire.points) == 3


def test_drag_block_pulls_wire(window):
    window.document.blocks.update(blocks())
    ms = window.document.model_space
    ms.add(BlockReference(id="r", name="Sicherung", insert=Point(50, 20)))
    ms.add(Wire(id="w", points=(Point(50, 30), Point(50, 60))))
    window.act_osnap.setChecked(False)
    click(window, 50, 25)  # select the reference via its line
    viewport = window.canvas.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 50, 25))
    QTest.mouseMove(viewport, vp(window, 55, 25))
    QTest.mouseMove(viewport, vp(window, 60, 25))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=vp(window, 60, 25))
    assert ms.get("r").insert == Point(60, 20)
    assert ms.get("w").points[0] == Point(60, 30)


def test_junction_dots_follow_model(window, qapp):
    ms = window.document.model_space
    ms.add(Wire(id="a", points=(Point(0, 0), Point(100, 0))))
    junctions = window.space.extra["junctions"]
    qapp.processEvents()
    assert junctions._dots == []
    ms.add(Wire(id="b", points=(Point(50, 0), Point(50, 40))))
    qapp.processEvents()  # dots are computed once per batch of changes
    assert len(junctions._dots) == 1
    ms.remove("b")
    qapp.processEvents()
    assert junctions._dots == []


def test_wire_label_in_properties_dock(window):
    window.document.model_space.add(Wire(id="w", points=(Point(0, 0), Point(60, 0))))
    window._sync.item("w").setSelected(True)
    dock = window.properties_dock
    edit = [e for e in dock.widget().findChildren(QLineEdit) if "NYY" in e.placeholderText()][0]
    edit.setText("NYY-J 5x10")
    [b for b in dock.widget().findChildren(QPushButton) if "Beschriftung" in b.text()][0].click()
    assert window.document.model_space.get("w").label == "NYY-J 5x10"
    assert any(p.id == "w:label" for p in window._sync.item("w")._parts)
    combos = dock.widget().findChildren(QComboBox)
    align = [c for c in combos if c.findData("right") >= 0][0]
    align.setCurrentIndex(align.findData("right"))
    align.activated.emit(align.currentIndex())
    assert window.document.model_space.get("w").label_align == "right"
    height = [c for c in dock.widget().findChildren(QComboBox) if c.findData(3.5) >= 0][-1]
    height.setCurrentIndex(height.findData(3.5))
    height.activated.emit(height.currentIndex())
    wire = window.document.model_space.get("w")
    assert wire.label_height == 3.5 and wire.label_align == "right"
    window.act_undo.trigger()
    assert window.document.model_space.get("w").label_height != 3.5
    position = [c for c in dock.widget().findChildren(QComboBox) if c.findData("free") >= 0][0]
    position.setCurrentIndex(position.findData("free"))
    position.activated.emit(position.currentIndex())
    wire = window.document.model_space.get("w")
    assert wire.label_pos == "free"


def test_busbar_tool_in_window(window):
    window.act_busbar.trigger()
    click(window, 0, 50)
    click(window, 100, 52)
    (bar,) = [e for e in window.document.model_space if isinstance(e, Busbar)]
    assert bar.p2 == Point(100, 50)


def test_shipped_library_in_dock(window):
    dock = window.library_dock
    titles = [lib.title for lib in dock.libraries.values() if lib.shipped]
    assert "SLD: Symbole nach DIN EN 60617" in titles
    assert dock.list.count() >= 40


def test_library_dock_category_filter(window):
    dock = window.library_dock
    index = dock.category.findText("Photovoltaik")
    assert index > 0
    dock.category.setCurrentIndex(index)
    shown = [
        dock.list.item(i).text()
        for i in range(dock.list.count())
        if not dock.list.item(i).isHidden()
    ]
    assert "PV-Modul" in shown and "Leitungsschutzschalter" not in shown
    assert all("mitgeliefert" not in dock.source.itemText(i) for i in range(dock.source.count()))


def test_docked_wire_follows_block(window):
    from electrogridy.model.blocks import BlockDefinition
    from electrogridy.model.container import EntityContainer
    from electrogridy.model.entities import BlockReference, Rectangle
    from electrogridy.ui.point_menu import point_actions

    doc = window.document
    doc.set_block(
        BlockDefinition(
            name="WR",
            base_point=Point(0, 0),
            entities=EntityContainer([Rectangle(id="r", p1=Point(-5, 0), p2=Point(5, 10))]),
        )
    )
    ms = doc.model_space
    ms.add(BlockReference(id="t1", name="WR", insert=Point(100, 50)))
    ms.add(Wire(id="lan", points=(Point(60, 57.5), Point(95, 57.5))))
    actions = dict(point_actions(window, Point(95, 57.5)))
    label = [k for k in actions if k.startswith("Andockpunkt hier setzen")][0]
    actions[label]()
    assert ms.get("t1").docks == (Point(-5, 7.5),)
    # Moving the block drags the wire end along.
    window._sync.item("t1").setSelected(True)
    window.act_move.trigger()
    click(window, 100, 50)
    click(window, 100, 40)
    assert ms.get("lan").points[-1] == Point(95, 47.5)
    assert ms.get("lan").points[0] == Point(60, 57.5)
    # And the dock can be removed again.
    actions = dict(point_actions(window, Point(95, 47.5)))
    remove = [k for k in actions if k.startswith("Andockpunkt entfernen")][0]
    actions[remove]()
    assert ms.get("t1").docks == ()


def test_moving_a_wire_drags_its_branches(window):
    ms = window.document.model_space
    ms.add(Wire(id="main", points=(Point(20, 0), Point(20, 80))))
    ms.add(Wire(id="lan", points=(Point(20, 40), Point(60, 40))))
    window._sync.item("main").setSelected(True)
    window.act_move.trigger()
    click(window, 20, 10)
    click(window, 10, 10)
    assert ms.get("main").points == (Point(10, 0), Point(10, 80))
    assert ms.get("lan").points == (Point(10, 40), Point(60, 40))
    window.act_undo.trigger()
    assert ms.get("lan").points == (Point(20, 40), Point(60, 40))


def test_moving_a_block_drags_wire_and_its_branches(window):
    window.document.blocks.update(blocks())
    window._on_blocks_changed("")
    ms = window.document.model_space
    # Fuse at (50, 100): connection 1 at the top (50, 100).
    ms.add(BlockReference(id="e1", name="Sicherung", insert=Point(50, 100)))
    ms.add(Wire(id="trunk", points=(Point(50, 100), Point(50, 20))))
    ms.add(Wire(id="lan", points=(Point(50, 40), Point(90, 40))))
    window._sync.item("e1").setSelected(True)
    window.act_move.trigger()
    click(window, 50, 100)
    click(window, 40, 100)
    trunk = ms.get("trunk")
    assert trunk.points[0] == Point(40, 100)
    lan = ms.get("lan")
    # The branch end is still on the trunk.
    from electrogridy.model.wires import on_segment, segments

    assert any(on_segment(lan.points[0], a, b) for a, b in segments(trunk.points))
    assert lan.points[-1] == Point(90, 40)


def test_add_point_then_shift_one_half(window):
    from electrogridy.model.grips import grip_points, move_grip
    from electrogridy.ui.point_menu import point_actions

    ms = window.document.model_space
    ms.add(Wire(id="w", points=(Point(0, 50), Point(100, 50))))
    actions = dict(point_actions(window, Point(40, 50)))
    add = [k for k in actions if k.startswith("Punkt hinzufügen")][0]
    actions[add]()
    w = ms.get("w")
    assert w.points == (Point(0, 50), Point(40, 50), Point(100, 50))
    # Segment grips: ends, then one per half.
    assert grip_points(w)[2:] == [Point(20, 50), Point(70, 50)]
    jog = move_grip(w, 3, Point(70, 60))  # right half 10 mm down
    assert jog.points == (
        Point(0, 50),
        Point(40, 50),
        Point(40, 60),
        Point(100, 60),
        Point(100, 50),
    )


def test_moving_a_device_does_not_connect_wires_by_chance(window, qapp):
    from electrogridy.model.entities import JunctionMark

    window.document.blocks.update(blocks())
    window._on_blocks_changed("")
    ms = window.document.model_space
    ms.add(BlockReference(id="f", name="Sicherung", insert=Point(50, 100)))
    ms.add(Wire(id="w", points=(Point(50, 100), Point(50, 20))))  # docked at the fuse
    ms.add(Wire(id="x", points=(Point(47.5, 140), Point(47.5, 100))))  # someone else's end

    window.act_osnap.setChecked(False)  # plain grid clicks

    def move_fuse(dx):
        window.scene.clearSelection()
        window._sync.item("f").setSelected(True)
        window.act_move.trigger()
        click(window, 50 if dx == -5 else 45, 100)
        click(window, (50 if dx == -5 else 45) + dx, 100)

    move_fuse(-5)
    # The pulled wire now runs through x's end, but they must not be connected.
    assert ms.get("w").points[0] == Point(45, 100)
    marks = [e for e in ms if isinstance(e, JunctionMark)]
    assert [(m.position, m.connected) for m in marks] == [(Point(47.5, 100), False)]
    qapp.processEvents()
    assert window.space.extra["junctions"]._dots == []
    move_fuse(-5)
    assert ms.get("x").points == (Point(47.5, 140), Point(47.5, 100))  # stays put
    # Undo removes the separation mark again.
    window.act_undo.trigger()
    window.act_undo.trigger()
    assert not [e for e in ms if isinstance(e, JunctionMark)]


def test_drag_segment_grip_with_the_mouse(window, qapp):
    from electrogridy.model.grips import grip_kinds, grip_points

    ms = window.document.model_space
    ms.add(Wire(id="w", points=(Point(0, 40), Point(60, 40), Point(60, 10))))
    window._sync.item("w").setSelected(True)
    window.act_osnap.setChecked(True)  # the own midpoint must not catch the grip
    qapp.processEvents()
    wire = ms.get("w")
    index = [i for i, k in enumerate(grip_kinds(wire)) if k == "segment"][1]
    grip = grip_points(wire)[index]
    assert grip == Point(60, 25)
    viewport = window.canvas.viewport()
    press = window.canvas.map_from_scene_f(QPointF(grip.x, grip.y)).toPoint()
    press.setX(press.x() + 5)  # a little beside the grip still takes it
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=press)
    assert window.tools.active is not None
    assert "Abschnitt verschieben" in window.tools.prompt()
    target = window.canvas.map_from_scene_f(QPointF(40, 25)).toPoint()
    QTest.mouseMove(viewport, target)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=target)
    moved = ms.get("w")
    assert moved.points[0] == Point(0, 40) and moved.points[-1] == Point(60, 10)
    assert Point(40, 40) in moved.points and Point(40, 10) in moved.points
    assert window.tools.active is None


def test_moving_a_wire_keeps_a_connection_set_on_a_crossing(window):
    from electrogridy.model.entities import JunctionMark

    ms = window.document.model_space
    ms.add(Wire(id="v", points=(Point(20, 0), Point(20, 80))))
    ms.add(Wire(id="h", points=(Point(0, 40), Point(60, 40))))
    ms.add(JunctionMark(id="m", position=Point(20, 40), connected=True))
    window.act_osnap.setChecked(False)
    window._sync.item("v").setSelected(True)
    window.act_move.trigger()
    click(window, 20, 10)
    click(window, 30, 10)
    assert ms.get("m").position == Point(30, 40)
    window.act_undo.trigger()
    assert ms.get("m").position == Point(20, 40)
