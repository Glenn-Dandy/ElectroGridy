"""Sheets (drawing frames): tabs, sheet spaces, viewports, title block fields, templates."""

import copy
import re
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QTabBar,
    QVBoxLayout,
)

from sldgridy.commands.blocks import AddBlockCommand
from sldgridy.commands.entities import AddEntitiesCommand, ReplaceEntitiesCommand
from sldgridy.commands.sheets import (
    AddSheetCommand,
    ChangeDocumentPropertiesCommand,
    ChangeSheetCommand,
    MoveSheetCommand,
    NavigateViewportCommand,
    RemoveSheetCommand,
)
from sldgridy.fileio.json_format import FileFormatError, block_signature
from sldgridy.fileio.paths import system_template_dir, user_template_dir
from sldgridy.fileio.templates import TEMPLATE_SUFFIX, load_frame, save_frame
from sldgridy.i18n import ui_locale
from sldgridy.model.container import EntityContainer
from sldgridy.model.document import PAGES, SHEETS, SheetLayout, new_page, new_sheet
from sldgridy.model.entities import Entity, Rectangle, Viewport, new_id
from sldgridy.model.geometry import Point
from sldgridy.model.paper import Orientation
from sldgridy.tools.base import PREVIEW_ID, Tool, tr
from sldgridy.ui.page_dialog import PageDialog
from sldgridy.ui.sheet_dialogs import FieldsDialog, FormatDialog, TemplateChooserDialog
from sldgridy.ui.space import SHEET, Space
from sldgridy.view.items import EntityItem
from sldgridy.view.sheet_items import SHEET_BACKGROUND, FrameItem, PaperItem, ViewportItem

if TYPE_CHECKING:
    from sldgridy.ui.main_window import MainWindow
    from sldgridy.ui.properties_dock import PropertiesDock

MIN_VIEWPORT_SCALE = 0.001
MAX_VIEWPORT_SCALE = 1000.0
OUTLINE_COLOR = QColor("#7b1fa2")
SCALE_PRESETS = ((2.0, "2:1"), (1.0, "1:1"), (0.5, "1:2"), (0.2, "1:5"), (0.1, "1:10"))


def format_scale(scale: float) -> str:
    if scale >= 1:
        return f"{scale:g}:1".replace(".", ui_locale().decimalPoint())
    return f"1:{1 / scale:g}".replace(".", ui_locale().decimalPoint())


def parse_scale(text: str) -> float | None:
    """'1:5', '2:1', '1:2,5' or a plain factor."""
    text = text.strip().replace(",", ".")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", text)
    try:
        value = float(m.group(1)) / float(m.group(2)) if m else float(text)
    except (ValueError, ZeroDivisionError):
        return None
    return value if MIN_VIEWPORT_SCALE <= value <= MAX_VIEWPORT_SCALE else None


class ViewportTool(Tool):
    """Two corners on the sheet; the new viewport shows the model around ``center``."""

    def __init__(self, ctx, center: Point, prompt_first: str, prompt_second: str) -> None:
        super().__init__(ctx)
        self._corner: Point | None = None
        self._center = center
        self._prompts = (prompt_first, prompt_second)

    def prompt(self) -> str:
        return self._prompts[0] if self._corner is None else self._prompts[1]

    def _viewport(self, p: Point, entity_id: str) -> Viewport | None:
        assert self._corner is not None
        if p.x == self._corner.x or p.y == self._corner.y:
            return None
        return Viewport(
            id=entity_id, layer=self.ctx.current_layer, p1=self._corner, p2=p, center=self._center
        )

    def pick(self, p: Point) -> None:
        if self._corner is None:
            self._corner = p
            return
        vp = self._viewport(p, new_id())
        if vp is not None:
            self.ctx.push(AddEntitiesCommand(self.ctx.container, [vp], tr("Ansichtsfenster")))
            self.done = True

    def preview(self) -> list[Entity]:
        if self._corner is None or self.cursor is None:
            return []
        if self.cursor.x == self._corner.x or self.cursor.y == self._corner.y:
            return []
        return [Rectangle(id=PREVIEW_ID, p1=self._corner, p2=self.cursor)]


