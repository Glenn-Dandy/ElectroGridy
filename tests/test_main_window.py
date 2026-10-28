import pytest
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt
from PyQt6.QtTest import QTest

from factories import sample_entities
from sldgridy.fileio.files import load_document
from sldgridy.fileio.json_format import document_to_dict
from sldgridy.model.document import Document
from sldgridy.model.geometry import Point
from sldgridy.ui.main_window import MainWindow


@pytest.fixture
def window(qapp):
    QSettings().clear()  # every test starts with default snap, ortho and grid
    w = MainWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.undo_stack.setClean()  # no save prompt on close
    w.close()


def test_status_bar_shows_cursor_in_mm_with_german_decimals(window):
    window.canvas.cursor_moved.emit(QPointF(12.5, -3.25))
    assert window.lbl_position.text() == "X: 12,50 mm   Y: -3,25 mm"


def test_status_bar_shows_zoom(window):
    window.canvas.set_zoom(2.0)
    assert window.lbl_zoom.text() == "Zoom: 200 %"


def test_zoom_in_the_status_bar_can_be_chosen(window, monkeypatch):
    window.lbl_zoom.menu().aboutToShow.emit()
    actions = {a.text(): a for a in window.lbl_zoom.menu().actions()}
    actions["50 %"].trigger()
    assert window.canvas.zoom() == pytest.approx(0.5)
    monkeypatch.setattr("PyQt6.QtWidgets.QInputDialog.getDouble", lambda *a, **k: (150.0, True))
    actions["Wert eingeben …"].trigger()
    assert window.lbl_zoom.text() == "Zoom: 150 %"


def test_grid_action_toggles_canvas(window):
    window.act_grid.setChecked(False)
    assert not window.canvas.grid_visible()
    window.act_grid.setChecked(True)
    assert window.canvas.grid_visible()


def test_new_window_has_document_with_one_sheet(window):
    assert [s.name for s in window.document.sheets] == ["Blatt 1"]


def click(window, x, y, button=Qt.MouseButton.LeftButton):
    canvas = window.canvas
    QTest.mouseClick(
        canvas.viewport(), button, pos=canvas.map_from_scene_f(QPointF(x, y)).toPoint()
    )


def test_draw_line_with_mouse_snaps_and_undoes(window):
    window.canvas.fit_rect(QRectF(0, 0, 100, 100))
    window.act_line.trigger()
    click(window, 10.4, 10.2)
    click(window, 40.6, 9.9)
    click(window, 0, 0, Qt.MouseButton.RightButton)
    (line,) = list(window.document.model_space)
    assert (line.p1, line.p2) == (Point(10, 10), Point(40, 10))
    assert window.isWindowModified()
    window.act_undo.trigger()
    assert list(window.document.model_space) == []
    window.act_redo.trigger()
    assert len(window.document.model_space) == 1


def test_ortho_constrains_second_point(window):
    window.canvas.fit_rect(QRectF(0, 0, 100, 100))
    window.act_ortho.setChecked(True)
    window.act_line.trigger()
    click(window, 10, 10)
    click(window, 50, 17.5)
    window.tools.cancel()
    (line,) = list(window.document.model_space)
    assert line.p2 == Point(50, 10)


def test_delete_and_select_all(window):
    for e in sample_entities():
        window.document.model_space.add(e)
    window.act_select_all.trigger()
    window.act_delete.trigger()
    assert len(window.document.model_space) == 0
    window.act_undo.trigger()
    assert len(window.document.model_space) == len(sample_entities())


def test_save_and_open_roundtrip(window, tmp_path):
    for e in sample_entities():
        window.document.model_space.add(e)
    path = tmp_path / "anlage.sldg"
    assert window.save_to(path)
    assert not window.isWindowModified()
    assert window.windowTitle() == "anlage.sldg[*] (Übersichtsschaltplan) - SLDGridy"
    assert window.recent_files()[0] == (path.resolve(), "sld")
    window._set_document(Document.new("Blatt 1"), None)
    assert len(window.document.model_space) == 0
    assert window.open_path(path)
    assert document_to_dict(window.document) == document_to_dict(load_document(path))
    from sldgridy.view.items import EntityItem

    assert len([i for i in window.scene.items() if isinstance(i, EntityItem)]) == len(
        sample_entities()
    )


def test_mouse_side_buttons_undo_and_redo(window):
    from sldgridy.commands.entities import AddEntitiesCommand
    from sldgridy.model.entities import Line

    ms = window.document.model_space
    window.push(AddEntitiesCommand(ms, [Line(id="x", p1=Point(0, 0), p2=Point(5, 0))], "Linie"))
    assert "x" in ms
    for widget in (window.canvas.viewport(), window.library_dock.list.viewport()):
        QTest.mouseClick(widget, Qt.MouseButton.BackButton)
        assert "x" not in ms
        QTest.mouseClick(widget, Qt.MouseButton.ForwardButton)
        assert "x" in ms


