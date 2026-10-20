"""Main application window."""

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path

from PyQt6.QtCore import (
    QElapsedTimer,
    QEvent,
    QEventLoop,
    QPoint,
    QPointF,
    QRectF,
    QSettings,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QCursor,
    QKeySequence,
    QUndoCommand,
    QUndoGroup,
    QUndoStack,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsScene,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sldgridy import i18n, platform_choice, project
from sldgridy.commands.entities import RemoveEntitiesCommand, ReplaceEntitiesCommand
from sldgridy.fileio.files import DRAWING_SUFFIX, load_document, save_document
from sldgridy.fileio.json_format import FileFormatError
from sldgridy.i18n import ui_locale
from sldgridy.model.blocks import BlockDefinition, BlockError, expand, world_connections
from sldgridy.model.container import EntityContainer
from sldgridy.model.devices import crossref_texts, crossrefs
from sldgridy.model.dimensions import dimension_geometry, format_value, measured_text, scale_at
from sldgridy.model.document import Document
from sldgridy.model.entities import (
    BlockReference,
    Busbar,
    ConnectionPoint,
    Dimension,
    Entity,
    InterruptionPoint,
    Text,
    Wire,
)
from sldgridy.model.geometry import Point
from sldgridy.model.interruptions import (
    interruption_geometry,
    interruption_targets,
    partner,
    unpaired_names,
)
from sldgridy.model.layers import DEFAULT_LAYER
from sldgridy.model.snap import ALL_MODES, SnapHit, SnapMode
from sldgridy.model.wires import label_anchor, label_text, project_on_path
from sldgridy.printing.output import export_pdf, export_png, export_svg
from sldgridy.tools.controller import ToolController, ToolFactory
from sldgridy.tools.coord_input import CoordinateError, parse_coordinate
from sldgridy.tools.draw import (
    AngularDimensionTool,
    ArcTool,
    BusbarTool,
    CircleTool,
    DimensionTool,
    InterruptionTool,
    LineTool,
    PolylineTool,
    RectangleTool,
    TextTool,
    WireTool,
)
from sldgridy.tools.edit import (
    CopyTool,
    MirrorTool,
    MoveTool,
    PasteTool,
    RotateFreeTool,
    RotateTool,
    ScaleTool,
)
from sldgridy.ui import clipboard
from sldgridy.ui.about_dialog import AboutDialog, app_icon, issue_url, open_url
from sldgridy.ui.autosave import AutoSaver, orphaned_backups, remove_backup
from sldgridy.ui.block_controller import BlockController
from sldgridy.ui.command_line import CommandLine
from sldgridy.ui.devices_dock import DevicesDock
from sldgridy.ui.dock_title import install_title_bar
from sldgridy.ui.export_dialog import PDF, PNG, SVG, ExportDialog
from sldgridy.ui.grid_dialog import GridDialog
from sldgridy.ui.grid_menu import GridMenu
from sldgridy.ui.layers_dock import LayersDock
from sldgridy.ui.library_dock import LibraryDock
from sldgridy.ui.osnap_dialog import OsnapDialog
from sldgridy.ui.osnap_menu import HoverMenuButton, OsnapMenu
from sldgridy.ui.pages_dock import PagesDock
from sldgridy.ui.point_menu import point_actions
from sldgridy.ui.print_dialog import PrintDialog
from sldgridy.ui.properties_dock import PropertiesDock
from sldgridy.ui.sheet_controller import SheetController
from sldgridy.ui.space import BLOCK, MODEL, SHEET, Space
from sldgridy.ui.styles import MIXED, HeightCombo
from sldgridy.ui.text_dialog import TextDialog
from sldgridy.view.canvas import BACKGROUND_COLOR, EMPTY_EXTENTS, Canvas, select_items
from sldgridy.view.display import title_labels
from sldgridy.view.items import EntityItem
from sldgridy.view.junctions import JunctionItem
from sldgridy.view.render import Style
from sldgridy.view.scene_sync import SceneSync

APP_NAME = "SLDGridy"


def wait_for_mouse_release() -> None:
    """Before a popup opened from a mouse press: let go of the button first, else the
    release lands on the item under the cursor and picks it at once (seen on Wayland)."""
    timer = QElapsedTimer()
    timer.start()
    while QApplication.mouseButtons() != Qt.MouseButton.NoButton and timer.elapsed() < 3000:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


WORKSPACE_SLD, WORKSPACE_DRAWING, WORKSPACE_MLD = "sld", "drawing", "mld"
# Grid and snap spacing a workspace starts with (mm); changes are remembered per workspace.
WORKSPACE_GRID = {
    WORKSPACE_SLD: (5.0, 2.5),
    WORKSPACE_DRAWING: (5.0, 2.5),
    WORKSPACE_MLD: (5.0, 2.5),
}

OPEN_VIEW_KEY = "view/on_open"
OPEN_EXTENTS, OPEN_LAST, OPEN_ORIGIN = "extents", "last", "origin"
LAST_VIEW_GROUP = "last_views"


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._locale = ui_locale()
        self.document = Document.new(self.tr("Blatt 1"), title_labels())
        self._interruptions: dict[str, tuple[str, str]] | None = None
        self._crossrefs: dict[str, list[str]] | None = None
        self._interruption_refresh_pending = False
        self._watched_pages: dict[int, EntityContainer] = {}
        self.file_path: Path | None = None
        self.current_layer = DEFAULT_LAYER

        self.undo_group = QUndoGroup(self)
        self.undo_stack = QUndoStack(self)
        self.undo_group.addStack(self.undo_stack)
        self.undo_group.setActiveStack(self.undo_stack)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self.undo_group.indexChanged.connect(self._on_undo_index_changed)
        self.autosave = AutoSaver(self)

        self.canvas = Canvas(QGraphicsScene(self), parent=self)
        self.canvas.resolve_style = self._resolve_style
        self.canvas.expand = self._expand
        self.canvas.snap_decompose = self._decompose
        self.canvas.snap_extra = self._snap_extra
        self.command_line = CommandLine(self)
        self.central_layout = QVBoxLayout()
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        self.central_layout.setSpacing(0)
        self.central_layout.addWidget(self.canvas, 1)
        self.central_layout.addWidget(self.command_line)
        central = QWidget(self)
        central.setLayout(self.central_layout)
        self.setCentralWidget(central)

        self.tools = ToolController(self, parent=self)
        self.canvas.controller = self.tools
        self.tools.changed.connect(self._on_tool_changed)

        self.model_view = self._make_space(MODEL, self.document.model_space, self.undo_stack)
        self.space = self.model_view
        self.canvas.set_scene(self.space.scene)
        self._subscribe_document()

        self.blocks = BlockController(self)
        self.sheets = SheetController(self)
        self.central_layout.insertWidget(1, self.sheets.tabs)
        self.model_view.extra["overlay"] = self.sheets.model_overlay
        self.canvas.extra_overlay = self.sheets.model_overlay

        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_docks()
        self._create_status_bar()

        self.canvas.cursor_moved.connect(self._show_cursor_position)
        self.canvas.zoom_changed.connect(self._show_zoom)
        self.canvas.entity_double_clicked.connect(self._edit_entity)
        self.canvas.text_typed.connect(self.command_line.start_typing)
        self.canvas.block_dropped.connect(self.blocks.on_drop)
        # Side buttons of the mouse anywhere in this window: back undoes, forward redoes.
        QApplication.instance().installEventFilter(self)
        self.canvas.drag_preview = self.blocks.drag_preview
        self.canvas.empty_double_clicked.connect(self.sheets.on_empty_double_click)
        self.canvas.point_menu_requested.connect(self._show_point_menu)
        self.canvas.osnap_menu_requested.connect(lambda pos: self.osnap_menu.exec(pos))
        self.sheets.rebuild_tabs()
        self.command_line.submitted.connect(self._on_command_input)
        self.command_line.cancelled.connect(self._on_command_cancel)

        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self._restore_settings()
        self._update_title()
        self._show_zoom(self.canvas.zoom())
        self._on_tool_changed()

    # -- spaces -------------------------------------------------------------

    @property
    def scene(self) -> QGraphicsScene:
        return self.space.scene

    @property
    def _sync(self) -> SceneSync:
        return self.space.sync

    def _make_space(
        self,
        kind: str,
        container: EntityContainer,
        stack: QUndoStack,
        item_factory=None,
        blocks: Mapping[str, BlockDefinition] | None = None,
    ) -> Space:
        """``blocks`` resolves references in this space; None means the drawing's blocks."""
        scene = QGraphicsScene(self)
        expand = partial(self.expand_with, blocks)
        sync = SceneSync(
            scene, container, self._resolve_style, self._layer_state, expand, item_factory
        )
        scene.selectionChanged.connect(self._on_selection_changed)
        junction_item = JunctionItem(
            container, self._resolve_style, lambda e: self._layer_state(e)[0]
        )
        scene.addItem(junction_item)
        space = Space(kind, container, scene, sync, stack)
        if blocks is not None:
            space.extra["blocks"] = blocks
        space.extra["junctions"] = junction_item
        return space

    def spaces(self) -> list[Space]:
        result = [self.model_view]
        editor = self.blocks.editor_space if hasattr(self, "blocks") else None
        if editor is not None:
            result.append(editor)
        if hasattr(self, "sheets"):
            result += self.sheets.all_spaces()
        return result

    def activate_space(self, space: Space) -> None:
        if space is self.space:
            return
        self.tools.cancel()
        self.sheets.deactivate_viewport()
        self.space.view = (
            self.canvas.transform(),
            self.canvas.map_to_scene_f(QPointF(self.canvas.viewport().rect().center())),
        )
        self.space = space
        self.canvas.set_scene(space.scene)
        self.canvas.extra_overlay = space.extra.get("overlay")
        self.canvas.set_background(
            space.extra.get("background", BACKGROUND_COLOR), show_origin=space.kind != SHEET
        )
        self.sheets.select_tab_for(space)
        if space.stack not in self.undo_group.stacks():
            self.undo_group.addStack(space.stack)
        self.undo_group.setActiveStack(space.stack)
        if space.view is not None:
            transform, center = space.view
            self.canvas.setTransform(transform)
            self.canvas.center_on_point(center)
            self._show_zoom(self.canvas.zoom())
        else:
            self.canvas.zoom_extents()
        self._on_selection_changed()
        self._update_title()

    def _drop_space(self, space: Space) -> None:
        space.detach()
        space.extra["junctions"].detach()
        if space.stack in self.undo_group.stacks() and space.stack is not self.undo_stack:
            self.undo_group.removeStack(space.stack)
        space.scene.deleteLater()

    # -- ToolContext --------------------------------------------------------

    @property
    def container(self) -> EntityContainer:
        return self.space.container

    def set_current_layer(self, name: str) -> None:
        if not self.document.has_layer(name):
            name = DEFAULT_LAYER
        self.current_layer = name
        self.lbl_layer.setText(self.tr("Ebene: {name}").format(name=name))
        self.layers_dock.rebuild()

    @property
    def block_definitions(self) -> Mapping[str, BlockDefinition]:
        """Blocks references of the active space resolve to."""
        space = getattr(self, "space", None)
        if space is not None and "blocks" in space.extra:
            return space.extra["blocks"]
        return self.document.blocks

    @property
    def active_stack(self) -> QUndoStack:
        return self.space.stack

    def push(self, command: QUndoCommand) -> None:
        self.active_stack.push(command)

    def begin_macro(self, text: str) -> None:
        self.active_stack.beginMacro(text)

    def end_macro(self) -> None:
        self.active_stack.endMacro()

    def selected_ids(self) -> list[str]:
        items = [i for i in self.scene.selectedItems() if isinstance(i, EntityItem)]
        items.sort(key=lambda i: i.zValue())
        return [i.entity_id for i in items]

    def ask_text(self, text: str = "", height: float | None = None) -> tuple[str, float] | None:
        dialog = TextDialog(self, text, height)
        if dialog.exec() != TextDialog.DialogCode.Accepted:
            return None
        return dialog.text(), dialog.text_height()

    def message(self, text: str) -> None:
        self.statusBar().showMessage(text, 5000)

    def ask_interruption_name(self) -> str | None:
        """Name of a new interruption point; names placed only once so far come first
        (usually the partner that is being placed)."""
        suggestions = unpaired_names(self.document)
        name, ok = QInputDialog.getItem(
            self,
            self.tr("Unterbrechungspunkt"),
            self.tr("Name (z. B. L1, N, PE, -X1:3):"),
            suggestions or [""],
            0,
            True,
        )
        name = name.strip()
        return name if ok and name else None

    def go_to_occurrence(self, occ) -> None:
        """Show where a device occurrence sits: circuit diagram, sheet or page."""
        if occ.where == "page":
            self.set_workspace(WORKSPACE_MLD)
            self.sheets.show_sheet(occ.layout_id)
        else:
            if self.workspace == WORKSPACE_MLD:
                self.set_workspace(WORKSPACE_SLD)
            if occ.where == "model":
                self.activate_space(self.model_view)
            else:
                self.sheets.show_sheet(occ.layout_id)
        if occ.entity_id in self.container:
            self.scene.clearSelection()
            self._sync.item(occ.entity_id).setSelected(True)
            self.canvas.centerOn(QPointF(occ.position.x, occ.position.y))

    def go_to_partner(self, point_id: str) -> bool:
        """Show the page of the interruption point's partner, centred and selected."""
        found = partner(self.document, point_id)
        if found is None:
            return False
        page_id, point = found
        self.sheets.show_sheet(page_id)
        self.scene.clearSelection()
        self._sync.item(point.id).setSelected(True)
        self.canvas.centerOn(QPointF(point.position.x, point.position.y))
        return True

    def ask_choice(self, key: str, options: list[str]) -> int | None:
        """Small menu at the mouse; the last choice for ``key`` is preselected."""
        settings = QSettings()
        last = settings.value(f"choice/{key}", 0, type=int)
        menu = QMenu(self)
        actions = [menu.addAction(text) for text in options]
        if 0 <= last < len(actions):
            menu.setActiveAction(actions[last])
        wait_for_mouse_release()
        chosen = menu.exec(QCursor.pos() + QPoint(8, 8))
        if chosen not in actions:
            return None
        index = actions.index(chosen)
        settings.setValue(f"choice/{key}", index)
        return index

    # -- setup --------------------------------------------------------------

    def _action(self, text: str, slot, shortcut=None, icon_text: str | None = None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if icon_text is not None:
            action.setIconText(icon_text)
        action.triggered.connect(slot)
        return action

    def _tool_action(self, text: str, factory: ToolFactory) -> QAction:
        return self._action(text, lambda: self.start_tool(factory))

    def _create_actions(self) -> None:
        sk = QKeySequence.StandardKey
        self.act_new = self._action(self.tr("&Neu"), self.new_document, sk.New)
        self.act_open = self._action(self.tr("Ö&ffnen …"), self.open_document, sk.Open)
        self.act_save = self._action(self.tr("&Speichern"), self.save, sk.Save)
        self.act_save_as = self._action(self.tr("Speichern &unter …"), self.save_as, "Ctrl+Shift+S")
        self.act_quit = self._action(self.tr("&Beenden"), self.close, sk.Quit)
        self.act_print = self._action(self.tr("&Drucken …"), self.print_document, sk.Print)
        self.act_export_pdf = self._action(self.tr("&PDF …"), lambda: self.export(PDF))
        self.act_export_svg = self._action(self.tr("&SVG …"), lambda: self.export(SVG))
        self.act_export_png = self._action(self.tr("P&NG …"), lambda: self.export(PNG))

        self.act_undo = self._action(self.tr("&Rückgängig"), self.undo, sk.Undo)
        self.act_redo = self._action(self.tr("&Wiederholen"), self.redo, sk.Redo)
        self.undo_group.canUndoChanged.connect(self.act_undo.setEnabled)
        self.undo_group.canRedoChanged.connect(self.act_redo.setEnabled)
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)
        self.act_select_all = self._action(
            self.tr("Alles &auswählen"), self.select_all, sk.SelectAll
        )
        self.act_delete = self._action(self.tr("&Löschen"), self.delete_selection, sk.Delete)
        self.act_cut = self._action(self.tr("Aus&schneiden"), self.cut, sk.Cut)
        self.act_copy_clip = self._action(self.tr("&Kopieren"), self.copy_to_clipboard, sk.Copy)
        self.act_paste = self._action(self.tr("&Einfügen"), self.paste, sk.Paste)

        self.act_line = self._tool_action(self.tr("&Linie"), LineTool)
        self.act_polyline = self._tool_action(self.tr("&Polylinie"), PolylineTool)
        self.act_rectangle = self._tool_action(self.tr("&Rechteck"), RectangleTool)
        self.act_circle = self._tool_action(self.tr("&Kreis"), CircleTool)
        self.act_arc = self._tool_action(self.tr("&Bogen"), ArcTool)
        self.act_text = self._tool_action(self.tr("&Text"), TextTool)
        self.act_wire = self._tool_action(self.tr("Lei&tung"), WireTool)
        self.act_wire.setShortcut(QKeySequence("Ctrl+W"))
        self.act_busbar = self._tool_action(self.tr("&Sammelschiene"), BusbarTool)
        self.act_dimension = self._tool_action(self.tr("Be&maßen"), DimensionTool)
        self.act_dimension.setToolTip(
            self.tr("Waagerecht oder senkrecht, je nachdem wohin die Maßlinie gezogen wird")
        )
        self.act_dimension_aligned = self._tool_action(
            self.tr("Bemaßen &parallel"), lambda ctx: DimensionTool(ctx, aligned=True)
        )
        self.act_dimension_angle = self._tool_action(
            self.tr("Bemaßen &Winkel"), AngularDimensionTool
        )
        self.act_dimension_angle.setToolTip(
            self.tr("Scheitelpunkt, je ein Punkt auf beiden Schenkeln, dann der Maßbogen")
        )
        self.act_dimension_aligned.setToolTip(
            self.tr("Parallel zur Strecke zwischen den Punkten, misst die wahre Länge")
        )
        self.act_interruption = self._tool_action(self.tr("&Unterbrechungspunkt"), InterruptionTool)
        self.act_interruption.setToolTip(
            self.tr(
                "Leitung geht auf einer anderen Seite weiter: Stelle, Richtung, Name. "
                "Gleichnamige Punkte zeigen gegenseitig ihre Seite und Spalte."
            )
        )
        self.act_module_field = self._action(self.tr("&Modulfeld …"), self.module_field)
        self.act_module_field.setToolTip(
            self.tr("Dachfläche automatisch mit PV-Modulen belegen (Arbeitsbereich Zeichnung)")
        )
        self.draw_actions = [
            self.act_wire,
            self.act_busbar,
            self.act_line,
            self.act_polyline,
            self.act_rectangle,
            self.act_circle,
            self.act_arc,
            self.act_text,
            self.act_dimension,
            self.act_dimension_aligned,
            self.act_dimension_angle,
            self.act_interruption,
            self.act_module_field,
        ]

        self.act_move = self._tool_action(self.tr("&Verschieben"), MoveTool)
        self.act_copy = self._tool_action(self.tr("&Kopieren"), CopyTool)
        self.act_rotate = self._tool_action(self.tr("&Drehen 90°"), RotateTool)
        self.act_rotate_free = self._tool_action(
            self.tr("Drehen (&beliebiger Winkel)"), RotateFreeTool
        )
        self.act_mirror = self._tool_action(self.tr("S&piegeln"), MirrorTool)
        self.act_scale = self._tool_action(self.tr("S&kalieren"), ScaleTool)
        self.act_scale.setToolTip(
            self.tr(
                "Größe ändern: Basispunkt, dann Faktor eintippen oder Bezugspunkt und neue Länge"
            )
        )
        self.act_explode = self._action(self.tr("&Auflösen"), self.blocks.explode_selection)
        self.modify_actions = [
            self.act_move,
            self.act_copy,
            self.act_rotate_free,
            self.act_rotate,
            self.act_mirror,
            self.act_scale,
            self.act_explode,
        ]

        self.act_grid = self._action(
            self.tr("&Raster anzeigen"), lambda: None, "F7", self.tr("RASTER")
        )
        self.act_grid.setCheckable(True)
        self.act_grid.setChecked(self.canvas.grid_visible())
        self.act_grid.toggled.connect(self.canvas.set_grid_visible)

        self.act_ortho = self._action(self.tr("&Ortho"), lambda: None, "F8", self.tr("ORTHO"))
        self.act_ortho.setCheckable(True)
        self.act_ortho.toggled.connect(self.canvas.set_ortho_enabled)

        self.act_snap = self._action(self.tr("Raster&fang"), lambda: None, "F9", self.tr("FANG"))
        self.act_snap.setCheckable(True)
        self.act_snap.setChecked(self.canvas.snap_enabled)
        self.act_snap.toggled.connect(self.canvas.set_snap_enabled)

        self.act_osnap = self._action(self.tr("&Objektfang"), lambda: None, "F3", self.tr("OFANG"))
        self.act_osnap.setCheckable(True)
        self.act_osnap.setChecked(self.canvas.osnap_enabled)
        self.act_osnap.toggled.connect(self.canvas.set_osnap_enabled)
        self.act_otrack = self._action(
            self.tr("Objektfang&spur"), lambda: None, "F11", self.tr("SPUR")
        )
        self.act_otrack.setCheckable(True)
        self.act_otrack.setChecked(self.canvas.otrack_enabled)
        self.act_otrack.toggled.connect(self.canvas.set_otrack_enabled)
        self.act_layer_cache = self._action(self.tr("Schnelle Darstellung"), lambda: None)
        self.act_layer_cache.setCheckable(True)
        self.act_layer_cache.setToolTip(
            self.tr(
                "Zeichnung als Bild zwischenspeichern: Mausbewegungen bei großen Plänen "
                "deutlich flüssiger. Bei Darstellungsfehlern ausschalten."
            )
        )
        self.act_layer_cache.toggled.connect(self.canvas.set_layer_cache_enabled)
        self.act_dynamic_input = self._action(self.tr("Maßeingabe am Fadenkreuz"), lambda: None)
        self.act_dynamic_input.setCheckable(True)
        self.act_dynamic_input.setToolTip(
            self.tr(
                "Beim Zeichnen Länge und Winkel (bzw. X/Y, Breite/Höhe) direkt am Fadenkreuz "
                "eintippen; Tab wechselt das Feld, Enter setzt den Punkt."
            )
        )
        self.act_dynamic_input.toggled.connect(self.canvas.set_dynamic_enabled)
        self.osnap_menu = OsnapMenu(
            self, self.act_osnap, lambda: self.canvas.osnap_modes, self._set_osnap_modes
        )
        self.act_osnap_settings = self._action(
            self.tr("Objektfang ein&stellen …"), self._edit_osnap_settings
        )
        self.act_grid_settings = self._action(
            self.tr("Raster und Fang &einstellen …"), self._edit_grid_settings
        )

        self.act_zoom_extents = self._action(
            self.tr("&Grenzen zoomen"), self.canvas.zoom_extents, "Home"
        )
        self.act_zoom_in = self._action(
            self.tr("Ver&größern"),
            lambda: self.canvas.set_zoom(self.canvas.zoom() * 1.5),
            sk.ZoomIn,
        )
        self.act_zoom_out = self._action(
            self.tr("Ver&kleinern"),
            lambda: self.canvas.set_zoom(self.canvas.zoom() / 1.5),
            sk.ZoomOut,
        )

        self.blocks.create_actions()
        self.sheets.create_actions()
        self.act_about = self._action(self.tr("Über {app}").format(app=APP_NAME), self._show_about)
        self.act_readme = self._action(self.tr("&README"), self._show_readme)
        self.act_support = self._action(
            self.tr("♥ Projekt &unterstützen"), lambda: open_url(project.SUPPORT_URL)
        )
        self.act_report_bug = self._action(
            self.tr("&Fehler melden …"), lambda: open_url(issue_url("[Bug] ", "bug"))
        )
        self.act_star = self._action(
            self.tr("★ &Stern auf GitHub geben"), lambda: open_url(project.URL)
        )

    def _create_menus(self) -> None:
        bar = self.menuBar()
        m = bar.addMenu(self.tr("&Datei"))
        m.addActions([self.act_new, self.act_open, self.act_save, self.act_save_as])
        m.addSeparator()
        m.addAction(self.act_print)
        export = m.addMenu(self.tr("&Exportieren"))
        export.addActions([self.act_export_pdf, self.act_export_svg, self.act_export_png])
        self.file_menu_tail = m.addSeparator()
        m.addAction(self.act_quit)
        self.file_menu = m

        m = bar.addMenu(self.tr("&Bearbeiten"))
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_cut, self.act_copy_clip, self.act_paste])
        m.addSeparator()
        m.addActions([self.act_select_all, self.act_delete])

        # Program settings (kept between sessions) in one menu.
        m = bar.addMenu(self.tr("&Einstellungen"))
        display_menu = m
        m.addActions([self.act_grid_settings, self.act_osnap_settings])
        m.addSeparator()
        m.addAction(self.act_layer_cache)
        m.addAction(self.act_dynamic_input)
        m.addSeparator()
        # Deliberately bilingual: findable whatever language is active.
        language_menu = display_menu.addMenu("Sprache / Language")
        group = QActionGroup(self)
        for code, label in i18n.LANGUAGES.items():
            action = language_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(code == i18n.current())
            action.setData(code)
            group.addAction(action)
        group.triggered.connect(self._choose_language)
        platform_menu = display_menu.addMenu(self.tr("Fenster&system"))
        group = QActionGroup(self)
        current = str(QSettings().value(platform_choice.SETTINGS_KEY, platform_choice.AUTO))
        for code, label in (
            (platform_choice.AUTO, self.tr("Automatisch (empfohlen)")),
            (platform_choice.WAYLAND, self.tr("Wayland")),
            (platform_choice.X11, self.tr("X11 (XWayland)")),
        ):
            action = platform_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(code == current)
            action.setData(code)
            group.addAction(action)
        group.triggered.connect(self._choose_platform)
        platform_menu.addSeparator()
        info = platform_menu.addAction(
            self.tr("Aktuell: {name}").format(name=QApplication.platformName())
        )
        info.setEnabled(False)
        open_menu = display_menu.addMenu(self.tr("Beim Öffnen &zeigen"))
        group = QActionGroup(self)
        current = str(QSettings().value(OPEN_VIEW_KEY, OPEN_EXTENTS))
        for code, label in (
            (OPEN_EXTENTS, self.tr("Ganze Zeichnung (Zoom Grenzen)")),
            (OPEN_LAST, self.tr("Letzte Ansicht dieser Datei")),
            (OPEN_ORIGIN, self.tr("Blatt 1 ab Nullpunkt")),
        ):
            action = open_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(code == current)
            action.setData(code)
            group.addAction(action)
        group.triggered.connect(self._choose_open_view)
        self.settings_menu = m

        m = bar.addMenu(self.tr("&Zeichnen"))
        m.addActions(self.draw_actions)
        self.draw_menu = m

        m = bar.addMenu(self.tr("Ä&ndern"))
        m.addActions(self.modify_actions)

        self.blocks.create_menu(bar)
        self.sheets.create_menu(bar)
        self.project_menu = bar.addMenu(self.tr("&Projekt"))

        m = bar.addMenu(self.tr("&Ansicht"))
        m.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_extents])
        m.addSeparator()
        m.addActions([self.act_grid, self.act_snap, self.act_ortho, self.act_osnap])
        m.addAction(self.act_otrack)
        m.addSeparator()
        self.docks_menu = m.addMenu(self.tr("&Fenster"))
        self.view_menu = m

        m = bar.addMenu(self.tr("&Hilfe"))
        m.addAction(self.act_readme)
        m.addSeparator()
        m.addActions([self.act_report_bug, self.act_star, self.act_support])
        m.addSeparator()
        m.addAction(self.act_about)

    def _create_toolbars(self) -> None:
        # The workspace switch sits at the right end of the status bar (Florian's wish).
        self.workspace_box = QComboBox()
        self.workspace_box.addItem(self.tr("Schaltplan (SLD)"), WORKSPACE_SLD)
        self.workspace_box.addItem(self.tr("Schaltplan (MLD)"), WORKSPACE_MLD)
        self.workspace_box.addItem(self.tr("Zeichnung"), WORKSPACE_DRAWING)
        self.workspace_box.setToolTip(
            self.tr(
                "Arbeitsbereich: zeigt die passenden Werkzeuge und Raster. "
                "Die Zeichnung selbst ändert sich dabei nicht."
            )
        )
        self.workspace_box.activated.connect(
            lambda _i: self.set_workspace(self.workspace_box.currentData())
        )
        self.workspace = WORKSPACE_SLD
        for name, title, actions in (
            ("draw", self.tr("Zeichnen"), self.draw_actions),
            ("modify", self.tr("Ändern"), [*self.modify_actions, self.act_delete]),
            ("blocks", self.tr("Blöcke"), self.blocks.toolbar_actions()),
        ):
            bar = QToolBar(title, self)
            bar.setObjectName(f"toolbar_{name}")
            bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            for action in actions:
                if action in (
                    self.act_rotate_free,
                    self.act_dimension_aligned,
                    self.act_dimension_angle,
                ):
                    continue
                if action is self.act_rotate:
                    bar.addWidget(self._rotate_button())
                    continue
                if action is self.act_dimension:
                    bar.addWidget(self._dimension_button())
                    continue
                bar.addAction(action)
            self.addToolBar(bar)

    def _rotate_button(self) -> QToolButton:
        """ "Drehen" with a drop-down: any angle (the click) or 90° steps."""
        menu = QMenu(self)
        menu.addActions([self.act_rotate_free, self.act_rotate])
        button = QToolButton()
        button.setText(self.tr("Drehen"))
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.clicked.connect(self.act_rotate_free.trigger)
        button.setToolTip(self.tr("Drehen um einen beliebigen Winkel; Pfeil: auch 90°-Schritte"))
        self.btn_rotate = button
        return button

    def _dimension_button(self) -> QToolButton:
        """ "Bemaßen" with a drop-down: horizontal/vertical, parallel or angle; the click
        repeats the variant chosen last."""
        menu = QMenu(self)
        menu.addActions([self.act_dimension, self.act_dimension_aligned, self.act_dimension_angle])
        button = QToolButton()
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setDefaultAction(self.act_dimension)
        button.setText(self.tr("Bemaßen"))
        menu.triggered.connect(button.setDefaultAction)
        self.btn_dimension = button
        return button

    def _create_docks(self) -> None:
        self.layers_dock = LayersDock(self, self)
        self.properties_dock = PropertiesDock(self, self)
        self.library_dock = LibraryDock(self, self)
        self.pages_dock = PagesDock(self, self)
        self.devices_dock = DevicesDock(self, self)
        self.blocks.attach_properties(self.properties_dock)
        self.sheets.attach_properties(self.properties_dock)
        self.properties_dock.extra_type_names.update(
            {
                Wire: self.tr("Leitung"),
                Busbar: self.tr("Sammelschiene"),
                InterruptionPoint: self.tr("Unterbrechungspunkt"),
            }
        )
        self.properties_dock.extra_editors.append(self._interruption_editor)
        self.properties_dock.extra_editors.append(self._wire_label_editor)
        self.properties_dock.extra_editors.append(self._dimension_editor)
        self.library_dock.insert_requested.connect(self.blocks.insert_from_source)
        self.library_dock.edit_requested.connect(self.blocks.edit_block_info)
        self.library_dock.editor_requested.connect(self.blocks.open_library_editor)
        self.library_dock.delete_requested.connect(self.blocks.delete_block)
        self.library_dock.save_requested.connect(self.blocks.save_block_to_user_library)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.layers_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.pages_dock)
        self.pages_dock.hide()  # only in the multi-line workspace
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.devices_dock)
        self.tabifyDockWidget(self.properties_dock, self.devices_dock)
        self.devices_dock.hide()  # Projekt > Geräteliste
        for dock in self.docks():
            install_title_bar(dock)
            self.docks_menu.addAction(dock.toggleViewAction())
        self.docks_menu.addSeparator()
        self.docks_menu.addAction(self.tr("Alle Fenster &andocken"), self.dock_all)
        self.docks_menu.addAction(self.tr("Fensteranordnung &zurücksetzen"), self.reset_dock_layout)
        devices = self.devices_dock.toggleViewAction()
        devices.setText(self.tr("&Geräteliste"))
        self.project_menu.addAction(devices)
        self.resizeDocks([self.layers_dock], [480], Qt.Orientation.Horizontal)
        self.resizeDocks([self.library_dock], [260], Qt.Orientation.Horizontal)

    def docks(self) -> list:
        return [
            self.layers_dock,
            self.properties_dock,
            self.library_dock,
            self.pages_dock,
            self.devices_dock,
        ]

    def dock_all(self) -> None:
        for dock in self.docks():
            dock.setFloating(False)

    def reset_dock_layout(self) -> None:
        """Default arrangement: library left, layers and properties right, all shown."""
        areas = {
            self.layers_dock: Qt.DockWidgetArea.RightDockWidgetArea,
            self.properties_dock: Qt.DockWidgetArea.RightDockWidgetArea,
            self.library_dock: Qt.DockWidgetArea.LeftDockWidgetArea,
            self.pages_dock: Qt.DockWidgetArea.LeftDockWidgetArea,
            self.devices_dock: Qt.DockWidgetArea.RightDockWidgetArea,
        }
        for dock, area in areas.items():
            dock.setFloating(False)
            self.removeDockWidget(dock)
            self.addDockWidget(area, dock)
            if dock is self.pages_dock:
                dock.setVisible(self.workspace == WORKSPACE_MLD)
            elif dock is self.devices_dock:
                dock.hide()
            else:
                dock.show()
        self.resizeDocks([self.layers_dock], [480], Qt.Orientation.Horizontal)
        self.resizeDocks([self.library_dock], [260], Qt.Orientation.Horizontal)

    def _create_status_bar(self) -> None:
        self.grid_menu = GridMenu(
            self,
            [self.act_grid, self.act_snap],
            lambda: (self.canvas.grid_spacing(), self.canvas.snap_spacing),
            self._set_grid_spacing,
            self._set_snap_spacing,
            lambda: self.canvas.polar_increment,
            self._set_polar_increment,
        )
        self.lbl_position = QLabel()
        width = self.lbl_position.fontMetrics().horizontalAdvance(
            "X: -00000,00 mm   Y: -00000,00 mm"
        )
        self.lbl_position.setMinimumWidth(width)
        self.lbl_layer = QLabel(self.tr("Ebene: {name}").format(name=DEFAULT_LAYER))
        self.lbl_zoom = QLabel()
        status = self.statusBar()
        status.addPermanentWidget(self.lbl_position)
        for action in (
            self.act_grid,
            self.act_snap,
            self.act_ortho,
            self.act_osnap,
            self.act_otrack,
        ):
            with_menu = action in (self.act_osnap, self.act_grid, self.act_snap)
            button = HoverMenuButton() if with_menu else QToolButton()
            button.setDefaultAction(action)
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if action in (self.act_grid, self.act_snap):
                button.setMenu(self.grid_menu)
                button.setToolTip(
                    self.tr("{name}; verweilen oder Pfeil: Raster und Fang eintragen").format(
                        name=action.text().replace("&", "")
                    )
                )
            if action is self.act_osnap:
                button.setMenu(self.osnap_menu)
                button.setToolTip(
                    self.tr("Objektfang (F3); verweilen oder Pfeil zeigt die Fangarten")
                )
                self.btn_osnap = button
            status.addPermanentWidget(button)
        status.addPermanentWidget(self.lbl_layer)
        status.addPermanentWidget(self.lbl_zoom)
        status.addPermanentWidget(self.workspace_box)
        self._show_cursor_position(QPointF(0.0, 0.0))

    # -- style, blocks and snapping -----------------------------------------

    def _resolve_style(self, entity: Entity) -> Style:
        doc = self.document
        return Style(
            QColor(doc.effective_color(entity)),
            doc.effective_lineweight(entity),
            doc.effective_linetype(entity),
        )

    def _layer_state(self, entity: Entity) -> tuple[bool, bool]:
        layer = self.document.layer(entity.layer)
        return layer.visible, layer.locked

    def _expand(self, entity: Entity) -> list[Entity]:
        return self.expand_with(self.block_definitions, entity)

    def expand_with(
        self, blocks: Mapping[str, BlockDefinition] | None, entity: Entity
    ) -> list[Entity]:
        if isinstance(entity, Wire):
            label = label_text(entity)
            return [entity, label] if label is not None else [entity]
        if isinstance(entity, Dimension):
            return dimension_geometry(entity, self.canvas.decimal_comma)
        if isinstance(entity, InterruptionPoint):
            target = self.interruption_targets().get(entity.id)
            return interruption_geometry(entity, target[0] if target else None)
        if isinstance(entity, BlockReference):
            definitions = blocks if blocks is not None else self.document.blocks
            try:
                parts = expand(entity, definitions)
            except BlockError:
                return []
            xref = self.crossref_lines().get(entity.id)
            if xref:
                parts = parts + crossref_texts(entity, definitions, xref)
            return [
                q
                for p in parts
                for q in (
                    dimension_geometry(p, self.canvas.decimal_comma)
                    if isinstance(p, Dimension)
                    else [p]
                )
            ]
        return [entity]

    def _decompose(self, entity: Entity) -> list[Entity]:
        if isinstance(entity, ConnectionPoint):
            return []
        return self._expand(entity)

    def _snap_extra(self, entity: Entity) -> list[SnapHit]:
        if isinstance(entity, ConnectionPoint):
            return [SnapHit(entity.position, SnapMode.CONNECTION)]
        if isinstance(entity, BlockReference):
            return [
                SnapHit(c.position, SnapMode.CONNECTION)
                for c in world_connections(entity, self.block_definitions)
            ]
        return []

    def _subscribe_document(self) -> None:
        self.document.subscribe_layers(self._on_layers_changed)
        self.document.subscribe_blocks(self._on_blocks_changed)
        self.document.subscribe_sheets(self._on_sheets_changed)
        self.document.model_space.subscribe(self._on_model_changed)

    def _unsubscribe_document(self) -> None:
        self.document.unsubscribe_layers(self._on_layers_changed)
        self.document.unsubscribe_blocks(self._on_blocks_changed)
        self.document.unsubscribe_sheets(self._on_sheets_changed)
        self.document.model_space.unsubscribe(self._on_model_changed)

    def _on_sheets_changed(self) -> None:
        self.sheets.on_sheets_changed()
        self._watch_pages()
        self._interruptions_changed()

    # -- interruption points (multi-line pages) ---------------------------------

    def contact_letters(self) -> dict[str, str]:
        return {
            "no": self.tr("S", "contact"),
            "nc": self.tr("Ö", "contact"),
            "co": self.tr("W", "contact"),
            "": "",
        }

    def crossref_lines(self) -> dict[str, list[str]]:
        """Contact mirror and main function references on the pages (cached like the
        interruption points)."""
        if self._crossrefs is None:
            self._crossrefs = crossrefs(self.document, self.contact_letters())
        return self._crossrefs

    def interruption_targets(self) -> dict[str, tuple[str, str]]:
        """Reference text and target page of every paired interruption point (cached
        until a page or the page order changes)."""
        if self._interruptions is None:
            self._interruptions = interruption_targets(self.document)
        return self._interruptions

    def _watch_pages(self) -> None:
        for page in self.document.pages:
            if id(page.entities) not in self._watched_pages:
                self._watched_pages[id(page.entities)] = page.entities
                page.entities.subscribe(self._on_page_changed)

    def _unwatch_pages(self) -> None:
        for container in self._watched_pages.values():
            container.unsubscribe(self._on_page_changed)
        self._watched_pages = {}

    def _on_page_changed(self, event: str, entity: Entity | None) -> None:
        if event == "batch_end" or isinstance(entity, InterruptionPoint | BlockReference):
            self._interruptions_changed()

    def _interruptions_changed(self) -> None:
        """Partners may have changed: references of all interruption points and the
        cross references of devices on the pages are drawn anew, once."""
        self._interruptions = None
        self._crossrefs = None
        if not self._interruption_refresh_pending:
            self._interruption_refresh_pending = True
            QTimer.singleShot(0, self._refresh_interruptions)

    def _refresh_interruptions(self) -> None:
        self._interruption_refresh_pending = False
        for space in self.sheets.all_spaces():
            for item in space.sync.items():
                if isinstance(item.entity, InterruptionPoint | BlockReference):
                    item.refresh()
        if hasattr(self, "devices_dock"):
            self.devices_dock.schedule_rebuild()

    def _on_model_changed(self, event: str, _entity: Entity | None) -> None:
        if self.document.model_space.in_batch:
            return  # once at "batch_end"
        if hasattr(self, "devices_dock"):
            self.devices_dock.schedule_rebuild()
        if hasattr(self, "sheets"):
            self.sheets.refresh_viewports()

    def _refresh_all_spaces(self) -> None:
        for space in self.spaces():
            space.sync.refresh()
            space.extra["junctions"].recompute()
        self.sheets.refresh_viewports()
        self.canvas.viewport().update()

    def _on_layers_changed(self) -> None:
        if not self.document.has_layer(self.current_layer):
            self.current_layer = DEFAULT_LAYER
        self.lbl_layer.setText(self.tr("Ebene: {name}").format(name=self.current_layer))
        self._refresh_all_spaces()
        self.layers_dock.rebuild()
        self.properties_dock.refresh()

    def _on_blocks_changed(self, _name: str) -> None:
        self._crossrefs = None  # a block's role may have changed
        self._refresh_all_spaces()
        self.library_dock.refresh_document()
        self.properties_dock.refresh()

    # -- document -----------------------------------------------------------

    def _set_document(self, document: Document, path: Path | None) -> None:
        self._remember_view()
        self.tools.cancel()
        self.blocks.close_editor(save=False, ask=False)
        self.autosave.discard()
        self._unsubscribe_document()
        old = self.model_view
        self.document = document
        self.file_path = path
        self.sheets.reset()
        self.model_view = self._make_space(MODEL, document.model_space, self.undo_stack)
        self.model_view.extra["overlay"] = self.sheets.model_overlay
        self.space = self.model_view
        self.canvas.set_scene(self.space.scene)
        self.canvas.extra_overlay = self.sheets.model_overlay
        self.canvas.set_background(BACKGROUND_COLOR, show_origin=True)
        self.undo_group.setActiveStack(self.undo_stack)
        self._drop_space(old)
        self._unwatch_pages()
        self._interruptions = None
        self._crossrefs = None
        self._subscribe_document()
        self._watch_pages()
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.sheets.rebuild_tabs()
        self.set_current_layer(DEFAULT_LAYER)
        self.properties_dock.refresh()
        self.library_dock.refresh_document()
        self._update_title()
        if self.workspace == WORKSPACE_MLD:
            # A drawing without pages is not changed just by opening it.
            if document.pages:
                self.sheets.show_sheet(document.pages[0].id)
            else:
                self.set_workspace(WORKSPACE_SLD)
        self.canvas.set_initial_view(self._opening_view)

    # -- view when a drawing is opened ----------------------------------------

    def _view_key(self) -> str | None:
        if self.file_path is None:
            return None
        digest = hashlib.sha1(str(self.file_path.resolve()).encode("utf-8")).hexdigest()
        return f"{LAST_VIEW_GROUP}/{digest}"

    def _model_view_state(self) -> tuple[float, QPointF]:
        if self.space is self.model_view or self.model_view.view is None:
            center = self.canvas.map_to_scene_f(QPointF(self.canvas.viewport().rect().center()))
            return self.canvas.zoom(), center
        transform, center = self.model_view.view
        return transform.m11() / self.canvas.px_per_mm(), center

    def _remember_view(self) -> None:
        """Store zoom and centre of the model for the open file (for "last view")."""
        key = self._view_key()
        if key is None or not hasattr(self, "model_view"):
            return
        zoom, center = self._model_view_state()
        QSettings().setValue(key, [zoom, center.x(), center.y()])

    def _opening_view(self) -> None:
        mode = str(QSettings().value(OPEN_VIEW_KEY, OPEN_EXTENTS))
        if mode == OPEN_LAST and (key := self._view_key()) is not None:
            stored = QSettings().value(key)
            try:
                zoom, x, y = (float(v) for v in stored)
            except (TypeError, ValueError):
                pass
            else:
                self.canvas.set_view(zoom, QPointF(x, y))
                return
        if mode == OPEN_ORIGIN:
            sheet = self.document.sheets[0] if self.document.sheets else None
            viewports = sheet.viewports() if sheet else []
            if viewports:
                a, b = viewports[0].model_rect()
                self.canvas.fit_rect_top_left(QRectF(a.x, a.y, b.x - a.x, b.y - a.y))
                return
            self.canvas.fit_rect_top_left(EMPTY_EXTENTS)
            return
        self.canvas.zoom_extents()

    def _choose_open_view(self, action) -> None:
        QSettings().setValue(OPEN_VIEW_KEY, action.data())

    def _update_title(self) -> None:
        name = self.file_path.name if self.file_path else self.tr("Unbenannt")
        suffix = ""
        if self.space.kind == BLOCK:
            suffix = self.tr(" [Blockeditor: {name}]").format(name=self.blocks.editor_name())
        self.setWindowTitle(f"{name}[*]{suffix} - {APP_NAME}")
        self.setWindowModified(not self.undo_stack.isClean())

    def _maybe_save(self) -> bool:
        """Ask to save unsaved changes. False means the user cancelled."""
        if not self.blocks.close_editor(save=None, ask=True):
            return False
        if self.undo_stack.isClean():
            return True
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            APP_NAME,
            self.tr("Die Zeichnung wurde geändert. Änderungen speichern?"),
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Save,
        )
        if answer == buttons.Save:
            return self.save()
        return answer == buttons.Discard

    def new_document(self) -> None:
        if self._maybe_save():
            self._set_document(Document.new(self.tr("Blatt 1"), title_labels()), None)

    def _file_filter(self) -> str:
        return self.tr("SLDGridy-Zeichnung (*{suffix})").format(suffix=DRAWING_SUFFIX)

    def last_dir(self) -> str:
        return str(QSettings().value("files/last_dir", str(Path.home())))

    def remember_dir(self, path: Path) -> None:
        QSettings().setValue("files/last_dir", str(path.parent))

    def open_document(self) -> None:
        if not self._maybe_save():
            return
        name, _ = QFileDialog.getOpenFileName(
            self, self.tr("Zeichnung öffnen"), self.last_dir(), self._file_filter()
        )
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path) -> bool:
        try:
            document = load_document(path)
        except (OSError, FileFormatError) as exc:
            QMessageBox.critical(
                self,
                APP_NAME,
                self.tr("Die Datei {name} kann nicht geöffnet werden:\n{error}").format(
                    name=path.name, error=exc
                ),
            )
            return False
        self.remember_dir(path)
        self._set_document(document, path)
        return True

    def save(self) -> bool:
        if self.file_path is None:
            return self.save_as()
        return self.save_to(self.file_path)

    def save_as(self) -> bool:
        start = str(self.file_path) if self.file_path else self.last_dir()
        name, _ = QFileDialog.getSaveFileName(
            self, self.tr("Zeichnung speichern"), start, self._file_filter()
        )
        if not name:
            return False
        path = Path(name)
        if path.suffix != DRAWING_SUFFIX:
            path = path.with_name(path.name + DRAWING_SUFFIX)
        return self.save_to(path)

    def save_to(self, path: Path) -> bool:
        try:
            save_document(self.document, path)
        except OSError as exc:
            QMessageBox.critical(
                self,
                APP_NAME,
                self.tr("Die Datei {name} kann nicht gespeichert werden:\n{error}").format(
                    name=path.name, error=exc
                ),
            )
            return False
        self.file_path = path
        self.remember_dir(path)
        self.undo_stack.setClean()
        self.autosave.discard()
        self._update_title()
        self.message(self.tr("Gespeichert: {path}").format(path=path))
        return True

    def offer_recovery(self) -> None:
        """Offer backups of instances that ended without saving."""
        for backup in orphaned_backups():
            name = backup.original.name if backup.original else self.tr("Unbenannt")
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(self.tr("Wiederherstellung"))
            box.setText(
                self.tr(
                    "Es gibt eine automatische Sicherung von „{name}“ ({time}), "
                    "die nicht gespeichert wurde."
                ).format(name=name, time=backup.saved.replace("T", " "))
            )
            restore = box.addButton(self.tr("Wiederherstellen"), QMessageBox.ButtonRole.AcceptRole)
            discard = box.addButton(self.tr("Verwerfen"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(self.tr("Später"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is discard:
                remove_backup(backup)
            elif box.clickedButton() is restore and self.restore_backup(backup):
                return

    def restore_backup(self, backup) -> bool:
        if not self._maybe_save():
            return False
        try:
            document = load_document(backup.path)
        except (OSError, FileFormatError) as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))
            return False
        self._set_document(document, backup.original)
        self.undo_stack.resetClean()  # recovered content counts as unsaved
        self._update_title()
        # The old backup goes only once this instance holds its own copy: ending now
        # (closed terminal, crash) must not lose the recovered work.
        if self.autosave.save_now():
            remove_backup(backup)
        return True

    # -- printing and export ------------------------------------------------

    def print_document(self) -> None:
        self.tools.cancel()
        dialog = PrintDialog(
            self.document,
            self.sheets.current_sheet(),
            parent=self,
            layouts=self.sheets.layouts(),
            pages=self.sheets.pages_mode,
        )
        dialog.exec()

    def export(self, kind: str) -> None:
        self.tools.cancel()
        current = self.sheets.current_sheet()
        dialog = ExportDialog(kind, current is not None, self)
        if dialog.exec() != ExportDialog.DialogCode.Accepted:
            return
        sheets = list(self.sheets.layouts()) if dialog.all_sheets() else [current]
        base = self.file_path.with_suffix("") if self.file_path else Path(self.last_dir()) / "plan"
        if kind != PDF and len(sheets) == 1 and len(self.sheets.layouts()) > 1:
            base = base.with_name(f"{base.name}_{sheets[0].name}")
        filters = {
            PDF: self.tr("PDF (*.pdf)"),
            SVG: self.tr("SVG (*.svg)"),
            PNG: self.tr("PNG-Bild (*.png)"),
        }
        name, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportieren"), str(base) + "." + kind, filters[kind]
        )
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != "." + kind:
            path = path.with_name(path.name + "." + kind)
        try:
            written = self.export_to(kind, path, sheets, dialog.options(), dialog.dpi.value())
        except OSError as exc:
            QMessageBox.critical(self, self.tr("Exportieren"), str(exc))
            return
        self.remember_dir(path)
        self.message(
            self.tr("Exportiert: {files}").format(files=", ".join(p.name for p in written))
        )

    def export_to(self, kind: str, path: Path, sheets, options, dpi: int = 300) -> list[Path]:
        """Write the export file(s); several SVG/PNG sheets get the sheet name appended."""
        if kind == PDF:
            export_pdf(path, self.document, sheets, options)
            return [path]
        written = []
        for sheet in sheets:
            target = path
            if len(sheets) > 1:
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sheet.name)
                target = path.with_name(f"{path.stem}_{safe}{path.suffix}")
            if kind == SVG:
                export_svg(target, self.document, sheet, options)
            else:
                export_png(target, self.document, sheet, dpi, options)
            written.append(target)
        return written

    # -- editing ------------------------------------------------------------

    def start_tool(self, factory: ToolFactory) -> None:
        self.tools.start(factory)
        self.canvas.setFocus()

    def undo(self) -> None:
        # A running tool may hold snapshots that undo would invalidate.
        self.tools.cancel()
        self.undo_group.undo()

    def redo(self) -> None:
        self.tools.cancel()
        self.undo_group.redo()

    def select_all(self) -> None:
        select_items(
            self.scene,
            [
                item
                for item in self.scene.items()
                if isinstance(item, EntityItem)
                and item.isVisible()
                and item.flags() & item.GraphicsItemFlag.ItemIsSelectable
            ],
        )

    def delete_selection(self) -> None:
        ids = self.selected_ids()
        if ids:
            self.tools.cancel()
            self.push(RemoveEntitiesCommand(self.container, ids, self.tr("Löschen")))

    def selected_entities(self) -> list[Entity]:
        return [self.container.get(i) for i in self.selected_ids()]

    def selection_base(self) -> Point:
        """Lower left corner of the selection's bounding box."""
        rect = None
        for item in self.scene.selectedItems():
            r = item.sceneBoundingRect()
            rect = r if rect is None else rect.united(r)
        return Point(rect.left(), rect.bottom()) if rect is not None else Point(0.0, 0.0)

    def copy_to_clipboard(self) -> bool:
        entities = self.selected_entities()
        if not entities:
            return False
        clipboard.copy_entities(
            entities, self.selection_base(), self.blocks.clipboard_extra(entities)
        )
        return True

    def cut(self) -> None:
        if self.copy_to_clipboard():
            self.tools.cancel()
            self.push(
                RemoveEntitiesCommand(self.container, self.selected_ids(), self.tr("Ausschneiden"))
            )

    def paste(self) -> None:
        payload = clipboard.clipboard_payload()
        result = clipboard.paste_entities(payload) if payload else None
        if result is None:
            self.message(self.tr("Die Zwischenablage enthält keine Zeichnungsobjekte"))
            return
        entities, base = result
        if not self.blocks.prepare_paste(payload, entities):
            return
        entities = [
            replace(e, layer=e.layer if self.document.has_layer(e.layer) else DEFAULT_LAYER)
            for e in entities
        ]
        self.start_tool(lambda ctx: PasteTool(ctx, entities, base))

    def _on_clean_changed(self, clean: bool) -> None:
        self.setWindowModified(not clean)

    def _on_undo_index_changed(self, _index: int) -> None:
        self.properties_dock.refresh()

    def _on_selection_changed(self) -> None:
        if hasattr(self, "properties_dock"):
            self.properties_dock.refresh()
        self.canvas.viewport().update()

    def _on_command_input(self, text: str) -> None:
        self.canvas.setFocus()
        if not text.strip():
            if self.tools.active is not None:
                self.tools.finish()
            else:
                self.tools.repeat()
            return
        if self.tools.active is None or self.tools.selecting():
            self.message(self.tr("Koordinaten werden nur während eines Zeichenbefehls erwartet"))
            return
        reference = self.tools.base_point() or self.tools.last_point
        try:
            p = parse_coordinate(text, reference, self.canvas.ortho_direction())
        except CoordinateError:
            self.message(self.tr("Ungültige Eingabe: {text}").format(text=text))
            return
        self.tools.hover(p)
        self.tools.pick(p)

    def _on_command_cancel(self) -> None:
        self.tools.cancel()
        self.canvas.setFocus()

    def module_field(self) -> None:
        from sldgridy.tools.pv import ModuleFieldTool
        from sldgridy.ui.pv_dialog import ModuleFieldDialog, save_spec, saved_spec

        dialog = ModuleFieldDialog(saved_spec(), self)
        if dialog.exec() != ModuleFieldDialog.DialogCode.Accepted:
            return
        spec = dialog.spec()
        save_spec(spec)
        self.start_tool(lambda ctx: ModuleFieldTool(ctx, spec))

    def _show_readme(self) -> None:
        from sldgridy.ui.readme_dialog import ReadmeDialog

        ReadmeDialog(self).exec()

    def _choose_platform(self, action) -> None:
        QSettings().setValue(platform_choice.SETTINGS_KEY, action.data())
        QMessageBox.information(
            self,
            self.tr("Fenstersystem"),
            self.tr("Das Fenstersystem wird beim nächsten Start von SLDGridy umgestellt."),
        )

    def _choose_language(self, action) -> None:
        code = action.data()
        QSettings().setValue(i18n.SETTINGS_KEY, code)
        if code != i18n.current():
            QMessageBox.information(
                self,
                "Sprache / Language",
                "Die Sprache wird beim nächsten Start von SLDGridy umgestellt.\n\n"
                "The language changes the next time SLDGridy starts.",
            )

    def _set_osnap_modes(self, modes) -> None:
        self.canvas.osnap_modes = frozenset(modes)

    def _show_point_menu(self, scene_pos: QPointF, global_pos) -> None:
        actions = point_actions(self, Point(scene_pos.x(), scene_pos.y()))
        if not actions:
            return
        menu = QMenu(self)
        for label, callback in actions:
            menu.addAction(label, callback)
        menu.exec(global_pos)

    def _edit_osnap_settings(self) -> None:
        dialog = OsnapDialog(self.canvas.osnap_modes, self)
        if dialog.exec() == OsnapDialog.DialogCode.Accepted:
            self.canvas.osnap_modes = dialog.modes()

    def _edit_entity(self, entity_id: str) -> None:
        entity = self.container.get(entity_id)
        if self.blocks.edit_entity(entity):
            return
        if isinstance(entity, InterruptionPoint):
            if not self.go_to_partner(entity.id):
                self.message(
                    self.tr("Zu „{name}“ gibt es noch keinen zweiten Punkt").format(
                        name=entity.name
                    )
                )
            return
        if isinstance(entity, Wire):
            label, ok = QInputDialog.getText(
                self, self.tr("Leitung"), self.tr("Beschriftung:"), text=entity.label
            )
            if ok and label != entity.label:
                self.push(
                    ReplaceEntitiesCommand(
                        self.container, [replace(entity, label=label)], self.tr("Beschriftung")
                    )
                )
            return
        if not isinstance(entity, Text):
            return
        result = self.ask_text(entity.text, entity.height)
        if result is None:
            return
        content, height = result
        if not content.strip() or (content, height) == (entity.text, entity.height):
            return
        changed = replace(entity, text=content, height=height)
        self.push(ReplaceEntitiesCommand(self.container, [changed], self.tr("Text ändern")))

    def _common(self, values: list) -> object:
        """The shared value, or MIXED when the selected objects differ."""
        return values[0] if all(v == values[0] for v in values) else MIXED

    def _apply_to_all(self, ids: list[str], change, label: str) -> None:
        """One undo step changing every still existing object in ``ids``."""
        changed = []
        for entity_id in ids:
            if entity_id not in self.container:
                continue
            current = self.container.get(entity_id)
            new = change(current)
            if new is not None and new != current:
                changed.append(new)
        if changed:
            self.push(ReplaceEntitiesCommand(self.container, changed, label))

    def _mixed_combo(self, combo: QComboBox, value: object) -> None:
        if value == MIXED:
            combo.insertItem(0, self.tr("*verschieden*"), MIXED)
            combo.setCurrentIndex(0)
        else:
            combo.setCurrentIndex(max(combo.findData(value), 0))

    def _mixed_line_edit(self, edit: QLineEdit, value: object, placeholder: str = "") -> None:
        if value == MIXED:
            edit.setPlaceholderText(self.tr("*verschieden*"))
            edit.setToolTip(self.tr("Die markierten Objekte haben verschiedene Werte"))
        else:
            edit.setText(str(value))
            edit.setPlaceholderText(placeholder)

    def _dimension_editor(self, entities: list[Entity], layout: QVBoxLayout) -> None:
        """Value text, text height and direction of every selected dimension; fields
        whose values differ show *verschieden*, a new value applies to all."""
        dims = [e for e in entities if isinstance(e, Dimension)]
        if not dims:
            return
        ids = [d.id for d in dims]
        label = self.tr("Bemaßung ändern")
        box = QGroupBox(
            self.tr("Bemaßung") if len(dims) == 1 else self.tr("Bemaßung ({n})").format(n=len(dims))
        )
        form = QFormLayout(box)
        text = QLineEdit()
        values = {measured_text(d, self.canvas.decimal_comma) for d in dims}
        measured_hint = (
            self.tr("gemessen: {value}").format(value=next(iter(values)))
            if len(values) == 1
            else self.tr("gemessen (je Maß)")
        )
        self._mixed_line_edit(text, self._common([d.text for d in dims]), measured_hint)
        if not text.toolTip():
            text.setToolTip(self.tr("Leer lassen für den gemessenen Wert"))
        height = QDoubleSpinBox()
        height.setDecimals(2)
        height.setSuffix(" mm")
        height.setKeyboardTracking(False)
        common_height = self._common([d.height for d in dims])
        if common_height == MIXED:
            # The minimum shows as *verschieden* until a real value is entered.
            height.setRange(0.0, 100000.0)
            height.setSpecialValueText(self.tr("*verschieden*"))
            height.setValue(0.0)
        else:
            height.setRange(0.1, 100000.0)
            height.setValue(float(common_height))
            paper = scale_at(self.document.sheets, dims[0].p1) * float(common_height)
            height.setToolTip(
                self.tr("Texthöhe im Modell; auf dem Blatt etwa {paper} mm").format(
                    paper=format_value(paper, self.canvas.decimal_comma)
                )
            )
        linear = [d for d in dims if d.orientation != "angular"]
        orientation = QComboBox()
        for code, name in (
            ("horizontal", self.tr("waagerecht")),
            ("vertical", self.tr("senkrecht")),
            ("aligned", self.tr("parallel")),
        ):
            orientation.addItem(name, code)
        if linear:
            self._mixed_combo(orientation, self._common([d.orientation for d in linear]))
        form.addRow(self.tr("Maßtext:"), text)
        form.addRow(self.tr("Texthöhe:"), height)
        if linear:
            form.addRow(self.tr("Richtung:"), orientation)
        else:
            orientation.hide()
        layout.addWidget(box)

        shown_text = text.text()

        def set_text() -> None:
            # Leaving the field unchanged keeps differing texts.
            if text.isModified() or text.text() != shown_text:
                value = text.text().strip()
                self._apply_to_all(ids, lambda d: replace(d, text=value), label)

        def set_height(value: float) -> None:
            if value > 0:
                self._apply_to_all(ids, lambda d: replace(d, height=float(value)), label)

        def set_orientation() -> None:
            code = orientation.currentData()
            if code != MIXED:
                self._apply_to_all(
                    ids,
                    lambda d: replace(d, orientation=code) if d.orientation != "angular" else None,
                    label,
                )

        text.editingFinished.connect(set_text)
        height.valueChanged.connect(set_height)
        orientation.activated.connect(lambda _i: set_orientation())

    def _interruption_editor(self, entities: list[Entity], layout: QVBoxLayout) -> None:
        points = [e for e in entities if isinstance(e, InterruptionPoint)]
        if len(points) != 1 or len(entities) != 1:
            return
        point = points[0]
        box = QGroupBox(self.tr("Unterbrechungspunkt"))
        form = QFormLayout(box)
        name = QLineEdit(point.name)
        target = self.interruption_targets().get(point.id)
        where = QLabel(target[0] if target else self.tr("(noch kein zweiter Punkt)"))
        go = QPushButton(self.tr("Zum Gegenstück"))
        go.setEnabled(target is not None)
        go.clicked.connect(lambda: self.go_to_partner(point.id))
        form.addRow(self.tr("Name:"), name)
        form.addRow(self.tr("Gegenstück:"), where)
        form.addRow(go)
        layout.addWidget(box)

        def apply() -> None:
            value = name.text().strip()
            current = self.container.get(point.id) if point.id in self.container else None
            if current is not None and value and value != current.name:
                self.push(
                    ReplaceEntitiesCommand(
                        self.container, [replace(current, name=value)], self.tr("Umbenennen")
                    )
                )

        name.editingFinished.connect(apply)

    def _wire_label_editor(self, entities: list[Entity], layout: QVBoxLayout) -> None:
        """Label of every selected wire; differing fields show *verschieden*, a new
        value applies to all selected wires."""
        wires = [e for e in entities if isinstance(e, Wire)]
        if not wires:
            return
        ids = [w.id for w in wires]
        label = self.tr("Beschriftung")
        box = QGroupBox(
            self.tr("Beschriftung")
            if len(wires) == 1
            else self.tr("Beschriftung ({n})").format(n=len(wires))
        )
        form = QFormLayout(box)
        edit = QLineEdit()
        self._mixed_line_edit(
            edit, self._common([w.label for w in wires]), self.tr("z. B. NYY-J 5x16")
        )
        side = QComboBox()
        side.addItem(self.tr("oben / links"), 1)
        side.addItem(self.tr("unten / rechts"), -1)
        self._mixed_combo(side, self._common([1 if w.label_side > 0 else -1 for w in wires]))
        align = QComboBox()
        align.addItem(self.tr("links"), "left")
        align.addItem(self.tr("mitte"), "center")
        align.addItem(self.tr("rechts"), "right")
        self._mixed_combo(align, self._common([w.label_align for w in wires]))
        align.setToolTip(self.tr("Entlang der Leitung in Leserichtung (senkrecht: unten = links)"))
        position = QComboBox()
        position.addItem(self.tr("automatisch (längster Abschnitt)"), "auto")
        position.addItem(self.tr("Anfang"), "start")
        position.addItem(self.tr("Ende"), "end")
        position.addItem(self.tr("frei (Griff auf der Leitung ziehen)"), "free")
        common_pos = self._common([w.label_pos for w in wires])
        self._mixed_combo(position, common_pos)
        position.setToolTip(
            self.tr("Frei: den Griff an der Beschriftung entlang der Leitung ziehen")
        )
        align.setEnabled(common_pos in ("auto", "free", MIXED))
        height = HeightCombo()
        height.set_height(self._common([w.label_height for w in wires]))
        apply = QPushButton(self.tr("Beschriftung übernehmen"))
        form.addRow(self.tr("Text:"), edit)
        form.addRow(self.tr("Lage:"), side)
        form.addRow(self.tr("Position:"), position)
        form.addRow(self.tr("Ausrichtung:"), align)
        form.addRow(self.tr("Größe:"), height)
        form.addRow(apply)
        layout.addWidget(box)

        shown_label = edit.text()

        def set_text() -> None:
            if edit.isModified() or edit.text() != shown_label or len(wires) == 1:
                value = edit.text()
                self._apply_to_all(ids, lambda w: replace(w, label=value), label)

        def set_choice(combo: QComboBox, field: str, kind) -> None:
            value = combo.currentData()
            if value == MIXED:
                return

            def change(w: Wire) -> Wire:
                new = replace(w, **{field: kind(value)})
                if field == "label_pos" and value == "free" and w.label_pos != "free":
                    # Start where the label is now, then the grip moves it along the wire.
                    anchor = label_anchor(w)[0]
                    new = replace(new, label_at=round(project_on_path(w.points, anchor), 3))
                return new

            self._apply_to_all(ids, change, label)

        apply.clicked.connect(set_text)
        edit.returnPressed.connect(set_text)
        # Choices take effect at once, like the other property fields.
        side.activated.connect(lambda _i: set_choice(side, "label_side", int))
        align.activated.connect(lambda _i: set_choice(align, "label_align", str))
        position.activated.connect(lambda _i: set_choice(position, "label_pos", str))
        height.value_chosen.connect(
            lambda v: self._apply_to_all(ids, lambda w: replace(w, label_height=v), label)
        )

    def _edit_grid_settings(self) -> None:
        dialog = GridDialog(self.canvas.grid_spacing(), self.canvas.snap_spacing, self)
        if dialog.exec() == GridDialog.DialogCode.Accepted:
            self.canvas.set_grid_spacing(dialog.grid_spacing())
            self.canvas.set_snap_spacing(dialog.snap_spacing())

    # -- slots --------------------------------------------------------------

    def _on_tool_changed(self) -> None:
        active = self.tools.active is not None
        if getattr(self, "_tool_was_active", False) and not active:
            self.canvas.clear_tracking()  # tracking points live for one command
        self._tool_was_active = active
        prompt = self.tools.prompt() or self.tr("Befehl:")
        self.command_line.set_prompt(prompt)
        self.canvas.viewport().update()

    def _fmt_mm(self, value: float) -> str:
        return self._locale.toString(value, "f", 2)

    def _show_cursor_position(self, pos: QPointF) -> None:
        self.lbl_position.setText(
            self.tr("X: {x} mm   Y: {y} mm").format(
                x=self._fmt_mm(pos.x()), y=self._fmt_mm(pos.y())
            )
        )

    def _show_zoom(self, zoom: float) -> None:
        digits = 0 if zoom >= 0.1 else 1 if zoom >= 0.01 else 2
        percent = self._locale.toString(zoom * 100, "f", digits)
        self.lbl_zoom.setText(self.tr("Zoom: {percent} %").format(percent=percent))

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    # -- settings -----------------------------------------------------------

    def _restore_settings(self) -> None:
        settings = QSettings()
        geometry = settings.value("main_window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value("main_window/state")
        if state is not None:
            self.restoreState(state)
        self.act_grid.setChecked(settings.value("view/grid_visible", True, type=bool))
        self.act_snap.setChecked(settings.value("view/snap_enabled", True, type=bool))
        self.act_ortho.setChecked(settings.value("view/ortho_enabled", False, type=bool))
        self.act_osnap.setChecked(settings.value("view/osnap_enabled", True, type=bool))
        self.act_otrack.setChecked(settings.value("view/otrack_enabled", True, type=bool))
        modes = settings.value("view/osnap_modes", None)
        if isinstance(modes, str):
            modes = [modes] if modes else []
        known = settings.value("view/osnap_known", None)
        if isinstance(known, str):
            known = [known] if known else []
        valid = {m.value for m in SnapMode}
        if modes is None:
            self.canvas.osnap_modes = ALL_MODES
        else:
            chosen = {SnapMode(m) for m in modes if m in valid}
            # Modes added in a newer version than the saved settings start switched on.
            known_set = (
                set(known)
                if known is not None
                else {"connection", "endpoint", "midpoint", "intersection", "center"}
            )
            chosen |= {m for m in SnapMode if m.value not in known_set}
            self.canvas.osnap_modes = frozenset(chosen)
        self.act_layer_cache.setChecked(settings.value("view/layer_cache", False, type=bool))
        self.act_dynamic_input.setChecked(settings.value("view/dynamic_input", True, type=bool))
        self.canvas.polar_increment = settings.value("view/polar_increment", 15.0, type=float)
        self.canvas.set_dynamic_enabled(self.act_dynamic_input.isChecked())
        self.canvas.decimal_comma = i18n.ui_locale().decimalPoint() == ","
        # Every start begins in the circuit diagram (Florian's wish), whatever was used last.
        self.workspace = WORKSPACE_SLD
        self._apply_workspace()

    def _set_grid_spacing(self, value: float) -> None:
        if value > 0:
            self.canvas.set_grid_spacing(value)
            self._remember_workspace_grid()

    def _set_polar_increment(self, value: float) -> None:
        self.canvas.polar_increment = max(0.0, float(value))
        QSettings().setValue("view/polar_increment", self.canvas.polar_increment)

    def _set_snap_spacing(self, value: float) -> None:
        if value > 0:
            self.canvas.set_snap_spacing(value)
            self._remember_workspace_grid()

    # -- workspaces ---------------------------------------------------------

    def _workspace_grid(self, workspace: str) -> tuple[float, float]:
        settings = QSettings()
        grid, snap = WORKSPACE_GRID[workspace]
        if workspace == WORKSPACE_SLD:
            # Settings from before workspaces existed belong to the circuit diagram.
            grid = settings.value("view/grid_spacing", grid, type=float)
            snap = settings.value("view/snap_spacing", snap, type=float)
        grid = settings.value(f"workspace/{workspace}/grid", grid, type=float)
        snap = settings.value(f"workspace/{workspace}/snap", snap, type=float)
        return grid, snap

    def _remember_workspace_grid(self) -> None:
        settings = QSettings()
        settings.setValue(f"workspace/{self.workspace}/grid", self.canvas.grid_spacing())
        settings.setValue(f"workspace/{self.workspace}/snap", self.canvas.snap_spacing)

    def set_workspace(self, workspace: str) -> None:
        """Circuit diagram or scaled drawing: tools and grid, not the drawing itself."""
        if workspace not in WORKSPACE_GRID or workspace == self.workspace:
            return
        self.tools.cancel()
        self._remember_workspace_grid()
        self.workspace = workspace
        self._apply_workspace()

    def _apply_workspace(self) -> None:
        grid, snap = self._workspace_grid(self.workspace)
        if grid > 0:
            self.canvas.set_grid_spacing(grid)
        if snap > 0:
            self.canvas.set_snap_spacing(snap)
        drawing = self.workspace == WORKSPACE_DRAWING
        mld = self.workspace == WORKSPACE_MLD
        for action in (self.act_wire, self.act_busbar):
            action.setVisible(not drawing)
        self.act_module_field.setVisible(drawing)
        self.act_interruption.setVisible(mld)
        self.sheets.set_pages_mode(mld)
        self.pages_dock.setVisible(mld)
        if mld:
            self.pages_dock.rebuild()
        self.library_dock.set_workspace(self.workspace)
        # Each workspace has its own layers; the current one must belong to it.
        if self.document.has_layer(self.current_layer) and not self.document.layer(
            self.current_layer
        ).in_workspace(self.workspace):
            self.set_current_layer(DEFAULT_LAYER)
        self.layers_dock.rebuild()
        self.properties_dock.refresh()
        self.workspace_box.setCurrentIndex(max(self.workspace_box.findData(self.workspace), 0))
        self.message(
            self.tr("Arbeitsbereich: {name}").format(name=self.workspace_box.currentText())
        )

    def _save_settings(self) -> None:
        settings = QSettings()
        settings.setValue("main_window/geometry", self.saveGeometry())
        settings.setValue("main_window/state", self.saveState())
        settings.setValue("view/grid_visible", self.act_grid.isChecked())
        settings.setValue("view/snap_enabled", self.act_snap.isChecked())
        settings.setValue("view/ortho_enabled", self.act_ortho.isChecked())
        settings.setValue("view/osnap_enabled", self.act_osnap.isChecked())
        settings.setValue("view/otrack_enabled", self.act_otrack.isChecked())
        settings.setValue("view/layer_cache", self.act_layer_cache.isChecked())
        settings.setValue("view/dynamic_input", self.act_dynamic_input.isChecked())
        settings.setValue("view/osnap_modes", sorted(m.value for m in self.canvas.osnap_modes))
        settings.setValue("view/osnap_known", sorted(m.value for m in SnapMode))
        self._remember_workspace_grid()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_initial_view_done", False):
            self._initial_view_done = True
            self.canvas.set_initial_view(self._opening_view)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            button = event.button()
            if button in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton) and (
                watched.window() is self
            ):
                action = self.act_undo if button == Qt.MouseButton.BackButton else self.act_redo
                if action.isEnabled():
                    action.trigger()
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._maybe_save():
            event.ignore()
            return
        self.tools.cancel()
        self._remember_view()
        self.autosave.discard()
        self._save_settings()
        # Qt 6.10 still routes events through application filters while a window is
        # destroyed; a filter living on the dying window then crashes (Ubuntu 26.04).
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
