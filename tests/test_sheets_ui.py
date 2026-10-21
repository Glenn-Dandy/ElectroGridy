import pytest
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt
from PyQt6.QtTest import QTest

from sldgridy.fileio.paths import system_template_dir
from sldgridy.model.entities import Line, Viewport
from sldgridy.model.geometry import Point
from sldgridy.ui.main_window import MainWindow
from sldgridy.ui.sheet_controller import format_scale, parse_scale
from sldgridy.ui.sheet_dialogs import FieldsDialog, FormatDialog
from sldgridy.ui.space import MODEL, SHEET


@pytest.fixture
def window(qapp):
    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    yield w
    w.undo_stack.setClean()
    w.close()


def test_scale_parsing():
    assert parse_scale("1:5") == 0.2
    assert parse_scale("2:1") == 2.0
    assert parse_scale("1:2,5") == 0.4
    assert parse_scale("0,5") == 0.5
    assert parse_scale("x") is None and parse_scale("1:0") is None
    assert format_scale(0.2) == "1:5" and format_scale(2.0) == "2:1"


def test_tabs_switch_spaces(window):
    tabs = window.sheets.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Modell", "Blatt 1"]
    tabs.setCurrentIndex(1)
    assert window.space.kind == SHEET
    assert window.container is window.document.sheets[0].entities
    tabs.setCurrentIndex(0)
    assert window.space.kind == MODEL


def test_drawing_on_sheet_goes_to_sheet(window):
    window.sheets.tabs.setCurrentIndex(1)
    window.canvas.fit_rect(QRectF(0, 0, 200, 150))
    window.act_line.trigger()
    for x, y in ((50, 50), (100, 50)):
        pos = window.canvas.map_from_scene_f(QPointF(x, y)).toPoint()
        QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    window.tools.cancel()
    assert [type(e).__name__ for e in window.document.sheets[0].entities] == ["Viewport", "Line"]
    assert list(window.document.model_space) == []


def answer_new_page(window, monkeypatch, kind="drawing"):
    from sldgridy.model.paper import Orientation
    from sldgridy.ui.page_dialog import PageSpec

    spec = PageSpec(kind, "", "", "", "A3", Orientation.LANDSCAPE, kind == "drawing")
    monkeypatch.setattr(window.sheets, "_page_spec", lambda title, default, new: spec)


def test_new_duplicate_delete_sheet(window, monkeypatch):
    answer_new_page(window, monkeypatch)
    window.sheets.act_new.trigger()
    assert [s.name for s in window.document.sheets] == ["Blatt 1", "Blatt 2"]
    assert window.sheets.current_sheet().name == "Blatt 2"
    window.sheets.duplicate_sheet()
    assert len(window.document.sheets) == 3
    window.act_undo.trigger()
    assert len(window.document.sheets) == 2
    window.act_undo.trigger()
    assert len(window.document.sheets) == 1
    assert window.sheets.tabs.count() == 2


def test_viewport_activation_and_zoom(window):
    window.document.model_space.add(Line(id="m", p1=Point(0, 0), p2=Point(100, 0)))
    window.sheets.tabs.setCurrentIndex(1)
    sheet = window.document.sheets[0]
    v = sheet.viewports()[0]
    window.sheets.on_empty_double_click(QPointF(500, 400))
    assert window.sheets.active_viewport_id == v.id
    assert window.canvas.navigator.zoom(0.5, QPointF(500, 400))
    assert window.canvas.navigator.zoom(0.5, QPointF(500, 400))
    new = sheet.entities.get(v.id)
    assert new.scale == pytest.approx(0.25)
    assert new.sheet_to_model(Point(500, 400)).x == pytest.approx(
        v.sheet_to_model(Point(500, 400)).x
    )
    assert window.undo_stack.count() == 1  # merged
    window.canvas.navigator.pan(QPointF(10, 0))
    assert sheet.entities.get(v.id).center.x == pytest.approx(new.center.x + 40)
    window.sheets.deactivate_viewport()
    assert window.canvas.navigator is None


def test_locked_viewport_not_activated(window):
    window.sheets.tabs.setCurrentIndex(1)
    sheet = window.document.sheets[0]
    from dataclasses import replace

    v = sheet.viewports()[0]
    sheet.entities.replace(replace(v, locked=True))
    window.sheets.on_empty_double_click(QPointF(500, 400))
    assert window.sheets.active_viewport_id is None


def test_fit_model_extents(window):
    window.document.model_space.add(Line(id="m", p1=Point(0, 0), p2=Point(2000, 1000)))
    window.sheets.tabs.setCurrentIndex(1)
    v = window.document.sheets[0].viewports()[0]
    window.sheets.fit_model_extents(v.id)
    new = window.document.sheets[0].entities.get(v.id)
    assert new.scale < 1 and new.center.x == pytest.approx(1000, abs=1)
    a, b = new.model_rect()
    assert a.x <= 0 and b.x >= 2000