def test_layer_cache_is_off_on_first_start_and_can_be_switched_on(window):
    assert not window.act_layer_cache.isChecked()
    assert not window.canvas.layer_cache_enabled
    plain = window.canvas.viewport().grab()
    window.act_layer_cache.setChecked(True)
    assert window.canvas.layer_cache_enabled
    cached = window.canvas.viewport().grab()
    assert cached.size() == plain.size()


def test_program_settings_have_their_own_menu(window):
    titles = [a.text().replace("&", "") for a in window.menuBar().actions()]
    assert titles[:3] == ["Datei", "Bearbeiten", "Einstellungen"]
    items = [a.text().replace("&", "") for a in window.settings_menu.actions()]
    for wanted in (
        "Schnelle Darstellung",
        "Sprache / Language",
        "Fenstersystem",
        "Beim Öffnen zeigen",
    ):
        assert wanted in items
    view = [a.text().replace("&", "") for a in window.view_menu.actions()]
    assert "Schnelle Darstellung" not in view


def test_opening_view_modes(window, tmp_path, qapp):
    from PyQt6.QtCore import QPointF, QSettings

    from sldgridy.fileio.files import save_document
    from sldgridy.model.entities import Line
    from sldgridy.ui.main_window import OPEN_EXTENTS, OPEN_LAST, OPEN_ORIGIN, OPEN_VIEW_KEY

    doc = Document.new("Blatt 1")
    doc.model_space.add(Line(id="far", p1=Point(1000, 1000), p2=Point(1100, 1050)))
    path = tmp_path / "ansicht.sldg"
    save_document(doc, path)
    canvas = window.canvas

    def center():
        return canvas.map_to_scene_f(QPointF(canvas.viewport().rect().center()))

    QSettings().setValue(OPEN_VIEW_KEY, OPEN_EXTENTS)
    assert window.open_path(path)
    c = center()
    assert 950 < c.x() < 1150 and 950 < c.y() < 1100  # the line is in the middle

    # Last view: zoom and centre come back after closing and reopening.
    QSettings().setValue(OPEN_VIEW_KEY, OPEN_LAST)
    canvas.set_view(2.0, QPointF(300, 200))
    window._set_document(Document.new("Blatt 1"), None)
    assert window.open_path(path)
    assert canvas.zoom() == pytest.approx(2.0)
    assert center().x() == pytest.approx(300, abs=1) and center().y() == pytest.approx(200, abs=1)

    # Sheet 1 from the origin: the first sheet's area, top left at 0,0.
    QSettings().setValue(OPEN_VIEW_KEY, OPEN_ORIGIN)
    assert window.open_path(path)
    origin = canvas.map_from_scene_f(QPointF(0, 0))  # 0,0 sits in the top left corner
    assert origin.x() == pytest.approx(12, abs=1) and origin.y() == pytest.approx(12, abs=1)


def test_opening_view_follows_window_size_until_the_user_acts(window, tmp_path, qapp):
    from PyQt6.QtCore import QPointF, QSettings

    from sldgridy.fileio.files import save_document
    from sldgridy.model.entities import Line
    from sldgridy.ui.main_window import OPEN_EXTENTS, OPEN_VIEW_KEY

    doc = Document.new("Blatt 1")
    doc.model_space.add(Line(id="l", p1=Point(500, 500), p2=Point(700, 600)))
    path = tmp_path / "gross.sldg"
    save_document(doc, path)
    QSettings().setValue(OPEN_VIEW_KEY, OPEN_EXTENTS)
    window.resize(700, 500)
    qapp.processEvents()
    assert window.open_path(path)
    window.resize(1400, 1000)  # e.g. the window gets maximized afterwards
    qapp.processEvents()
    canvas = window.canvas
    c = canvas.map_to_scene_f(QPointF(canvas.viewport().rect().center()))
    assert c.x() == pytest.approx(600, abs=5) and c.y() == pytest.approx(550, abs=5)
    # Once the user zooms, a later resize keeps the user's view.
    QTest.keyClick(canvas, Qt.Key.Key_Shift)
    canvas.set_view(3.0, QPointF(0, 0))
    window.resize(1200, 900)
    qapp.processEvents()
    assert canvas.zoom() == pytest.approx(3.0)