class ViewportNavigator:
    """Wheel zoom and middle-button panning inside the active viewport."""

    def __init__(self, controller: "SheetController", space: Space, viewport_id: str) -> None:
        self.c = controller
        self.space = space
        self.viewport_id = viewport_id

    def _viewport(self) -> Viewport | None:
        container = self.space.container
        return container.get(self.viewport_id) if self.viewport_id in container else None

    def _push(self, vp: Viewport) -> None:
        self.c.w.push(
            NavigateViewportCommand(self.space.container, vp, self.c.tr("Ansicht verschieben"))
        )

    def zoom(self, factor: float, scene_pos: QPointF) -> bool:
        vp = self._viewport()
        if vp is None:
            return False
        scale = min(max(vp.scale * factor, MIN_VIEWPORT_SCALE), MAX_VIEWPORT_SCALE)
        anchor = Point(scene_pos.x(), scene_pos.y())
        m = vp.sheet_to_model(anchor)
        c = vp.sheet_center
        center = Point(m.x - (anchor.x - c.x) / scale, m.y - (anchor.y - c.y) / scale)
        self._push(replace(vp, scale=scale, center=center))
        return True

    def pan(self, delta: QPointF) -> bool:
        vp = self._viewport()
        if vp is None:
            return False
        center = Point(vp.center.x + delta.x() / vp.scale, vp.center.y + delta.y() / vp.scale)
        self._push(replace(vp, center=center))
        return True

    def deactivate(self) -> None:
        self.c.deactivate_viewport()