def test_change_format_and_fields(window, monkeypatch):
    window.sheets.tabs.setCurrentIndex(1)
    from sldgridy.model.paper import Orientation

    monkeypatch.setattr(FormatDialog, "exec", lambda self: 1)
    monkeypatch.setattr(
        FormatDialog, "values", lambda self: ("A3", Orientation.PORTRAIT, "Schriftfeld")
    )
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.warning", lambda *a, **k: None)
    window.sheets.change_format()
    sheet = window.document.sheets[0]
    assert (sheet.paper, sheet.orientation) == ("A3", Orientation.PORTRAIT)
    paper = window.space.extra["paper"]
    assert paper.boundingRect().width() == pytest.approx(297 + 6)
    monkeypatch.setattr(FieldsDialog, "exec", lambda self: 1)
    monkeypatch.setattr(FieldsDialog, "properties", lambda self: {"FIRMA": "FS"})
    monkeypatch.setattr(FieldsDialog, "fields", lambda self: {"TITEL": "Plan"})
    window.sheets.edit_fields()
    assert window.document.properties == {"FIRMA": "FS"}
    assert sheet.fields == {"TITEL": "Plan"}
    window.act_undo.trigger()
    assert window.document.properties == {} and sheet.fields == {}


def test_tab_move_reorders_sheets(window, monkeypatch):
    answer_new_page(window, monkeypatch)
    window.sheets.act_new.trigger()
    names = [s.name for s in window.document.sheets]
    window.sheets._on_tab_moved(2, 1)
    assert [s.name for s in window.document.sheets] == list(reversed(names))


def test_shipped_templates_create_sheets(window):
    paths = sorted(system_template_dir().glob("*.sldgframe"))
    assert len(paths) == 10
    window.sheets.add_from_template(paths[0])
    assert len(window.document.sheets) == 2
    new = window.sheets.current_sheet()
    assert new.viewports() and new.title_block == "Schriftfeld"


def test_viewport_tool(window):
    window.sheets.tabs.setCurrentIndex(1)
    window.canvas.fit_rect(QRectF(0, 0, 400, 300))
    window.sheets.act_viewport.trigger()
    for x, y in ((50, 50), (150, 120)):
        pos = window.canvas.map_from_scene_f(QPointF(x, y)).toPoint()
        QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    vps = [e for e in window.document.sheets[0].entities if isinstance(e, Viewport)]
    assert len(vps) == 2


def test_viewport_corner_fields_and_origin_button(window):
    from PyQt6.QtWidgets import QDoubleSpinBox, QPushButton

    window.sheets.tabs.setCurrentIndex(1)
    sheet = window.document.sheets[0]
    v = sheet.viewports()[0]
    window._sync.item(v.id).setSelected(True)
    box = window.properties_dock.widget()
    spins = box.findChildren(QDoubleSpinBox)
    assert len(spins) == 2
    assert spins[0].value() == pytest.approx(v.model_rect()[0].x, abs=0.01)
    [b for b in box.findChildren(QPushButton) if "0,0" in b.text()][0].click()
    corner = sheet.entities.get(v.id).model_rect()[0]
    assert corner.x == pytest.approx(0) and corner.y == pytest.approx(0)
    assert sheet.entities.get(v.id).scale == v.scale  # only the position changes
    spins = window.properties_dock.widget().findChildren(QDoubleSpinBox)
    spins[1].setValue(-50)
    corner = sheet.entities.get(v.id).model_rect()[0]
    assert corner.x == pytest.approx(0) and corner.y == pytest.approx(-50)
    window.act_undo.trigger()
    window.act_undo.trigger()
    assert sheet.entities.get(v.id).center == v.center


def test_align_model_on_sheet(window, qapp):
    sheets = window.sheets
    sheet = window.document.sheets[0]
    rect = sheets.sheet_model_rect(sheet)
    assert rect is not None and not rect.isEmpty()
    window.canvas.set_view(5.0, QPointF(5000, 5000))  # model looks elsewhere
    sheets.tabs.setCurrentIndex(1)
    sheets.align_model_on(sheet.id)
    qapp.processEvents()
    assert window.space.kind == MODEL and sheets.tabs.currentIndex() == 0
    view = window.canvas.viewport().rect()
    for corner in (rect.topLeft(), rect.bottomRight()):
        assert view.contains(window.canvas.map_from_scene_f(corner).toPoint())
    # Fills the view: a larger rectangle would not fit any more.
    a = window.canvas.map_from_scene_f(rect.topLeft())
    b = window.canvas.map_from_scene_f(rect.bottomRight())
    assert max((b.x() - a.x()) / view.width(), (b.y() - a.y()) / view.height()) > 0.9
    menu = sheets.align_menu
    sheets._fill_align_menu(menu)
    assert [a.text() for a in menu.actions()] == ["Ausrichten auf Blatt 1"]