def test_help_menu_starts_with_readme(window):
    from sldgridy.ui.readme_dialog import ReadmeDialog, readme_markdown

    help_menu = [a.menu() for a in window.menuBar().actions() if a.text() == "&Hilfe"][0]
    first = [a for a in help_menu.actions() if not a.isSeparator()][0]
    assert first is window.act_readme
    text = readme_markdown()
    assert "SLDGridy" in text and "[![" not in text  # no remote badges offline
    assert "application/x-sldgridy" in text  # snap double-click setup is documented
    dialog = ReadmeDialog(window)
    assert "Installation" in dialog.browser.toPlainText()


def test_readme_links_jump_to_headings(window):
    from sldgridy.ui.readme_dialog import ReadmeDialog

    dialog = ReadmeDialog(window)
    assert dialog.jump_to_heading("deutsch")
    assert dialog.browser.textCursor().block().text() == "Deutsch"
    assert not dialog.jump_to_heading("gibt-es-nicht")


def test_document_kinds_show_their_tools_and_libraries(window):
    from sldgridy.model.document import DOC_DRAWING, DOC_PROJECT
    from sldgridy.ui.main_window import WORKSPACE_DRAWING, WORKSPACE_SLD

    def titles():  # shipped ones; other tests may leave user libraries behind
        libs = window.library_dock.visible_libraries().values()
        return [lib.title for lib in libs if lib.shipped]

    # Overview diagram: wires and bus bars, SLD symbols only, no project menu.
    assert window.workspace == WORKSPACE_SLD and window.document.kind == "sld"
    assert window.act_wire.isVisible() and window.act_busbar.isVisible()
    assert not window.act_interruption.isVisible() and not window.act_rails.isVisible()
    assert not window.act_module_field.isVisible()
    assert not window.project_menu.menuAction().isVisible()
    assert titles() and all(t.startswith("SLD:") for t in titles())
    assert window.sheets.tabs.tabText(0) == "Modell"
    # Drawing: no wiring, the roof layout instead, no circuit symbols.
    window.new_document(DOC_DRAWING)
    assert window.workspace == WORKSPACE_DRAWING
    assert not window.act_wire.isVisible() and window.act_module_field.isVisible()
    assert window.act_dimension.isVisible()
    assert not any("DIN EN 60617" in t for t in titles())
    window.canvas.set_snap_spacing(50)  # remembered for drawings
    # Project: numbered pages without model, SLD before MLD symbols, MLD chosen.
    window.new_document(DOC_PROJECT)
    assert window.canvas.snap_spacing == 2.5
    assert window.act_interruption.isVisible() and window.act_rails.isVisible()
    assert window.project_menu.menuAction().isVisible()
    assert [t[:4] for t in titles()] == ["SLD:", "SLD:", "MLD:"]
    dock = window.library_dock
    assert dock.source.currentText().startswith("MLD:")
    tabs = [window.sheets.tabs.tabText(i) for i in range(window.sheets.tabs.count())]
    assert tabs == ["1 Deckblatt", "2 Stromlaufplan"]
    assert window.sheets.current_sheet() is window.document.sheets[1]
    assert "(Schaltplanprojekt)" in window.windowTitle()
    window.new_document(DOC_DRAWING)
    assert window.canvas.snap_spacing == 50


def test_library_categories_name_their_group_in_a_project(window):
    from sldgridy.model.document import DOC_PROJECT

    window.new_document(DOC_PROJECT)
    dock = window.library_dock
    dock.source.setCurrentIndex(0)  # all libraries
    texts = [dock.category.itemText(i) for i in range(dock.category.count())]
    assert "SLD: Schalten und Schützen" in texts and "MLD: Schalten und Schützen" in texts
    assert texts.index("SLD: Schalten und Schützen") < texts.index("MLD: Schalten und Schützen")
    assert not any("Klemmen" in t for t in texts)  # terminals are set on wires
    dock.category.setCurrentIndex(texts.index("MLD: Steuerstromkreis"))
    shown = [dock.list.item(i).text() for i in range(dock.list.count())
             if not dock.list.item(i).isHidden()]  # fmt: skip
    assert "Schließer" in shown and "Leitungsschutzschalter" not in shown


def test_start_dialog_creates_the_chosen_kind(window, monkeypatch):
    from sldgridy.ui import main_window as mw

    class Fake:
        DialogCode = mw.StartDialog.DialogCode

        def __init__(self, recent, parent):
            self.choice = ("new", "project")

        def exec(self):
            return self.DialogCode.Accepted

    monkeypatch.setattr(mw, "StartDialog", Fake)
    window.show_start_dialog()
    assert window.document.is_project


def test_grid_and_snap_typed_in_the_status_bar_menu(window):
    menu = window.grid_menu
    menu.sync()
    menu.grid_spin.setValue(10)
    menu.snap_spin.setValue(1)
    assert window.canvas.grid_spacing() == 10 and window.canvas.snap_spacing == 1
    window.canvas.set_snap_spacing(2.5)
    menu.sync()
    assert menu.snap_spin.value() == 2.5


