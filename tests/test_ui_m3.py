import pytest
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest

from factories import sample_entities
from sldgridy.model.entities import Line, Text
from sldgridy.model.geometry import Point
from sldgridy.model.layers import Layer
from sldgridy.ui.main_window import MainWindow
from sldgridy.ui.styles import BY_LAYER
from sldgridy.view.render import make_pen


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


def click(window, x, y, button=Qt.MouseButton.LeftButton):
    QTest.mouseClick(window.canvas.viewport(), button, pos=vp(window, x, y))


def drag(window, a, b):
    viewport = window.canvas.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=vp(window, *a))
    QTest.mouseMove(viewport, vp(window, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    QTest.mouseMove(viewport, vp(window, *b))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=vp(window, *b))


def add_line(window, id_="a", y=50.0, layer="0"):
    line = Line(id=id_, layer=layer, p1=Point(20, y), p2=Point(80, y))
    window.document.model_space.add(line)
    return line


def test_drag_selected_object_moves_it(window):
    window.act_osnap.setChecked(False)
    add_line(window)
    click(window, 50, 50)
    drag(window, (50, 50), (50, 70))
    line = window.document.model_space.get("a")
    assert (line.p1, line.p2) == (Point(20, 70), Point(80, 70))
    window.act_undo.trigger()
    assert window.document.model_space.get("a").p1 == Point(20, 50)


def test_drag_unselected_object_selects_and_moves(window):
    window.act_osnap.setChecked(False)
    add_line(window)
    drag(window, (50, 50), (60, 50))
    assert window.document.model_space.get("a").p1 == Point(30, 50)


def test_move_command_asks_for_selection(window):
    window.act_osnap.setChecked(False)
    add_line(window)
    window.act_move.trigger()
    assert window.tools.selecting()
    click(window, 50, 50)
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    assert not window.tools.selecting()
    click(window, 50, 50)
    click(window, 50, 30)
    assert window.document.model_space.get("a").p1 == Point(20, 30)


def test_grip_drag_stretches_line(window):
    window.act_osnap.setChecked(False)
    add_line(window)
    click(window, 50, 50)
    click(window, 80, 50)  # grip at the end point
    assert window.tools.active is not None
    click(window, 90, 60)
    line = window.document.model_space.get("a")
    assert (line.p1, line.p2) == (Point(20, 50), Point(90, 60))


def test_object_snap_to_endpoint(window):
    window.act_snap.setChecked(False)
    add_line(window)
    window.act_line.trigger()
    click(window, 80.6, 50.4)
    click(window, 80.6, 90)
    window.tools.cancel()
    new = [e for e in window.document.model_space if e.id != "a"][0]
    assert new.p1 == Point(80, 50)


def test_typed_coordinates_draw_line(window):
    window.act_line.trigger()
    window.command_line.submitted.emit("10,10")
    window.command_line.submitted.emit("@30,0")
    window.command_line.submitted.emit("")
    (line,) = list(window.document.model_space)
    assert (line.p1, line.p2) == (Point(10, 10), Point(40, 10))
    assert window.tools.active is None


def test_typing_on_canvas_goes_to_command_line(window):
    window.act_line.trigger()
    window.canvas.setFocus()
    # Numbers go into the fields at the cursor; "@" starts command line input.
    QTest.keyClicks(window.canvas, "@")
    assert window.command_line.edit.text() == "@"
    window.command_line.edit.clear()
    window.canvas.set_dynamic_enabled(False)
    window.canvas.setFocus()
    QTest.keyClicks(window.canvas, "5")
    assert window.command_line.edit.text() == "5"


def test_hidden_and_locked_layers(window):
    window.document.insert_layer(1, Layer("Kabel"))
    add_line(window, "k", layer="Kabel")
    item = window._sync.item("k")
    layer = window.document.layer("Kabel")
    from dataclasses import replace

    from sldgridy.commands.layers import ChangeLayerCommand

    window.push(ChangeLayerCommand(window.document, "Kabel", replace(layer, locked=True), "x"))
    click(window, 50, 50)
    assert window.selected_ids() == []
    window.push(
        ChangeLayerCommand(
            window.document, "Kabel", replace(layer, locked=False, visible=False), "x"
        )
    )
    assert not item.isVisible()
    window.act_undo.trigger()
    assert item.isVisible()


def test_layer_color_drives_rendering(window):
    window.document.insert_layer(1, Layer("Kabel", color="#0000ff", lineweight=0.5))
    line = add_line(window, "k", layer="Kabel")
    style = window._resolve_style(line)
    assert style.color == QColor("#0000ff") and style.lineweight == 0.5


def test_properties_dock_changes_selection(window):
    for e in sample_entities():
        window.document.model_space.add(e)
    window.act_select_all.trigger()
    dock = window.properties_dock
    assert f"{len(sample_entities())} Objekte" in dock.lbl_selection.text()
    dock.cmb_weight.setCurrentIndex(dock.cmb_weight.findData(0.7))
    dock.cmb_weight.activated.emit(dock.cmb_weight.currentIndex())
    assert all(e.lineweight == 0.7 for e in window.document.model_space)
    window.act_undo.trigger()
    assert window.document.model_space.get("l1").lineweight is None
    dock.refresh()
    dock.cmb_color.setCurrentIndex(dock.cmb_color.findData(BY_LAYER))
    dock.cmb_color.activated.emit(dock.cmb_color.currentIndex())
    assert all(e.color is None for e in window.document.model_space)


def test_properties_dock_edits_text(window):
    window.document.model_space.add(Text(id="t", position=Point(10, 10), text="alt"))
    window._sync.item("t").setSelected(True)
    dock = window.properties_dock
    dock.txt_text.setPlainText("neu")
    dock.btn_apply_text.click()
    assert window.document.model_space.get("t").text == "neu"


def test_layers_dock_add_rename_current_delete(window):
    dock = window.layers_dock
    dock.add_layer()
    assert window.document.layers[-1].name == "Ebene 1"
    row = len(window.document.layers) - 1
    dock.table.item(row, 1).setText("Kabel")
    assert window.document.layers[-1].name == "Kabel"
    dock.table.selectRow(row)
    dock.btn_current.click()
    assert window.current_layer == "Kabel"
    window.act_line.trigger()
    click(window, 10, 10)
    click(window, 30, 10)
    window.tools.cancel()
    (line,) = list(window.document.model_space)
    assert line.layer == "Kabel"
    dock.delete_selected()  # current and in use: refused
    assert window.document.has_layer("Kabel")


def test_clipboard_copy_and_paste(window):
    add_line(window)
    window.act_select_all.trigger()
    window.act_copy_clip.trigger()
    window.act_paste.trigger()
    click(window, 20, 80)
    lines = list(window.document.model_space)
    assert len(lines) == 2
    assert lines[1].p1.y == pytest.approx(80, abs=0.5)


def test_cut_removes_and_paste_restores(window):
    add_line(window)
    window.act_select_all.trigger()
    window.act_cut.trigger()
    assert len(window.document.model_space) == 0
    window.act_paste.trigger()
    click(window, 20, 50)
    assert len(window.document.model_space) == 1


def test_dashed_pen_pattern_in_mm():
    pen = make_pen(QColor("black"), 0.25, 20.0, "dashed")
    assert pen.dashPattern() == [12.0, 3.0]
    # Widened on screen: pattern shrinks so dash lengths stay 3 mm / 0.75 mm.
    pen = make_pen(QColor("black"), 0.25, 2.0, "dashed")
    assert pen.widthF() == pytest.approx(0.5)
    assert [v * pen.widthF() for v in pen.dashPattern()] == pytest.approx([3.0, 0.75])


def test_floating_docks_can_be_docked_again(window):
    from sldgridy.ui.dock_title import DockTitleBar

    for dock in window.docks():
        bar = dock.titleBarWidget()
        assert isinstance(bar, DockTitleBar)
        bar.btn_float.click()
        assert dock.isFloating()
        bar.btn_float.click()
        assert not dock.isFloating()
    window.layers_dock.setFloating(True)
    window.properties_dock.close()
    window.reset_dock_layout()
    assert not window.layers_dock.isFloating() and window.properties_dock.isVisible()
    assert window.dockWidgetArea(window.library_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    window.library_dock.setFloating(True)
    window.dock_all()
    assert not window.library_dock.isFloating()


def test_dock_context_menu_docks_to_area(window):
    bar = window.library_dock.titleBarWidget()
    bar.dock_to(Qt.DockWidgetArea.BottomDockWidgetArea)
    assert window.dockWidgetArea(window.library_dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    window.library_dock.setFloating(True)
    bar.dock_to(Qt.DockWidgetArea.RightDockWidgetArea)
    assert not window.library_dock.isFloating()
    assert window.dockWidgetArea(window.library_dock) == Qt.DockWidgetArea.RightDockWidgetArea


def test_line_by_typed_length_and_angle_at_the_cursor(window):
    from sldgridy.model.entities import Line as LineEntity

    window.act_osnap.setChecked(False)
    window.act_line.trigger()
    window.canvas.setFocus()
    click(window, 10, 10)
    QTest.mouseMove(window.canvas.viewport(), vp(window, 40, 30))
    QTest.keyClicks(window.canvas, "125,5")
    QTest.keyClick(window.canvas, Qt.Key.Key_Tab)
    QTest.keyClicks(window.canvas, "90")
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    lines = [e for e in window.document.model_space if isinstance(e, LineEntity)]
    assert len(lines) == 1
    assert lines[0].p1 == Point(10, 10)
    assert lines[0].p2.x == pytest.approx(10) and lines[0].p2.y == pytest.approx(10 - 125.5)
    # The next segment starts there, the fields are empty again.
    assert not window.canvas.dynamic.has_input()


def test_rectangle_by_typed_width_and_height(window):
    from sldgridy.model.entities import Rectangle as RectangleEntity

    window.act_osnap.setChecked(False)
    window.act_rectangle.trigger()
    window.canvas.setFocus()
    click(window, 0, 0)
    QTest.mouseMove(window.canvas.viewport(), vp(window, 20, 20))
    QTest.keyClicks(window.canvas, "60")
    QTest.keyClick(window.canvas, Qt.Key.Key_Tab)
    QTest.keyClicks(window.canvas, "25")
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    (rect,) = [e for e in window.document.model_space if isinstance(e, RectangleEntity)]
    assert {rect.p1, rect.p2} == {Point(0, 0), Point(60, 25)}


def test_switching_tools_switches_the_fields_without_error(window):
    window.act_osnap.setChecked(False)
    window.act_line.trigger()
    click(window, 10, 10)
    QTest.mouseMove(window.canvas.viewport(), vp(window, 40, 30))
    window.canvas.viewport().repaint()
    window.tools.cancel()
    window.act_rectangle.trigger()
    click(window, 0, 0)
    window.canvas.viewport().repaint()  # painted before the next mouse move
    assert window.canvas.dynamic.mode == "size"


def test_dimension_tool_horizontal_and_aligned(window):
    from sldgridy.model.dimensions import dimension_geometry, measured
    from sldgridy.model.entities import Dimension
    from sldgridy.model.grips import grip_points, move_grip

    window.act_osnap.setChecked(False)
    window.act_dimension.trigger()
    click(window, 10, 40)
    click(window, 60, 50)
    click(window, 35, 20)  # dragged above: horizontal
    (d,) = [e for e in window.document.model_space if isinstance(e, Dimension)]
    assert d.orientation == "horizontal" and measured(d) == pytest.approx(50)
    texts = [p.text for p in dimension_geometry(d) if hasattr(p, "text")]
    assert texts == ["50"]
    window.tools.cancel()
    window.act_dimension_aligned.trigger()
    click(window, 0, 0)
    click(window, 30, 40)
    click(window, -10, 10)
    aligned = [e for e in window.document.model_space if isinstance(e, Dimension)][-1]
    assert aligned.orientation == "aligned" and measured(aligned) == pytest.approx(50)
    # Grips: the measured points and the dimension line position.
    assert len(grip_points(d)) == 3
    assert move_grip(d, 2, Point(35, 70)).position == Point(35, 70)
    window.act_undo.trigger()
    window.act_undo.trigger()
    assert not [e for e in window.document.model_space if isinstance(e, Dimension)]


def test_dimension_properties_in_the_dock(window):
    from PyQt6.QtWidgets import QLineEdit

    from sldgridy.model.entities import Dimension

    ms = window.document.model_space
    ms.add(Dimension(id="d", p1=Point(0, 0), p2=Point(40, 0), position=Point(20, -10)))
    window._sync.item("d").setSelected(True)
    dock = window.properties_dock
    edit = [e for e in dock.widget().findChildren(QLineEdit) if "40" in e.placeholderText()][0]
    edit.setText("ca. 40")
    edit.editingFinished.emit()
    assert ms.get("d").text == "ca. 40"


def test_rotate_by_typed_angle_with_the_dropdown_tool(window):
    from sldgridy.model.entities import Line as LineEntity

    window.act_osnap.setChecked(False)
    ms = window.document.model_space
    ms.add(LineEntity(id="l", p1=Point(10, 10), p2=Point(50, 10)))
    window._sync.item("l").setSelected(True)
    window.act_rotate_free.trigger()
    window.canvas.setFocus()
    click(window, 10, 10)  # pivot
    QTest.mouseMove(window.canvas.viewport(), vp(window, 40, 20))
    QTest.keyClick(window.canvas, Qt.Key.Key_Tab)
    QTest.keyClicks(window.canvas, "30")
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    line = ms.get("l")
    assert line.p1 == Point(10, 10)
    assert line.p2.x == pytest.approx(10 + 40 * 0.8660254) and line.p2.y == pytest.approx(-10)
    menu_texts = [a.text() for a in window.btn_rotate.menu().actions()]
    assert len(menu_texts) == 2  # any angle and 90° steps


def test_typed_length_snaps_onto_an_edge(window):
    from sldgridy.model.entities import Line as LineEntity

    ms = window.document.model_space
    ms.add(LineEntity(id="eave", p1=Point(-100, -30), p2=Point(100, -30)))
    window.act_osnap.setChecked(True)
    window.act_line.trigger()
    window.canvas.setFocus()
    click(window, 0, 0)
    QTest.keyClicks(window.canvas, "50")
    QTest.mouseMove(window.canvas.viewport(), vp(window, 39.5, -30.8))
    assert window.canvas._snap_hit is not None  # crossing of the 50 mm circle and the edge
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    new = [e for e in ms if isinstance(e, LineEntity) and e.id != "eave"][0]
    assert new.p2.x == pytest.approx(40) and new.p2.y == pytest.approx(-30)


def test_typed_length_snaps_to_angle_steps(window):
    from sldgridy.model.entities import Line as LineEntity

    window.act_osnap.setChecked(False)
    window.canvas.polar_increment = 15.0
    window.act_line.trigger()
    window.canvas.setFocus()
    click(window, 0, 0)
    QTest.keyClicks(window.canvas, "40")
    # Mouse a little off the 45° direction.
    QTest.mouseMove(window.canvas.viewport(), vp(window, 29, -27))
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    (line,) = [e for e in window.document.model_space if isinstance(e, LineEntity)]
    assert line.p2.x == pytest.approx(40 * 0.70710678, abs=1e-6)
    assert line.p2.y == pytest.approx(-40 * 0.70710678, abs=1e-6)


def test_first_digit_after_a_click_is_kept(window):
    window.act_osnap.setChecked(False)
    window.act_line.trigger()
    window.canvas.setFocus()
    click(window, 0, 0)  # no mouse move afterwards
    QTest.keyClicks(window.canvas, "40")
    assert window.canvas.dynamic.texts.get("length") == "40"


def test_dimension_button_offers_parallel(window):
    button = window.btn_dimension
    assert button.menu().actions() == [
        window.act_dimension,
        window.act_dimension_aligned,
        window.act_dimension_angle,
    ]
    assert window.act_dimension_aligned in window.draw_menu.actions()
    window.act_osnap.setChecked(False)
    window.act_dimension_aligned.trigger()  # as chosen from the drop-down
    button.menu().triggered.emit(window.act_dimension_aligned)
    assert button.defaultAction() is window.act_dimension_aligned
    window.tools.cancel()
    button.click()  # repeats the last variant
    click(window, 0, 0)
    click(window, 30, 40)
    click(window, 10, -10)
    from sldgridy.model.dimensions import dimension_geometry
    from sldgridy.model.entities import Dimension

    (d,) = [e for e in window.document.model_space if isinstance(e, Dimension)]
    assert d.orientation == "aligned"
    line = next(p for p in dimension_geometry(d) if p.id.endswith(":line"))
    # Parallel to the measured line 0,0 to 30,40.
    assert (line.p2.x - line.p1.x) * 40 == pytest.approx((line.p2.y - line.p1.y) * 30)
    window.act_undo.trigger()


def test_angle_dimension_tool(window):
    from sldgridy.model.dimensions import measured
    from sldgridy.model.entities import Dimension

    window.act_osnap.setChecked(False)
    window.act_dimension_angle.trigger()
    click(window, 0, 0)  # vertex
    click(window, 50, 0)
    click(window, 0, -50)
    click(window, 20, -20)
    (d,) = [e for e in window.document.model_space if isinstance(e, Dimension)]
    assert d.orientation == "angular" and d.vertex == Point(0, 0)
    assert measured(d) == pytest.approx(90)
    window.act_undo.trigger()


def test_angle_dimension_snaps_onto_sloped_leg(window):
    from sldgridy.model.dimensions import measured
    from sldgridy.model.entities import Dimension, Line

    ms = window.document.model_space
    ms.add(Line(id="base", p1=Point(0, 0), p2=Point(80, 0)))
    ms.add(Line(id="left", p1=Point(0, 0), p2=Point(30, -50)))
    window.act_dimension_angle.trigger()
    click(window, 0, 0)
    click(window, 80, 0)
    click(window, 20, -30)  # grid point beside the leg (the leg passes 18, -30)
    click(window, 15, -10)
    (d,) = [e for e in ms if isinstance(e, Dimension)]
    assert d.p2 == Point(30, -50)
    assert measured(d) == pytest.approx(59.036243)
    window.act_undo.trigger()


def test_dimension_dock_edits_several_dimensions(window):
    from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QGroupBox, QLineEdit

    from sldgridy.model.entities import Dimension

    ms = window.document.model_space
    ms.add(Dimension(id="a", p1=Point(0, 0), p2=Point(40, 0), position=Point(20, -10)))
    ms.add(
        Dimension(
            id="b",
            p1=Point(0, 20),
            p2=Point(30, 20),
            position=Point(15, 30),
            orientation="horizontal",
            height=5.0,
            text="x",
        )
    )
    for i in ("a", "b"):
        window._sync.item(i).setSelected(True)
    dock = window.properties_dock.widget()
    box = [b for b in dock.findChildren(QGroupBox) if b.title().startswith("Bemaßung")][-1]
    assert box.title() == "Bemaßung (2)"
    (text,) = box.findChildren(QLineEdit, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert text.text() == "" and text.placeholderText() == "*verschieden*"
    (height,) = box.findChildren(QDoubleSpinBox)
    assert height.text() == "*verschieden*"
    (orientation,) = box.findChildren(QComboBox)
    assert orientation.currentText() == "*verschieden*"
    # Leaving the text field unchanged keeps both texts.
    text.editingFinished.emit()
    assert (ms.get("a").text, ms.get("b").text) == ("", "x")
    height.setValue(3.5)
    assert ms.get("a").height == ms.get("b").height == 3.5
    box = [b for b in dock.findChildren(QGroupBox) if b.title().startswith("Bemaßung")][-1]
    (text,) = box.findChildren(QLineEdit, options=Qt.FindChildOption.FindDirectChildrenOnly)
    text.setText("ca.")
    text.editingFinished.emit()
    assert ms.get("a").text == ms.get("b").text == "ca."
    box = [b for b in dock.findChildren(QGroupBox) if b.title().startswith("Bemaßung")][-1]
    (orientation,) = box.findChildren(QComboBox)
    orientation.setCurrentIndex(orientation.findData("aligned"))
    orientation.activated.emit(orientation.currentIndex())
    assert ms.get("a").orientation == ms.get("b").orientation == "aligned"
    # All of it in single undo steps per field.
    window.act_undo.trigger()
    assert ms.get("b").orientation == "horizontal"


def test_wire_label_dock_edits_several_wires(window):
    from PyQt6.QtWidgets import QGroupBox, QLineEdit

    from sldgridy.model.entities import Wire
    from sldgridy.ui.styles import HeightCombo

    ms = window.document.model_space
    ms.add(Wire(id="w1", points=(Point(0, 0), Point(40, 0)), label="NYY-J 5x16"))
    ms.add(Wire(id="w2", points=(Point(0, 20), Point(40, 20)), label_height=5.0))
    for i in ("w1", "w2"):
        window._sync.item(i).setSelected(True)
    dock = window.properties_dock.widget()
    (box,) = [b for b in dock.findChildren(QGroupBox) if b.title() == "Beschriftung (2)"]
    edit = box.findChildren(QLineEdit, options=Qt.FindChildOption.FindDirectChildrenOnly)[0]
    assert edit.placeholderText() == "*verschieden*"
    (height,) = box.findChildren(HeightCombo)
    assert height.currentText() == "" and height.lineEdit().placeholderText() == "*verschieden*"
    edit.returnPressed.emit()  # unchanged: both labels stay
    assert (ms.get("w1").label, ms.get("w2").label) == ("NYY-J 5x16", "")
    height.setEditText("12,5")  # any height, not only the listed ones
    height.lineEdit().editingFinished.emit()
    assert ms.get("w1").label_height == ms.get("w2").label_height == 12.5
    assert ms.get("w1").label == "NYY-J 5x16"


def test_text_height_can_be_typed_freely(window):
    from sldgridy.model.entities import Text
    from sldgridy.ui.styles import parse_mm

    assert parse_mm("125") == 125 and parse_mm("3,5 mm") == 3.5 and parse_mm("0") is None
    ms = window.document.model_space
    ms.add(Text(id="t", position=Point(0, 0), text="Dach", height=2.5))
    window._sync.item("t").setSelected(True)
    box = window.properties_dock.cmb_height
    box.setEditText("125")
    box.lineEdit().editingFinished.emit()
    assert ms.get("t").height == 125
    assert box.currentText() == "125 mm"
    box.setEditText("abc")  # not a number: back to the old value, nothing changes
    box.lineEdit().editingFinished.emit()
    assert ms.get("t").height == 125 and box.currentText() == "125 mm"


def test_polyline_snaps_to_its_own_start_and_closes(window):
    from sldgridy.model.entities import Polyline

    window.act_snap.setChecked(False)
    window.act_osnap.setChecked(True)
    window.act_polyline.trigger()
    click(window, 0, 0)
    click(window, 40, 0)
    click(window, 40, -30)
    # Slightly beside the start: the object snap of the unfinished polyline catches it.
    click(window, 0.6, 0.4)
    (poly,) = [e for e in window.document.model_space if isinstance(e, Polyline)]
    assert poly.closed and poly.points[0] == Point(0, 0) and len(poly.points) == 3
    window.act_undo.trigger()


def test_scale_by_typed_factor(window):
    from sldgridy.model.entities import Line as LineEntity

    window.act_osnap.setChecked(False)
    ms = window.document.model_space
    ms.add(LineEntity(id="l", p1=Point(10, 10), p2=Point(30, 10)))
    window._sync.item("l").setSelected(True)
    window.act_scale.trigger()
    window.canvas.setFocus()
    click(window, 10, 10)  # base point
    QTest.keyClicks(window.canvas, "2,5")
    window.canvas.viewport().repaint()  # the factor box is drawn
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    line = ms.get("l")
    assert (line.p1, line.p2) == (Point(10, 10), Point(60, 10))
    assert window.tools.active is None
    window.act_undo.trigger()
    assert ms.get("l").p2 == Point(30, 10)


def test_scale_by_factor_without_base_point(window):
    """Select all, type the factor, Enter: around the upper left corner of the
    selection, so imported pages keep their place (Florian 2026-10-28)."""
    from sldgridy.model.entities import Line as LineEntity
    from sldgridy.model.entities import Text as TextEntity

    window.act_osnap.setChecked(False)
    ms = window.document.model_space
    ms.add(LineEntity(id="l", p1=Point(20, 40), p2=Point(120, 40)))
    ms.add(TextEntity(id="t", position=Point(30, 10), text="-Q1", height=2.5))
    for i in ("l", "t"):
        window._sync.item(i).setSelected(True)
    window.act_scale.trigger()
    window.canvas.setFocus()
    QTest.mouseMove(window.canvas.viewport(), vp(window, 200, 200))
    QTest.keyClicks(window.canvas, "0,5")
    window.canvas.viewport().repaint()  # factor box and preview are drawn
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    line, text = ms.get("l"), ms.get("t")
    assert (line.p1, line.p2) == (Point(20, 25), Point(70, 25))  # around (20, 10)
    assert text.position == Point(25, 10) and text.height == pytest.approx(1.25)
    window.act_undo.trigger()
    # Tab to X/Y: a typed base point.
    for i in ("l", "t"):
        window._sync.item(i).setSelected(True)
    window.act_scale.trigger()
    QTest.keyClicks(window.canvas, "2")
    QTest.keyClick(window.canvas, Qt.Key.Key_Tab)
    QTest.keyClicks(window.canvas, "20")
    QTest.keyClick(window.canvas, Qt.Key.Key_Tab)
    QTest.keyClicks(window.canvas, "40")
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    assert ms.get("l").p2 == Point(220, 40)
    window.act_undo.trigger()


def test_scale_by_reference_and_new_length(window):
    from sldgridy.model.entities import Line as LineEntity

    window.act_osnap.setChecked(True)  # the reference point snaps onto the line end
    ms = window.document.model_space
    ms.add(LineEntity(id="l", p1=Point(0, 0), p2=Point(42, 0)))  # drawn 42, should be 50
    window._sync.item("l").setSelected(True)
    window.act_scale.trigger()
    window.canvas.setFocus()
    click(window, 0, 0)  # base
    click(window, 42, 0)  # reference: the known length
    QTest.mouseMove(window.canvas.viewport(), vp(window, 45, 0))
    QTest.keyClicks(window.canvas, "50")
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    assert ms.get("l").p2.x == pytest.approx(50)
    window.act_undo.trigger()