class SheetController(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.w = window
        self.spaces: dict[str, Space] = {}
        self.show_outlines = True
        self._navigator: ViewportNavigator | None = None
        self._updating_tabs = False
        # Multi-line diagram: the tabs show its pages instead of model and sheets.
        self.pages_mode = False
        self.tabs = QTabBar()
        self.tabs.setShape(QTabBar.Shape.RoundedSouth)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabMoved.connect(self._on_tab_moved)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        self.tabs.tabBarClicked.connect(self._on_tab_clicked)

    def tr(self, text: str) -> str:  # noqa: D102 - stable translation context
        return self.w.tr(text)

    @property
    def doc(self):
        return self.w.document

    # -- actions and menus --------------------------------------------------

    def create_actions(self) -> None:
        a = self.w._action
        self.act_new = a(self.tr("&Neues Blatt"), self.new_sheet)
        self.act_from_template = a(self.tr("Neues Blatt aus &Vorlage …"), self.new_from_template)
        self.act_rename = a(self.tr("&Umbenennen …"), self.rename_sheet)
        self.act_duplicate = a(self.tr("&Duplizieren"), self.duplicate_sheet)
        self.act_delete = a(self.tr("&Löschen"), self.delete_sheet)
        self.act_format = a(self.tr("&Format …"), self.change_format)
        self.act_fields = a(self.tr("&Schriftfeld ausfüllen …"), self.edit_fields)
        self.act_save_template = a(self.tr("Als Vorlage s&peichern …"), self.save_template)
        self.act_viewport = a(self.tr("&Ansichtsfenster zeichnen"), self.viewport_tool)
        self.act_outlines = a(self.tr("Blattumrisse im &Modell"), self._toggle_outlines)
        self.act_outlines.setCheckable(True)
        self.act_outlines.setChecked(True)
        self.sheet_only = [
            self.act_rename,
            self.act_duplicate,
            self.act_delete,
            self.act_format,
            self.act_fields,
            self.act_save_template,
            self.act_viewport,
        ]

    @property
    def kind(self) -> str:
        return PAGES if self.pages_mode else SHEETS

    def layouts(self) -> list[SheetLayout]:
        return self.doc.layouts(self.kind)

    def set_pages_mode(self, pages: bool) -> None:
        """Switch the tab bar between model + sheets and the pages of the multi-line
        diagram (with the workspace)."""
        if pages == self.pages_mode and self.tabs.count():
            return
        self.pages_mode = pages
        self.deactivate_viewport()
        self._retitle()
        if pages:
            if not self.doc.pages:
                self._add_layout(new_page())
                self.w.message(self.tr("Erste Seite des Schaltplans (MLD) angelegt"))
            current = self.current_sheet()
            if current is None or self.doc.kind_of(current.id) != PAGES:
                self.show_sheet(self.doc.pages[0].id)
        else:
            current = self.current_sheet()
            if current is not None and self.doc.kind_of(current.id) == PAGES:
                self.w.activate_space(self.w.model_view)
        self.rebuild_tabs()

    def _retitle(self) -> None:
        if not hasattr(self, "menu"):
            return
        pages = self.pages_mode
        self.menu.setTitle(self.tr("Sei&te") if pages else self.tr("Bl&att"))
        self.act_new.setText(self.tr("&Neue Seite …") if pages else self.tr("&Neues Blatt"))
        self.act_from_template.setText(
            self.tr("Neue Seite aus &Vorlage …") if pages else self.tr("Neues Blatt aus &Vorlage …")
        )
        self.act_rename.setText(
            self.tr("Seite &bearbeiten …") if pages else self.tr("&Umbenennen …")
        )
        for action in (self.act_viewport, self.act_outlines, self.align_menu.menuAction()):
            action.setVisible(not pages)

    def create_menu(self, bar: QMenuBar) -> None:
        m = bar.addMenu(self.tr("Bl&att"))
        m.addActions([self.act_new, self.act_from_template])
        m.addSeparator()
        m.addActions([self.act_rename, self.act_duplicate, self.act_delete])
        m.addSeparator()
        m.addActions([self.act_format, self.act_fields, self.act_viewport])
        m.addSeparator()
        m.addActions([self.act_save_template, self.act_outlines])
        self.align_menu = m.addMenu(self.tr("Modell auf Blatt &ausrichten"))
        self.align_menu.aboutToShow.connect(lambda: self._fill_align_menu(self.align_menu))
        self.menu = m
        self._update_actions()

    def _update_actions(self) -> None:
        current = self.current_sheet()
        on_sheet = current is not None
        for action in self.sheet_only:
            action.setEnabled(on_sheet)
        if on_sheet and self.doc.kind_of(current.id) == PAGES:
            self.act_viewport.setEnabled(False)
        else:
            self.act_delete.setEnabled(on_sheet and len(self.doc.sheets) > 1)

    def _tab_menu(self, pos) -> None:
        index = self.tabs.tabAt(pos)
        if index < 0:
            return
        if index != self.tabs.currentIndex():
            self.tabs.setCurrentIndex(index)
        menu = QMenu(self.tabs)
        first = 0 if self.pages_mode else 1
        if index == 0 and not self.pages_mode:
            self._fill_align_menu(menu)
            menu.addSeparator()
        menu.addActions([self.act_new, self.act_from_template])
        if index >= first:
            menu.addSeparator()
            menu.addActions([self.act_rename, self.act_duplicate, self.act_delete, self.act_format])
            menu.addActions([self.act_fields, self.act_save_template])
        menu.exec(self.tabs.mapToGlobal(pos))

    # -- aligning the model view on a sheet ----------------------------------

    def sheet_model_rect(self, sheet: SheetLayout) -> QRectF | None:
        """Model area all viewports of ``sheet`` show together; None without viewports."""
        rect: QRectF | None = None
        for vp in sheet.viewports():
            a, b = vp.model_rect()
            r = QRectF(a.x, a.y, b.x - a.x, b.y - a.y)
            rect = r if rect is None else rect.united(r)
        return rect

    def align_model_on(self, sheet_id: str) -> None:
        """Model view showing exactly what ``sheet_id`` shows."""
        sheet = next((s for s in self.doc.sheets if s.id == sheet_id), None)
        rect = self.sheet_model_rect(sheet) if sheet is not None else None
        if rect is None:
            return
        if self.w.space is not self.w.model_view:
            self.w.activate_space(self.w.model_view)
        self.w.canvas.fit_rect(rect, margin=0.02)

    def _fill_align_menu(self, menu: QMenu) -> None:
        """One entry per sheet: "Ausrichten auf Blatt 1", …"""
        menu.clear()
        for sheet in self.doc.sheets:
            action = menu.addAction(
                self.tr("Ausrichten auf {name}").format(name=sheet.name),
                partial(self.align_model_on, sheet.id),
            )
            action.setEnabled(self.sheet_model_rect(sheet) is not None)

    def _on_tab_clicked(self, index: int) -> None:
        # A click on the model tab while the model is shown offers the sheets.
        if self.pages_mode:
            return
        if index == 0 and self.tabs.currentIndex() == 0 and self.doc.sheets:
            QTimer.singleShot(0, self._show_align_popup)

    def _show_align_popup(self) -> None:
        from sldgridy.ui.main_window import wait_for_mouse_release

        wait_for_mouse_release()
        menu = QMenu(self.tabs)
        self._fill_align_menu(menu)
        rect = self.tabs.tabRect(0)
        menu.exec(self.tabs.mapToGlobal(rect.topLeft()) - QPoint(0, menu.sizeHint().height()))

    def _toggle_outlines(self, checked: bool) -> None:
        self.show_outlines = checked
        self.w.canvas.viewport().update()

    # -- tabs ---------------------------------------------------------------

    def tab_text(self, layout: SheetLayout) -> str:
        if self.doc.kind_of(layout.id) == PAGES:
            label = self.doc.page_label(layout.id)
            return f"{label} {layout.name}".strip()
        return layout.name

    def rebuild_tabs(self) -> None:
        current = self.current_sheet()
        self._updating_tabs = True
        try:
            while self.tabs.count():
                self.tabs.removeTab(0)
            offset = 0
            if not self.pages_mode:
                self.tabs.addTab(self.tr("Modell"))
                self.tabs.setTabData(0, None)
                offset = 1
            items = self.layouts()
            for layout in items:
                i = self.tabs.addTab(self.tab_text(layout))
                self.tabs.setTabData(i, layout.id)
            index = 0
            if current is not None and any(s.id == current.id for s in items):
                index = self.doc.layout_index(current.id) + offset
            self.tabs.setCurrentIndex(index)
        finally:
            self._updating_tabs = False
        self._update_actions()

    def _on_tab_changed(self, index: int) -> None:
        if self._updating_tabs or index < 0:
            return
        sheet_id = self.tabs.tabData(index)
        if sheet_id is None:
            if self.w.space.kind == SHEET:
                self.w.activate_space(self.w.model_view)
        elif any(s.id == sheet_id for s in self.layouts()):
            self.show_sheet(sheet_id)
        self._update_actions()

    def _on_tab_moved(self, old: int, new: int) -> None:
        if self._updating_tabs:
            return
        if self.pages_mode:
            self.w.push(
                MoveSheetCommand(self.doc, old, new, self.tr("Seite verschieben"), kind=PAGES)
            )
            return
        if old == 0 or new == 0:
            self.rebuild_tabs()  # the model tab stays first
            return
        self.w.push(MoveSheetCommand(self.doc, old - 1, new - 1, self.tr("Blatt verschieben")))

    def select_tab_for(self, space: Space) -> None:
        sheet = space.extra.get("sheet")
        if hasattr(self.w, "pages_dock"):
            self.w.pages_dock.select_page(sheet.id if sheet is not None else None)
        if sheet is not None and self.doc.kind_of(sheet.id) != self.kind:
            self._update_actions()
            return
        offset = 0 if self.pages_mode else 1
        index = 0 if sheet is None else self.doc.layout_index(sheet.id) + offset
        if self.tabs.currentIndex() != index:
            self._updating_tabs = True
            self.tabs.setCurrentIndex(index)
            self._updating_tabs = False
        self._update_actions()

    # -- spaces -------------------------------------------------------------

    def current_sheet(self) -> SheetLayout | None:
        if self.w.space.kind != SHEET:
            return None
        return self.w.space.extra["sheet"]

    def sheet_space(self, sheet_id: str) -> Space:
        space = self.spaces.get(sheet_id)
        if space is not None:
            return space
        sheet = self.doc.layout(sheet_id)

        def get_sheet(sid=sheet_id):
            return self.doc.layout(sid)

        def factory(e: Entity) -> EntityItem | None:
            if isinstance(e, Viewport):
                return ViewportItem(
                    e, self.w._resolve_style, partial(self.w.expand_with, None), lambda: self.doc
                )
            return None

        space = self.w._make_space(SHEET, sheet.entities, self.w.undo_stack, factory)
        space.extra["sheet"] = sheet
        space.extra["background"] = SHEET_BACKGROUND
        space.extra["overlay"] = None
        paper = PaperItem(get_sheet)
        frame = FrameItem(lambda: self.doc, get_sheet)
        space.scene.addItem(paper)
        space.scene.addItem(frame)
        space.extra["paper"] = paper
        space.extra["frame"] = frame
        self.spaces[sheet_id] = space
        return space

    def show_sheet(self, sheet_id: str) -> None:
        space = self.sheet_space(sheet_id)
        first = space.view is None
        self.w.activate_space(space)
        if first:
            w, h = self.doc.layout(sheet_id).size
            self.w.canvas.fit_rect(QRectF(0, 0, w, h), 0.03)

    def all_spaces(self) -> list[Space]:
        return list(self.spaces.values())

    def reset(self) -> None:
        """New document: forget all sheet spaces."""
        self.deactivate_viewport()
        for space in self.spaces.values():
            self.w._drop_space(space)
        self.spaces.clear()
        self.rebuild_tabs()

    def on_sheets_changed(self) -> None:
        ids = {s.id for s in self.doc.sheets} | {p.id for p in self.doc.pages}
        for sid in [sid for sid in self.spaces if sid not in ids]:
            space = self.spaces.pop(sid)
            if self.w.space is space:
                self.w.activate_space(self.w.model_view)
            self.w._drop_space(space)
        for sid, space in self.spaces.items():
            space.extra["sheet"] = self.doc.layout(sid)
            space.extra["paper"].refresh()
            space.extra["frame"].refresh()
        self.rebuild_tabs()
        if hasattr(self.w, "pages_dock"):
            self.w.pages_dock.rebuild()
        self.w._update_title()

    def refresh_viewports(self) -> None:
        for space in self.spaces.values():
            for item in space.sync.items():
                if isinstance(item, ViewportItem):
                    item.update()
            space.extra["frame"].update()

    # -- model overlay ------------------------------------------------------

    def model_overlay(self, painter: QPainter, scale: float) -> None:
        """Sheet outlines in the model: what each viewport shows (never printed)."""
        if not self.show_outlines:
            return
        pen = QPen(OUTLINE_COLOR, 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        font = QFont("DejaVu Sans")
        font.setPixelSize(11)
        for sheet in self.doc.sheets:
            for vp in sheet.viewports():
                a, b = vp.model_rect()
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(a.x, a.y, b.x - a.x, b.y - a.y))
                painter.save()
                painter.resetTransform()
                corner = self.w.canvas.map_from_scene_f(QPointF(a.x, a.y))
                painter.setFont(font)
                painter.setPen(OUTLINE_COLOR)
                painter.drawText(corner + QPointF(4, 14), sheet.name)
                painter.restore()

    # -- viewport activation ------------------------------------------------

    def on_empty_double_click(self, scene_pos: QPointF) -> None:
        sheet = self.current_sheet()
        if sheet is None:
            return
        p = Point(scene_pos.x(), scene_pos.y())
        hit = [vp for vp in sheet.viewports() if vp.contains(p)]
        if not hit:
            self.deactivate_viewport()
            return
        vp = hit[-1]
        if vp.locked:
            self.w.message(self.tr("Das Ansichtsfenster ist gesperrt"))
            return
        self.activate_viewport(vp.id)

    def activate_viewport(self, viewport_id: str) -> None:
        self.deactivate_viewport()
        space = self.w.space
        self._navigator = ViewportNavigator(self, space, viewport_id)
        self.w.canvas.navigator = self._navigator
        space.sync.item(viewport_id).active = True
        space.sync.item(viewport_id).update()
        self.w.message(
            self.tr("Ansichtsfenster aktiv: Mausrad zoomt, mittlere Taste verschiebt, Esc beendet")
        )

    def deactivate_viewport(self) -> None:
        nav = self._navigator
        if nav is None:
            return
        self._navigator = None
        self.w.canvas.navigator = None
        if nav.viewport_id in nav.space.container:
            item = nav.space.sync.item(nav.viewport_id)
            item.active = False
            item.update()

    @property
    def active_viewport_id(self) -> str | None:
        return self._navigator.viewport_id if self._navigator else None

    # -- properties dock ----------------------------------------------------

    def attach_properties(self, dock: "PropertiesDock") -> None:
        dock.extra_type_names[Viewport] = self.tr("Ansichtsfenster")
        dock.extra_editors.append(self._viewport_editor)

    def _viewport_editor(self, entities: list[Entity], layout: QVBoxLayout) -> None:
        if len(entities) != 1 or not isinstance(entities[0], Viewport):
            return
        vp = entities[0]
        box = QGroupBox(self.tr("Ansichtsfenster"))
        form = QFormLayout(box)
        scale = QComboBox()
        scale.setEditable(True)
        for value, label in SCALE_PRESETS:
            scale.addItem(label, value)
        scale.setCurrentText(format_scale(vp.scale))
        locked = QCheckBox(self.tr("gesperrt"))
        locked.setChecked(vp.locked)
        border = QCheckBox(self.tr("Rahmen drucken"))
        border.setChecked(vp.print_border)
        fit = QPushButton(self.tr("Modellgrenzen einpassen"))
        # Model position of the shown area's top left corner (the sheet outline in the model).
        corner = vp.model_rect()[0]
        corner_x, corner_y = QDoubleSpinBox(), QDoubleSpinBox()
        for spin, value in ((corner_x, corner.x), (corner_y, corner.y)):
            spin.setRange(-1_000_000.0, 1_000_000.0)
            spin.setDecimals(2)
            spin.setSuffix(" mm")
            spin.setKeyboardTracking(False)
            spin.setValue(value)
            spin.setEnabled(not vp.locked)
        origin = QPushButton(self.tr("Links oben auf 0,0"))
        origin.setToolTip(
            self.tr("Legt die linke obere Ecke des Blattrahmens im Modell auf den Nullpunkt")
        )
        origin.setEnabled(not vp.locked)
        corner_row = QHBoxLayout()
        corner_row.addWidget(QLabel("X"))
        corner_row.addWidget(corner_x, 1)
        corner_row.addWidget(QLabel("Y"))
        corner_row.addWidget(corner_y, 1)
        form.addRow(self.tr("Maßstab:"), scale)
        form.addRow(self.tr("Ausschnitt links oben:"), corner_row)
        form.addRow(origin)
        form.addRow(locked)
        form.addRow(border)
        form.addRow(fit)
        layout.addWidget(box)

        def apply(**changes) -> None:
            current = self.w.container.get(vp.id)
            new = replace(current, **changes)
            if new != current:
                self.w.push(
                    ReplaceEntitiesCommand(
                        self.w.container, [new], self.tr("Ansichtsfenster ändern")
                    )
                )

        def on_scale() -> None:
            value = parse_scale(scale.currentText())
            if value is None:
                self.w.message(self.tr("Ungültiger Maßstab"))
                return
            apply(scale=value)

        def move_corner(x: float, y: float) -> None:
            current = self.w.container.get(vp.id)
            hw, hh = current.width / 2 / current.scale, current.height / 2 / current.scale
            center = Point(x + hw, y + hh)
            apply(center=center)

        scale.activated.connect(lambda _i: on_scale())
        corner_x.valueChanged.connect(lambda v: move_corner(v, corner_y.value()))
        corner_y.valueChanged.connect(lambda v: move_corner(corner_x.value(), v))
        origin.clicked.connect(lambda: move_corner(0.0, 0.0))
        scale.lineEdit().returnPressed.connect(on_scale)
        locked.toggled.connect(lambda v: apply(locked=v))
        border.toggled.connect(lambda v: apply(print_border=v))
        fit.clicked.connect(lambda: self.fit_model_extents(vp.id))

    def model_extents(self) -> QRectF | None:
        rect = QRectF()
        for item in self.w.model_view.sync.items():
            if item.isVisible():
                rect = rect.united(item.sceneBoundingRect())
        return rect if not rect.isEmpty() else None

    def fit_model_extents(self, viewport_id: str) -> None:
        container = self.w.container
        vp = container.get(viewport_id)
        extents = self.model_extents()
        if extents is None:
            self.w.message(self.tr("Das Modell ist leer"))
            return
        scale = min(vp.width / extents.width(), vp.height / extents.height()) * 0.95
        center = Point(extents.center().x(), extents.center().y())
        new = replace(vp, scale=scale, center=center)
        self.w.push(ReplaceEntitiesCommand(container, [new], self.tr("Modellgrenzen einpassen")))

    # -- sheet commands -----------------------------------------------------

    def _insert_index(self, layout: SheetLayout | None = None) -> int:
        current = self.current_sheet()
        items = self.layouts()
        if current is not None and self.doc.kind_of(current.id) != self.kind:
            current = None
        if self.pages_mode and layout is not None:
            return page_insert_index(items, layout, current)
        return self.doc.layout_index(current.id) + 1 if current else len(items)

    def _add_layout(self, sheet: SheetLayout, extra_blocks=()) -> None:
        index = self._insert_index(sheet)
        text = (
            self.tr("Seite anlegen")
            if self.pages_mode
            else self.tr("Blatt {name} anlegen").format(name=sheet.name)
        )
        self.w.begin_macro(text)
        for definition in extra_blocks:
            self.w.push(AddBlockCommand(self.doc, definition, ""))
        self.w.push(AddSheetCommand(self.doc, index, sheet, "", kind=self.kind))
        self.w.end_macro()
        self.show_sheet(sheet.id)

    _add_sheet = _add_layout

    def _next_name(self) -> str:
        return self.doc.unique_sheet_name(self.tr("Blatt {n}").format(n=len(self.doc.sheets) + 1))

    def new_sheet(self) -> None:
        if self.w.blocks.in_editor():
            self.w.message(self.tr("Zuerst den Blockeditor schließen"))
            return
        if self.pages_mode:
            self.new_page()
            return
        current = self.current_sheet()
        template = current or (self.doc.sheets[0] if self.doc.sheets else None)
        sheet = new_sheet(self._next_name())
        if template is not None:
            sheet = new_sheet(self._next_name(), template.paper, template.orientation)
            sheet.title_block = template.title_block
        self._add_sheet(sheet)

    def _page_values(self, title: str, page: SheetLayout | None):
        plants = sorted({p.plant for p in self.doc.pages if p.plant})
        locations = sorted({p.location for p in self.doc.pages if p.location})
        dialog = PageDialog(
            title,
            page.plant if page else "",
            page.location if page else "",
            page.name if page else "",
            plants,
            locations,
            self.w,
        )
        if dialog.exec() != PageDialog.DialogCode.Accepted:
            return None
        return dialog.values()

    def new_page(self) -> None:
        current = self.current_sheet()
        if current is not None and self.doc.kind_of(current.id) != PAGES:
            current = None
        values = self._page_values(self.tr("Neue Seite"), current)
        if values is None:
            return
        plant, location, name = values
        page = new_page(name, plant, location)
        if current is not None:
            page.paper, page.orientation = current.paper, current.orientation
            page.title_block, page.columns = current.title_block, current.columns
        self._add_layout(page)

    def edit_page(self) -> None:
        current = self.current_sheet()
        if current is None:
            return
        values = self._page_values(self.tr("Seite bearbeiten"), current)
        if values is None:
            return
        plant, location, name = values
        changes = {
            k: v
            for k, v in (("plant", plant), ("location", location), ("name", name))
            if getattr(current, k) != v
        }
        if not changes:
            return
        self.w.begin_macro(self.tr("Seite bearbeiten"))
        if "plant" in changes or "location" in changes:
            # Joining another plant/location: the page moves to the end of that group.
            moved = replace(current, plant=plant, location=location)
            others = [p for p in self.doc.pages if p.id != current.id]
            target = page_insert_index(others, moved, None)
            old = self.doc.layout_index(current.id)
            if target != old:
                self.w.push(MoveSheetCommand(self.doc, old, target, "", kind=PAGES))
        self.w.push(ChangeSheetCommand(self.doc, current.id, "", **changes))
        self.w.end_macro()

    def duplicate_sheet(self) -> None:
        current = self.current_sheet()
        if current is None:
            return
        if self.doc.kind_of(current.id) == PAGES:
            page = replace(
                current,
                id=new_id(),
                entities=EntityContainer(e.with_new_id() for e in current.entities),
                fields=copy.deepcopy(current.fields),
            )
            self._add_layout(page)
            return
        sheet = SheetLayout(
            name=self.doc.unique_sheet_name(current.name),
            paper=current.paper,
            orientation=current.orientation,
            entities=EntityContainer(list(current.entities)),
            title_block=current.title_block,
            fields=copy.deepcopy(current.fields),
        )
        self._add_sheet(sheet)

    def rename_sheet(self) -> None:
        current = self.current_sheet()
        if current is None:
            return
        if self.doc.kind_of(current.id) == PAGES:
            self.edit_page()
            return
        name, ok = QInputDialog.getText(
            self.w, self.tr("Blatt umbenennen"), self.tr("Name:"), text=current.name
        )
        name = name.strip()
        if not ok or not name or name == current.name:
            return
        if any(s.name == name for s in self.doc.sheets):
            self.w.message(self.tr("Ein Blatt mit diesem Namen gibt es schon"))
            return
        self.w.push(
            ChangeSheetCommand(self.doc, current.id, self.tr("Blatt umbenennen"), name=name)
        )

    def delete_sheet(self) -> None:
        current = self.current_sheet()
        if current is None:
            return
        page = self.doc.kind_of(current.id) == PAGES
        if not page and len(self.doc.sheets) <= 1:
            return
        if page:
            title = self.tr("Seite löschen")
            question = self.tr("Seite „{name}“ löschen?").format(name=self.tab_text(current))
        else:
            title = self.tr("Blatt löschen")
            question = self.tr("Blatt „{name}“ löschen?").format(name=current.name)
        if QMessageBox.question(self.w, title, question) != QMessageBox.StandardButton.Yes:
            return
        self.deactivate_viewport()
        neighbours = self.layouts()
        index = self.doc.layout_index(current.id)
        self.w.push(RemoveSheetCommand(self.doc, current.id, title))
        if page:
            if self.doc.pages:
                self.show_sheet(neighbours[min(index, len(neighbours) - 1)].id)
            else:
                self.w.activate_space(self.w.model_view)

    def change_format(self) -> None:
        current = self.current_sheet()
        if current is None:
            return
        dialog = FormatDialog(
            current.paper, current.orientation, current.title_block, list(self.doc.blocks), self.w
        )
        if dialog.exec() != FormatDialog.DialogCode.Accepted:
            return
        paper, orientation, title_block = dialog.values()
        changes = {}
        if paper != current.paper:
            changes["paper"] = paper
        if orientation is not current.orientation:
            changes["orientation"] = orientation
        if title_block != current.title_block:
            changes["title_block"] = title_block
        if not changes:
            return
        self.w.push(ChangeSheetCommand(self.doc, current.id, self.tr("Blattformat"), **changes))
        self._warn_outside(current.id)

    def _warn_outside(self, sheet_id: str) -> None:
        space = self.spaces.get(sheet_id)
        sheet = self.doc.layout(sheet_id)
        if space is None:
            return
        w, h = sheet.size
        paper = QRectF(0, 0, w, h)
        outside = [
            i
            for i in space.sync.items()
            if not paper.contains(i.sceneBoundingRect().adjusted(0.5, 0.5, -0.5, -0.5))
        ]
        if outside:
            QMessageBox.warning(
                self.w,
                self.tr("Blattformat"),
                self.tr("{n} Objekte liegen ganz oder teilweise außerhalb des Blatts.").format(
                    n=len(outside)
                ),
            )

    def edit_fields(self) -> None:
        current = self.current_sheet()
        if current is None:
            return
        dialog = FieldsDialog(self.doc.properties, current.fields, current.name, self.w)
        if dialog.exec() != FieldsDialog.DialogCode.Accepted:
            return
        properties, fields = dialog.properties(), dialog.fields()
        if properties == self.doc.properties and fields == current.fields:
            return
        self.w.begin_macro(self.tr("Schriftfeld ausfüllen"))
        if properties != self.doc.properties:
            self.w.push(ChangeDocumentPropertiesCommand(self.doc, properties, ""))
        if fields != current.fields:
            self.w.push(ChangeSheetCommand(self.doc, current.id, "", fields=fields))
        self.w.end_macro()

    def viewport_tool(self) -> None:
        if self.current_sheet() is None:
            return
        extents = self.model_extents()
        center = Point(extents.center().x(), extents.center().y()) if extents else Point(0, 0)
        self.w.start_tool(
            lambda ctx: ViewportTool(
                ctx,
                center,
                self.tr("Ansichtsfenster: Erste Ecke angeben"),
                self.tr("Ansichtsfenster: Gegenüberliegende Ecke angeben"),
            )
        )

    # -- templates ----------------------------------------------------------

    def templates(self) -> list[tuple[str, Path, bool]]:
        result = []
        for directory, shipped in ((system_template_dir(), True), (user_template_dir(), False)):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob(f"*{TEMPLATE_SUFFIX}")):
                try:
                    title, _, _ = load_frame(path)
                except (OSError, FileFormatError):
                    continue
                result.append((title or path.stem, path, shipped))
        return result

    def new_from_template(self) -> None:
        if self.w.blocks.in_editor():
            self.w.message(self.tr("Zuerst den Blockeditor schließen"))
            return
        templates = self.templates()
        if not templates:
            self.w.message(self.tr("Keine Rahmenvorlagen gefunden"))
            return
        dialog = TemplateChooserDialog(templates, self.w)
        if dialog.exec() != TemplateChooserDialog.DialogCode.Accepted:
            return
        path = dialog.selected_path()
        if path is not None:
            self.add_from_template(path)

    def add_from_template(self, path: Path) -> None:
        try:
            _, sheet, blocks = load_frame(path)
        except (OSError, FileFormatError) as exc:
            QMessageBox.critical(self.w, self.tr("Rahmenvorlage"), str(exc))
            return
        sheet.name = self._next_name()
        if self.pages_mode:
            current = self.current_sheet()
            sheet.name = ""
            sheet.columns = 10
            if current is not None and self.doc.kind_of(current.id) == PAGES:
                sheet.plant, sheet.location = current.plant, current.location
            for vp in sheet.viewports():
                sheet.entities.remove(vp.id)
        missing = []
        for definition in blocks:
            existing = self.doc.blocks.get(definition.name)
            if existing is None:
                missing.append(definition)
            elif block_signature(existing) != block_signature(definition):
                self.w.message(
                    self.tr("Block {name}: die Version der Zeichnung wird verwendet").format(
                        name=definition.name
                    )
                )
        self._add_sheet(sheet, missing)

    def _orientation_name(self, orientation: Orientation) -> str:
        return self.tr("quer") if orientation is Orientation.LANDSCAPE else self.tr("hoch")

    def save_template(self) -> None:
        current = self.current_sheet()
        if current is None:
            return
        name, ok = QInputDialog.getText(
            self.w,
            self.tr("Als Vorlage speichern"),
            self.tr("Name der Vorlage:"),
            text=f"{current.paper} {self._orientation_name(current.orientation)}",
        )
        if not ok or not name.strip():
            return
        directory = user_template_dir()
        directory.mkdir(parents=True, exist_ok=True)
        default = directory / (re.sub(r"[^\w\-]+", "_", name.strip()) + TEMPLATE_SUFFIX)
        filename, _ = QFileDialog.getSaveFileName(
            self.w,
            self.tr("Rahmenvorlage speichern"),
            str(default),
            self.tr("Rahmenvorlage (*{suffix})").format(suffix=TEMPLATE_SUFFIX),
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix != TEMPLATE_SUFFIX:
            path = path.with_name(path.name + TEMPLATE_SUFFIX)
        save_frame(current, self.doc.blocks, path, name.strip())
        self.w.message(self.tr("Vorlage gespeichert: {path}").format(path=path))


def page_insert_index(
    pages: list[SheetLayout], page: SheetLayout, after: SheetLayout | None
) -> int:
    """Where a new page goes: after ``after`` when it belongs to the same plant and
    location, else behind the last page of its group, else at the end."""
    key = (page.plant, page.location)
    if after is not None and (after.plant, after.location) == key:
        ids = [p.id for p in pages]
        if after.id in ids:
            return ids.index(after.id) + 1
    last = [i for i, p in enumerate(pages) if (p.plant, p.location) == key]
    return last[-1] + 1 if last else len(pages)