def test_layers_are_separate_per_workspace(window):
    from sldgridy.model.layers import Layer
    from sldgridy.ui.main_window import WORKSPACE_DRAWING, WORKSPACE_SLD

    doc = window.document
    doc.insert_layer(len(doc.layers), Layer("Kabel", workspace=WORKSPACE_SLD))
    doc.insert_layer(len(doc.layers), Layer("Dachfläche", workspace=WORKSPACE_DRAWING))
    window.set_current_layer("Kabel")

    def listed():
        dock = window.layers_dock
        return [dock.table.item(r, 1).text() for r in range(dock.table.rowCount())]

    window.layers_dock.rebuild()
    assert listed() == ["0", "Kabel"]
    window.set_workspace(WORKSPACE_DRAWING)
    assert listed() == ["0", "Dachfläche"]
    assert window.current_layer == "0"  # "Kabel" is not a drawing layer
    window.layers_dock.add_layer()
    new = doc.layers[-1]
    assert new.workspace == WORKSPACE_DRAWING and new.name in listed()


def test_module_field_fills_a_roof_with_a_chimney(window):
    from sldgridy.model.document import DOC_DRAWING
    from sldgridy.model.entities import BlockReference, Rectangle
    from sldgridy.tools.pv import ModuleFieldTool, ModuleSpec

    window.new_document(DOC_DRAWING)
    assert window.act_module_field.isVisible() and not window.act_wire.isVisible()
    ms = window.document.model_space
    ms.add(Rectangle(id="roof", p1=Point(0, 0), p2=Point(8000, 5000)))
    spec = ModuleSpec(power=445)
    window.start_tool(lambda ctx: ModuleFieldTool(ctx, spec))
    window.tools.pick(Point(4000, 2500))
    modules = [e for e in ms if isinstance(e, BlockReference)]
    assert len(modules) == 12
    assert spec.block_name in window.document.blocks
    assert "12" in window.statusBar().currentMessage()
    window.act_undo.trigger()  # one step removes modules and the module block
    assert not [e for e in ms if isinstance(e, BlockReference)]
    assert spec.block_name not in window.document.blocks
    ms.add(Rectangle(id="chimney", p1=Point(3800, 1800), p2=Point(4400, 2400)))
    window.start_tool(lambda ctx: ModuleFieldTool(ctx, spec))
    window.tools.pick(Point(1000, 1000))
    assert 0 < len([e for e in ms if isinstance(e, BlockReference)]) < 12


def test_module_field_with_a_number_of_modules(window):
    from sldgridy.model.entities import BlockReference, Rectangle
    from sldgridy.tools.pv import ModuleFieldTool, ModuleSpec

    ms = window.document.model_space
    ms.add(Rectangle(id="roof", p1=Point(0, 0), p2=Point(8000, 5000)))
    window.start_tool(lambda ctx: ModuleFieldTool(ctx, ModuleSpec(power=400, count=7)))
    window.tools.pick(Point(4000, 2500))
    assert len([e for e in ms if isinstance(e, BlockReference)]) == 7
    assert "7 Module, 2,80 kWp" in window.statusBar().currentMessage()
    window.act_undo.trigger()
    window.start_tool(lambda ctx: ModuleFieldTool(ctx, ModuleSpec(power=400, count=20)))
    window.tools.pick(Point(4000, 2500))
    assert len([e for e in ms if isinstance(e, BlockReference)]) == 12
    assert "Nur 12 von 20" in window.statusBar().currentMessage()


def test_deleting_many_selected_objects_refreshes_the_dock_once(window):
    from sldgridy.model.entities import Line as LineEntity

    ms = window.document.model_space
    for i in range(60):
        ms.add(LineEntity(id=f"l{i}", p1=Point(i, 0), p2=Point(i, 10)))
    window.select_all()
    calls = []
    original = window.properties_dock.refresh
    window.properties_dock.refresh = lambda: (calls.append(1), original())[1]
    window.delete_selection()
    assert len(ms) == 0 and len(calls) <= 2  # not once per object
    window.act_undo.trigger()
    assert len(ms) == 60


def test_every_start_begins_with_an_overview_diagram(qapp):
    from sldgridy.model.document import DOC_DRAWING
    from sldgridy.ui.main_window import WORKSPACE_SLD, MainWindow

    first = MainWindow()
    first.new_document(DOC_DRAWING)
    first.undo_stack.setClean()
    first.close()
    second = MainWindow()
    assert second.workspace == WORKSPACE_SLD and second.document.kind == "sld"
    second.undo_stack.setClean()
    second.close()
