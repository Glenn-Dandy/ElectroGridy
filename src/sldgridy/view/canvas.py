"""Drawing canvas: a QGraphicsView working in millimetres."""

import json
import math
from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QPen,
    QPicture,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PyQt6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from sldgridy.model.entities import BlockReference, Entity
from sldgridy.model.geometry import Point, distance, ortho, snap_to_grid
from sldgridy.model.grips import grip_kinds, grip_points
from sldgridy.model.snap import ALL_MODES, SnapHit, SnapMode, circle_hits, find_snap
from sldgridy.model.tracking import TrackLine, toggle_acquired, track
from sldgridy.tools.controller import ToolController
from sldgridy.tools.dynamic_input import DynamicInput, angle_of
from sldgridy.tools.edit import GripEditTool, MoveTool
from sldgridy.view import theme
from sldgridy.view.grid import grid_lines, visible_grid_step
from sldgridy.view.items import SELECTION_COLOR, EntityItem, StyleResolver
from sldgridy.view.render import Style, mpt, paint_entity, qpt

MM_PER_INCH = 25.4

# Practical bound of the "unbounded" model space: +/- 1 km. Keeps scroll bar
# ranges inside int32 up to MAX_ZOOM.
SCENE_EXTENT_MM = 1_000_000.0

# Zoom is relative to physical size: 1.0 shows 1 mm as 1 mm on screen.
MIN_ZOOM = 0.0005  # a 1400 px wide view shows about 740 m (large roofs, sites)
MAX_ZOOM = 50.0
WHEEL_ZOOM_STEP = 1.2

DEFAULT_GRID_SPACING_MM = 5.0
DEFAULT_SNAP_SPACING_MM = 2.5
MIN_GRID_PX = 8.0
MAJOR_GRID_EVERY = 10

ORIGIN_ARM_PX = 40.0

# Light background of the model; on screen it follows the theme (view/theme.py).
BACKGROUND_COLOR = theme.LIGHT_PALETTE.background
AXIS_X_COLOR = QColor("#d03030")
AXIS_Y_COLOR = QColor("#20a040")

WINDOW_SELECT_COLOR = QColor(30, 136, 229)
CROSSING_SELECT_COLOR = QColor(56, 142, 60)

CROSSHAIR_ARM_PX = 24.0
PICKBOX_PX = 4.0  # half size of the pick box
DRAG_THRESHOLD_PX = 3.0
SNAP_APERTURE_PX = 10.0
SNAP_MARKER_PX = 6.0
SNAP_MARKER_COLOR = QColor("#e07000")
TRACK_COLOR = QColor("#2e7d32")
ACQUIRE_DELAY_MS = 400  # hover time on a snap point before it is acquired for tracking
GRIP_PX = 4.0  # half size of a grip square
GRIP_HIT_PX = GRIP_PX + 4  # a click this close to a grip takes the grip, not the object
GRIP_HOVER_COLOR = "#e53935"
MAX_GRIP_ENTITIES = 200

# Drag and drop payload of a library block: JSON {"path": str, "name": str}.
BLOCK_MIME = "application/x-sldgridy-block"

# Characters that start typed coordinate input while the canvas has focus.
COORD_INPUT_CHARS = set("0123456789@.,;-")

# Area shown by "zoom extents" when the drawing is empty (A3 landscape).
EMPTY_EXTENTS = QRectF(0.0, 0.0, 420.0, 297.0)
INITIAL_VIEW_MS = 2000  # how long the opening view follows window size changes


def select_items(scene: QGraphicsScene, items: list) -> None:
    """Select many items with a single selectionChanged (not one per item: the
    properties dock rebuilds on each, hundreds of modules took seconds)."""
    blocked = scene.blockSignals(True)
    changed = False
    try:
        for item in items:
            if not item.isSelected():
                item.setSelected(True)
                changed = True
    finally:
        scene.blockSignals(blocked)
    if changed and not blocked:
        scene.selectionChanged.emit()
    scene.update()


class Canvas(QGraphicsView):
    """View onto a scene where 1 scene unit = 1 mm and Y points down."""

    # Snapped cursor position in scene mm.
    cursor_moved = pyqtSignal(QPointF)
    zoom_changed = pyqtSignal(float)
    entity_double_clicked = pyqtSignal(str)
    # Printable text typed while the canvas has focus (goes to the command line).
    text_typed = pyqtSignal(str)
    # A library block dropped on the canvas: payload and snapped scene position.
    block_dropped = pyqtSignal(dict, QPointF)
    # Double click where no entity is (raw scene position).
    empty_double_clicked = pyqtSignal(QPointF)
    # Right click without a running command: snapped scene point and global position.
    point_menu_requested = pyqtSignal(QPointF, QPoint)
    # Shift + right click: object snap mode menu at the global position.
    osnap_menu_requested = pyqtSignal(QPoint)

    def __init__(self, scene: QGraphicsScene | None = None, parent=None) -> None:
        super().__init__(parent)
        self._initial_view: Callable[[], None] | None = None
        # Typed length/angle (or X/Y, width/height) shown at the cursor.
        self.dynamic = DynamicInput()
        # Paper mm per real mm of the page (typed lengths are real); set by the window.
        self.drawing_scale: Callable[[], float] = lambda: 1.0
        self.dynamic_enabled = True
        self.decimal_comma = True
        # Directions snap to multiples of this angle near the cursor (0: off).
        self.polar_increment = 15.0
        self._polar_ray: tuple[Point, float] | None = None
        self._preview_blocks: dict[tuple[Entity, float], QPicture] = {}
        # The paper of the shown page (drawn as background, with the grid on it).
        self.paper_item = None
        self._layer: QPixmap | None = None
        # Switched by Settings > Fast display (off until the user switches it on).
        self.layer_cache_enabled = False
        self._layer_key_value: tuple = ()
        self._rendering_layer = False
        self._watched_scenes: list[QGraphicsScene] = []
        if scene is None:
            scene = QGraphicsScene(self)
        self.setScene(scene)
        self._prepare_scene(scene)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setCursor(Qt.CursorShape.BlankCursor)

        self._grid_visible = True
        self._grid_spacing = DEFAULT_GRID_SPACING_MM
        self.snap_enabled = True
        self.snap_spacing = DEFAULT_SNAP_SPACING_MM
        self.ortho_enabled = False
        self.osnap_enabled = True
        self.otrack_enabled = True
        self.acquired: list[Point] = []
        self._pending_drops: list[tuple[dict, QPointF]] = []
        # Entities of a block dragged from the library, placed at a point; set by the window.
        self.drag_preview: Callable[[dict, Point], list[Entity]] | None = None
        self._drag_payload: dict | None = None
        self._track_lines: tuple[TrackLine, ...] = ()
        self._hover_point: Point | None = None
        self._acquire_timer = QTimer(self)
        self._acquire_timer.setSingleShot(True)
        self._acquire_timer.setInterval(ACQUIRE_DELAY_MS)
        self._acquire_timer.timeout.connect(self._acquire_hovered)
        self.osnap_modes: frozenset[SnapMode] = ALL_MODES
        self.controller: ToolController | None = None
        self.resolve_style: StyleResolver | None = None
        # Hooks for compound entities (block references) used by object snap.
        self.snap_extra: Callable[[Entity], list[SnapHit]] | None = None
        self.snap_decompose: Callable[[Entity], list[Entity]] | None = None
        # Extra helper painting in scene coordinates (never printed).
        self.extra_overlay: Callable[[QPainter, float], None] | None = None
        # Resolves block references in previews.
        self.expand: Callable[[Entity], list[Entity]] | None = None
        # Takes over wheel zoom and middle-button panning (active sheet viewport).
        self.navigator = None
        self.background_color = BACKGROUND_COLOR
        self.show_origin = True
        self.setAcceptDrops(True)

        self._pan_last: QPointF | None = None
        self._cursor_view: QPointF | None = None  # raw mouse position in view pixels
        self._cursor_scene: QPointF | None = None  # snapped position in scene mm
        self._snap_hit: SnapHit | None = None
        self._rubber_start: QPointF | None = None
        self._rubber_end: QPointF | None = None
        # Press on a selected entity that may turn into a drag-move.
        self._drag_start: QPointF | None = None
        self._dragging = False
        # A press on a grip: dragging it and letting go places it (a click without
        # dragging keeps the click, click mode).
        self._grip_press: QPointF | None = None
        self._grip_dragging = False

        self._set_scale(1.0)

    def _prepare_scene(self, scene: QGraphicsScene) -> None:
        scene.setSceneRect(
            -SCENE_EXTENT_MM, -SCENE_EXTENT_MM, 2 * SCENE_EXTENT_MM, 2 * SCENE_EXTENT_MM
        )
        if scene not in self._watched_scenes:
            scene.changed.connect(self._invalidate_layer)
            self._watched_scenes.append(scene)
            scene.destroyed.connect(self._forget_scene)

    def _forget_scene(self, scene=None) -> None:
        self._watched_scenes = [s for s in self._watched_scenes if s is not scene]

    # -- drawing layer cache ------------------------------------------------
    # The drawing (background, grid and all items) is rendered into a pixmap that is
    # reused while only the overlays change (crosshair, snap marker, previews, rubber
    # band). It is rebuilt when the scene changes, on zoom, pan or resize.

    def _invalidate_layer(self, *_args) -> None:
        self._layer = None

    def resetCachedContent(self) -> None:  # noqa: N802 - Qt name
        self._invalidate_layer()
        super().resetCachedContent()

    def _layer_key(self) -> tuple:
        t = self.viewportTransform()
        vp = self.viewport()
        return (
            t.m11(),
            t.m12(),
            t.m21(),
            t.m22(),
            t.dx(),
            t.dy(),
            vp.width(),
            vp.height(),
            vp.devicePixelRatioF(),
        )

    def set_layer_cache_enabled(self, enabled: bool) -> None:
        self.layer_cache_enabled = enabled
        self._invalidate_layer()
        self.viewport().update()

    def paintEvent(self, event) -> None:
        if not self.layer_cache_enabled:
            super().paintEvent(event)
            return
        vp = self.viewport()
        key = self._layer_key()
        if self._layer is None or key != self._layer_key_value:
            dpr = vp.devicePixelRatioF()
            pixmap = QPixmap(max(1, round(vp.width() * dpr)), max(1, round(vp.height() * dpr)))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(theme.surface(self.background_color))
            self._rendering_layer = True
            try:
                p = QPainter(pixmap)
                self.render(
                    p,
                    QRectF(0, 0, vp.width(), vp.height()),
                    vp.rect(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                )
                p.end()
            finally:
                self._rendering_layer = False
            self._layer, self._layer_key_value = pixmap, key
        painter = QPainter(vp)
        painter.drawPixmap(0, 0, self._layer)
        painter.setRenderHints(self.renderHints())
        painter.setTransform(self.viewportTransform())
        self.drawForeground(painter, self.mapToScene(vp.rect()).boundingRect())
        painter.end()

    def set_scene(self, scene: QGraphicsScene) -> None:
        """Switch to another scene (model, sheet, block editor)."""
        self._prepare_scene(scene)
        self.setScene(scene)
        self.resetCachedContent()

    # -- coordinate helpers -------------------------------------------------

    def px_per_mm(self) -> float:
        """Screen pixels per mm at zoom 1.0."""
        return self.logicalDpiX() / MM_PER_INCH

    def zoom(self) -> float:
        return self.transform().m11() / self.px_per_mm()

    def map_to_scene_f(self, view_pos: QPointF) -> QPointF:
        """Like mapToScene, but without rounding to integer pixels."""
        inverted, _ = self.viewportTransform().inverted()
        return inverted.map(view_pos)

    def map_from_scene_f(self, scene_pos: QPointF) -> QPointF:
        return self.viewportTransform().map(scene_pos)

    # -- grid, snap and ortho ------------------------------------------------

    def grid_visible(self) -> bool:
        return self._grid_visible

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = visible
        self.resetCachedContent()
        self.viewport().update()

    def grid_spacing(self) -> float:
        return self._grid_spacing

    def set_grid_spacing(self, spacing_mm: float) -> None:
        if spacing_mm <= 0:
            raise ValueError("grid spacing must be positive")
        self._grid_spacing = spacing_mm
        self.resetCachedContent()
        self.viewport().update()

    def set_snap_spacing(self, spacing_mm: float) -> None:
        if spacing_mm <= 0:
            raise ValueError("snap spacing must be positive")
        self.snap_spacing = spacing_mm

    def set_snap_enabled(self, enabled: bool) -> None:
        self.snap_enabled = enabled

    def set_ortho_enabled(self, enabled: bool) -> None:
        self.ortho_enabled = enabled

    def set_osnap_enabled(self, enabled: bool) -> None:
        self.osnap_enabled = enabled

    # -- point input --------------------------------------------------------

    def _visible_entities_near(self, scene_pos: QPointF, radius: float) -> list[Entity]:
        rect = QRectF(scene_pos.x() - radius, scene_pos.y() - radius, 2 * radius, 2 * radius)
        items = self.scene().items(rect, Qt.ItemSelectionMode.IntersectsItemBoundingRect)
        return [i.entity for i in items if isinstance(i, EntityItem) and i.isVisible()]

    def object_snap(self, scene_pos: QPointF) -> SnapHit | None:
        if not self.osnap_enabled or not self.osnap_modes:
            return None
        aperture = SNAP_APERTURE_PX / self.transform().m11()
        entities = self._visible_entities_near(scene_pos, aperture)
        tool = self.controller.active if self.controller else None
        if tool is not None:
            entities += tool.snap_entities()  # e.g. the polyline being drawn
        ignored = tool.snap_ignored_ids() if tool is not None else set()
        if ignored:
            # E.g. while a grip is dragged: its own object would only pull it back.
            entities = [e for e in entities if e.id not in ignored]
        if not entities:
            return None
        base = self.controller.base_point() if self.controller else None
        return find_snap(
            mpt(scene_pos),
            entities,
            aperture,
            self.osnap_modes,
            extra=self.snap_extra,
            decompose=self.snap_decompose,
            base=base,
            grid=self.snap_spacing if self.snap_enabled else None,
        )

    def constrain(self, scene_pos: QPointF) -> QPointF:
        """Apply object snap, or grid snap and ortho mode, to a raw scene position."""
        self._snap_hit = self.object_snap(scene_pos)
        self._track_lines = ()
        if self._snap_hit is not None:
            return qpt(self._snap_hit.point)
        base = self.controller.base_point() if self.controller else None
        ortho_base = base if self.ortho_enabled else None
        if self.otrack_enabled and self.acquired:
            tolerance = SNAP_APERTURE_PX / self.transform().m11()
            grid = self.snap_spacing if self.snap_enabled else None
            # The command's own base point is no tracking source (ortho covers that).
            sources = [p for p in self.acquired if p != base]
            result = track(mpt(scene_pos), sources, tolerance, grid, ortho_base)
            if result is not None:
                self._track_lines = result.lines
                return qpt(result.point)
        p = mpt(scene_pos)
        if self.snap_enabled:
            p = snap_to_grid(p, self.snap_spacing)
        if ortho_base is not None:
            p = ortho(ortho_base, p)
        return qpt(p)

    # -- object snap tracking -----------------------------------------------

    def set_otrack_enabled(self, enabled: bool) -> None:
        self.otrack_enabled = enabled
        if not enabled:
            self.clear_tracking()

    def clear_tracking(self) -> None:
        self.acquired = []
        self._track_lines = ()
        self._hover_point = None
        self._acquire_timer.stop()
        self.viewport().update()

    def _watch_hover(self) -> None:
        """Start the acquire timer when the cursor rests on a new snap point."""
        if not self._picking_point():
            # Tracking only helps while a command asks for a point; idle clicks and
            # grips (e.g. on a selected wire) must not leave tracking points behind.
            if self.acquired:
                self.clear_tracking()
            self._hover_point = None
            self._acquire_timer.stop()
            return
        point = self._snap_hit.point if self._snap_hit is not None else None
        if not self.otrack_enabled or point is None:
            self._hover_point = None
            self._acquire_timer.stop()
            return
        if point != self._hover_point:
            self._hover_point = point
            self._acquire_timer.start()

    def _forget_tracking_point(self, p: Point) -> None:
        """A clicked point is never a tracking source: stop acquiring and drop it."""
        self._acquire_timer.stop()
        self._hover_point = p  # no new acquisition while resting on the clicked point
        if p in self.acquired:
            self.acquired = [q for q in self.acquired if q != p]

    def _acquire_hovered(self) -> None:
        hit = self._snap_hit
        if hit is None or hit.point != self._hover_point:
            return
        self.acquired = toggle_acquired(self.acquired, hit.point)
        self.viewport().update()

    def cursor_point(self) -> QPointF | None:
        return self._cursor_scene

    def ortho_direction(self) -> tuple[float, float] | None:
        """Unit vector from the base point towards the cursor, axis-aligned, if ortho is on."""
        if not self.ortho_enabled or self.controller is None or self._cursor_view is None:
            return None
        base = self.controller.base_point() or self.controller.last_point
        if base is None:
            return None
        raw = mpt(self.map_to_scene_f(self._cursor_view))
        dx, dy = raw.x - base.x, raw.y - base.y
        if abs(dx) >= abs(dy):
            return (1.0 if dx >= 0 else -1.0, 0.0)
        return (0.0, 1.0 if dy >= 0 else -1.0)

    def _update_cursor(self, view_pos: QPointF) -> None:
        self._cursor_view = view_pos
        if not self._tool_active() and self.grip_at(view_pos) is not None:
            # On a grip nothing else is offered: no snap marker competing with it.
            self._snap_hit = None
            self._track_lines = ()
            self._cursor_scene = self.map_to_scene_f(view_pos)
        else:
            self._cursor_scene = self.constrain(self.map_to_scene_f(view_pos))
            mode = self._dynamic_mode()
            if mode is not None:
                self.dynamic.set_mode(mode[0])
                if self.dynamic.has_input():
                    # Typed values win; the mouse only decides the remaining ones.
                    self.dynamic.scale = self.drawing_scale()
                    fixed = self.dynamic.constrain(mode[1], mpt(self._cursor_scene))
                    self._cursor_scene = qpt(fixed)
            self._polar_snap(mode)
        self._watch_hover()
        self.cursor_moved.emit(self._cursor_scene)
        if self.controller:
            self.controller.hover(mpt(self._cursor_scene))

    # -- selection ----------------------------------------------------------

    def entity_items_at(self, view_pos: QPointF) -> list[EntityItem]:
        """Selectable entity items touching the pick box around ``view_pos``, topmost first."""
        r = PICKBOX_PX
        rect = QRectF(
            self.map_to_scene_f(view_pos - QPointF(r, r)),
            self.map_to_scene_f(view_pos + QPointF(r, r)),
        ).normalized()
        items = self.scene().items(
            rect, Qt.ItemSelectionMode.IntersectsItemShape, Qt.SortOrder.DescendingOrder
        )
        return [
            i
            for i in items
            if isinstance(i, EntityItem)
            and i.isVisible()
            and i.flags() & i.GraphicsItemFlag.ItemIsSelectable
        ]

    def select_in_rect(self, rect: QRectF, crossing: bool, add: bool = False) -> None:
        """Window selection (fully inside) or crossing selection (touching)."""
        mode = (
            Qt.ItemSelectionMode.IntersectsItemShape
            if crossing
            else Qt.ItemSelectionMode.ContainsItemShape
        )
        if not add:
            self.scene().clearSelection()
        select_items(
            self.scene(),
            [
                item
                for item in self.scene().items(rect.normalized(), mode)
                if isinstance(item, EntityItem) and item.isVisible()
            ],
        )

    def _click_select(self, view_pos: QPointF, toggle: bool) -> EntityItem | None:
        items = self.entity_items_at(view_pos)
        if not items:
            return None
        item = items[0]
        if toggle:
            item.setSelected(not item.isSelected())
        elif not item.isSelected():
            self.scene().clearSelection()
            item.setSelected(True)
        return item

    def _tool_active(self) -> bool:
        return self.controller is not None and self.controller.active is not None

    def _picking_point(self) -> bool:
        """True while the active command waits for a point."""
        return self._tool_active() and not self.controller.selecting()

    def _selecting(self) -> bool:
        """True when clicks select objects (idle, or a command asking for objects)."""
        return not self._tool_active() or self.controller.selecting()

    # -- grips --------------------------------------------------------------

    def _selected_entity_items(self) -> list[EntityItem]:
        return [i for i in self.scene().selectedItems() if isinstance(i, EntityItem)]

    def _grips(self) -> list[tuple[str, int, Point]]:
        items = self._selected_entity_items()
        if not items or len(items) > MAX_GRIP_ENTITIES:
            return []
        return [
            (item.entity_id, index, p)
            for item in items
            for index, p in enumerate(grip_points(item.entity))
        ]

    def grip_at(self, view_pos: QPointF) -> tuple[str, int] | None:
        """The grip nearest to ``view_pos`` within the hit distance."""
        best, best_d = None, None
        for entity_id, index, p in self._grips():
            v = self.map_from_scene_f(qpt(p))
            dx, dy = abs(v.x() - view_pos.x()), abs(v.y() - view_pos.y())
            if dx <= GRIP_HIT_PX and dy <= GRIP_HIT_PX and (best_d is None or dx + dy < best_d):
                best, best_d = (entity_id, index), dx + dy
        return best

    # -- zoom and pan -------------------------------------------------------

    def _set_scale(self, zoom: float) -> None:
        s = zoom * self.px_per_mm()
        self.setTransform(self.transform().fromScale(s, s))

    def zoom_at(self, factor: float, view_pos: QPointF) -> None:
        """Zoom by ``factor`` keeping the scene point under ``view_pos`` fixed."""
        new_zoom = min(max(self.zoom() * factor, MIN_ZOOM), MAX_ZOOM)
        if new_zoom == self.zoom():
            return
        anchor = self.map_to_scene_f(view_pos)
        self._set_scale(new_zoom)
        self._scroll_by(self.map_from_scene_f(anchor) - view_pos)
        self.zoom_changed.emit(new_zoom)

    def set_zoom(self, zoom: float) -> None:
        center = QPointF(self.viewport().rect().center())
        self.zoom_at(zoom / self.zoom(), center)

    def center_on_point(self, scene_pos: QPointF) -> None:
        center = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        self._scroll_by(self.map_from_scene_f(scene_pos) - center)

    def fit_rect(self, rect: QRectF, margin: float = 0.05) -> None:
        """Show ``rect`` (scene mm) as large as possible with a relative margin."""
        vw, vh = self.viewport().width(), self.viewport().height()
        if rect.isEmpty() or vw <= 0 or vh <= 0:
            return
        w = rect.width() * (1 + 2 * margin)
        h = rect.height() * (1 + 2 * margin)
        zoom = min(vw / w, vh / h) / self.px_per_mm()
        self._set_scale(min(max(zoom, MIN_ZOOM), MAX_ZOOM))
        self.center_on_point(rect.center())
        self.zoom_changed.emit(self.zoom())

    def extents(self) -> QRectF:
        """Bounding box of what is visible (hidden layers do not count)."""
        rect = QRectF()
        for item in self.scene().items():
            if item.isVisible() and item.parentItem() is None:
                rect = rect.united(item.sceneBoundingRect())
        return rect

    def zoom_extents(self) -> None:
        rect = self.extents()
        self.fit_rect(rect if not rect.isEmpty() else EMPTY_EXTENTS)

    def fit_rect_top_left(self, rect: QRectF, margin_px: float = 12.0) -> None:
        """Like ``fit_rect`` but with the rectangle's top left corner in the view's top
        left corner (instead of centred)."""
        self.fit_rect(rect, margin=0.0)
        vw, vh = self.viewport().width(), self.viewport().height()
        zoom = min((vw - 2 * margin_px) / rect.width(), (vh - 2 * margin_px) / rect.height())
        self._set_scale(min(max(zoom / self.px_per_mm(), MIN_ZOOM), MAX_ZOOM))
        corner = self.map_from_scene_f(rect.topLeft())
        self._scroll_by(corner - QPointF(margin_px, margin_px))
        self.zoom_changed.emit(self.zoom())

    def set_view(self, zoom: float, center: QPointF) -> None:
        self._set_scale(min(max(zoom, MIN_ZOOM), MAX_ZOOM))
        self.center_on_point(center)
        self.zoom_changed.emit(self.zoom())

    def set_initial_view(self, apply: Callable[[], None]) -> None:
        """Show a view now and again whenever the window size still settles (maximizing,
        restoring the layout), until the user zooms, pans, clicks or types."""
        self._initial_view = apply
        apply()
        QTimer.singleShot(INITIAL_VIEW_MS, self._end_initial_view)

    def _end_initial_view(self) -> None:
        self._initial_view = None

    def end_initial_view(self) -> None:
        """A command chose the view (align, go to): keep it even if the window still
        settles."""
        self._initial_view = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._initial_view is not None:
            self._initial_view()

    def _scroll_by(self, delta: QPointF) -> None:
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() + round(delta.x()))
        v.setValue(v.value() + round(delta.y()))

    # -- events -------------------------------------------------------------

    def set_background(self, color: QColor, show_origin: bool) -> None:
        self.background_color = color
        self.show_origin = show_origin
        self.resetCachedContent()
        self.viewport().update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._initial_view = None
        steps = event.angleDelta().y() / 120.0
        if steps:
            factor = WHEEL_ZOOM_STEP**steps
            scene_pos = self.map_to_scene_f(event.position())
            if self.navigator is None or not self.navigator.zoom(factor, scene_pos):
                self.zoom_at(factor, event.position())
        event.accept()

    def mousePressEvent(self, event) -> None:
        self._initial_view = None
        pos = event.position()
        button = event.button()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if button == Qt.MouseButton.MiddleButton:
            self._pan_last = pos
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        elif button == Qt.MouseButton.LeftButton:
            self._update_cursor(pos)
            if not self._selecting():
                picked = mpt(self._cursor_scene)
                self._forget_tracking_point(picked)
                self.dynamic.clear()
                self.controller.pick(picked)
            elif not self._tool_active() and (grip := self.grip_at(pos)) is not None:
                entity_id, index = grip
                for grip_id, grip_index, p in self._grips():
                    if (grip_id, grip_index) == grip:
                        self._forget_tracking_point(p)
                self.controller.start(lambda ctx: GripEditTool(ctx, entity_id, index))
                self._grip_press, self._grip_dragging = pos, False
                self._update_cursor(pos)
            else:
                item = self._click_select(pos, shift)
                if item is None:
                    self._rubber_start = self._rubber_end = pos
                elif not shift and not self._tool_active() and item.isSelected():
                    self._drag_start = pos
        elif button == Qt.MouseButton.RightButton:
            global_pos = event.globalPosition().toPoint()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.osnap_menu_requested.emit(global_pos)
            elif self._tool_active():
                self.controller.finish()
            else:
                self._update_cursor(pos)
                self.point_menu_requested.emit(self._cursor_scene, global_pos)
        event.accept()
        self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._pan_last is not None:
            delta = self._pan_last - pos
            scale = self.transform().m11()
            if self.navigator is None or not self.navigator.pan(
                QPointF(delta.x() / scale, delta.y() / scale)
            ):
                self._scroll_by(delta)
            self._pan_last = pos
        if self._rubber_start is not None:
            self._rubber_end = pos
        if self._grip_press is not None and not self._grip_dragging:
            delta = pos - self._grip_press
            self._grip_dragging = max(abs(delta.x()), abs(delta.y())) > DRAG_THRESHOLD_PX
        if self._drag_start is not None and not self._dragging:
            delta = pos - self._drag_start
            if max(abs(delta.x()), abs(delta.y())) > DRAG_THRESHOLD_PX:
                self._begin_drag_move()
        self._update_cursor(pos)
        self.viewport().update()
        event.accept()

    def _begin_drag_move(self) -> None:
        """Turn a press on a selected entity into a move command."""
        self._dragging = True
        self._update_cursor(self._drag_start)
        self.controller.start(MoveTool)
        self.controller.pick(mpt(self._cursor_scene))

    def mouseReleaseEvent(self, event) -> None:
        button = event.button()
        pos = event.position()
        if button == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self._pan_last = None
            self.viewport().setCursor(Qt.CursorShape.BlankCursor)
        elif button == Qt.MouseButton.LeftButton:
            grip_dragged = self._grip_dragging and self._tool_active()
            self._grip_press, self._grip_dragging = None, False
            if grip_dragged:
                # Press, drag, release: the grip goes where the mouse was let go.
                self._update_cursor(pos)
                self.controller.pick(mpt(self._cursor_scene))
            elif self._dragging:
                self._update_cursor(pos)
                self.controller.pick(mpt(self._cursor_scene))
            elif self._rubber_start is not None:
                start = self._rubber_start
                self._rubber_start = self._rubber_end = None
                add = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                delta = pos - start
                if max(abs(delta.x()), abs(delta.y())) > DRAG_THRESHOLD_PX:
                    rect = QRectF(self.map_to_scene_f(start), self.map_to_scene_f(pos))
                    self.select_in_rect(rect, crossing=pos.x() < start.x(), add=add)
                elif not add and not self._tool_active():
                    self.scene().clearSelection()
            self._drag_start = None
            self._dragging = False
        event.accept()
        self.viewport().update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._tool_active():
            items = self.entity_items_at(event.position())
            if items:
                self.entity_double_clicked.emit(items[0].entity_id)
                event.accept()
                return
            self.empty_double_clicked.emit(self.map_to_scene_f(event.position()))
            event.accept()
            return
        self.mousePressEvent(event)

    @staticmethod
    def _block_payload(data) -> dict | None:
        if not data.hasFormat(BLOCK_MIME):
            return None
        try:
            payload = json.loads(bytes(data.data(BLOCK_MIME)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def dragEnterEvent(self, event) -> None:
        self._drag_payload = self._block_payload(event.mimeData())
        if self._drag_payload is not None:
            self._cursor_view = event.position()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(BLOCK_MIME):
            self._update_cursor(event.position())
            self.viewport().update()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drag_payload = None
        self._cursor_view = None
        self.viewport().update()
        event.accept()

    def _drag_preview_entities(self) -> list[Entity]:
        if self._drag_payload is None or self.drag_preview is None:
            return []
        return self.drag_preview(self._drag_payload, mpt(self._cursor_scene))

    def dropEvent(self, event) -> None:
        self._drag_payload = None
        payload = self._block_payload(event.mimeData())
        if payload is None:
            event.ignore()
            return
        self._update_cursor(event.position())
        event.acceptProposedAction()
        self.setFocus()
        # Handle the drop only after the drag has fully ended: inserting may open
        # modal dialogs and rebuild the library list (the drag source). Doing that
        # inside the drag crashes Qt's Wayland drag handling.
        self._pending_drops.append((payload, QPointF(self._cursor_scene)))
        QTimer.singleShot(0, self._emit_pending_drops)

    def _emit_pending_drops(self) -> None:
        drops, self._pending_drops = self._pending_drops, []
        for payload, point in drops:
            self.block_dropped.emit(payload, point)

    def leaveEvent(self, event) -> None:
        self._cursor_view = None
        self.viewport().update()
        super().leaveEvent(event)

    # -- typed values at the cursor -------------------------------------------

    def _polar_snap(self, mode: tuple[str, Point | None] | None) -> None:
        """With a base point: a typed length snaps onto edges it can reach (the end
        runs on a circle), otherwise the direction snaps to angle steps."""
        self._polar_ray = None
        anchor = self.controller.base_point() if self.controller else None
        if anchor is None or self._cursor_scene is None or self.ortho_enabled:
            return
        polar = mode is not None and mode[0] == "polar"
        length = self.dynamic.value("length") if polar else None
        if polar and self.dynamic.value("angle") is not None:
            return
        point = mpt(self._cursor_scene)
        aperture = SNAP_APERTURE_PX / self.transform().m11()
        if length is not None:
            # The object snap point is not on the circle; only crossings count here.
            self._snap_hit = None
            if self.osnap_enabled and length > 0:
                tool = self.controller.active
                ignored = tool.snap_ignored_ids() if tool is not None else set()
                near = [
                    e
                    for e in self._visible_entities_near(self._cursor_scene, aperture)
                    if e.id not in ignored
                ]
                parts = [
                    q
                    for e in near
                    for q in (self.snap_decompose(e) if self.snap_decompose else [e])
                ]
                hits = circle_hits(anchor, length, parts)
                if hits:
                    best = min(hits, key=lambda q: distance(q, point))
                    if distance(best, point) <= aperture:
                        self._cursor_scene = qpt(best)
                        self._snap_hit = SnapHit(best, SnapMode.INTERSECTION)
                        return
        elif self._snap_hit is not None:
            return
        if self.polar_increment <= 0:
            return
        if length is None and self.snap_enabled:
            # A grid point is exact already; steps only help a typed length or free input.
            return
        d = length if length is not None else distance(anchor, point)
        if d <= 1e-9:
            return
        a = angle_of(anchor, point)
        snapped = round(a / self.polar_increment) * self.polar_increment
        r = math.radians(snapped)
        candidate = Point(anchor.x + d * math.cos(r), anchor.y - d * math.sin(r))
        if distance(candidate, point) <= aperture:
            self._cursor_scene = qpt(candidate)
            self._polar_ray = (anchor, snapped % 360)

    def _draw_polar_ray(self, painter: QPainter) -> None:
        if self._polar_ray is None:
            return
        anchor, angle = self._polar_ray
        r = math.radians(angle)
        reach = 4000.0 / self.transform().m11()
        end = QPointF(anchor.x + reach * math.cos(r), anchor.y - reach * math.sin(r))
        pen = QPen(TRACK_COLOR, 0, Qt.PenStyle.DotLine)
        pen.setCosmetic(True)
        painter.save()
        painter.setPen(pen)
        painter.drawLine(qpt(anchor), end)
        painter.restore()

    def _dynamic_mode(self) -> tuple[str, Point | None] | None:
        if not self.dynamic_enabled or self.controller is None:
            return None
        return self.controller.dynamic_mode()

    def set_dynamic_enabled(self, enabled: bool) -> None:
        self.dynamic_enabled = enabled
        self.dynamic.clear()
        self.viewport().update()

    def event(self, event) -> bool:
        # Tab moves between the fields instead of moving the keyboard focus.
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Tab
            and self._dynamic_mode() is not None
        ):
            self.dynamic.set_mode(self._dynamic_mode()[0])
            self.dynamic.next_field()
            self.viewport().update()
            return True
        return super().event(event)

    def _dynamic_key(self, event: QKeyEvent) -> bool:
        """Typing into the fields at the cursor; True if the key was used."""
        mode = self._dynamic_mode()
        if mode is None or event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        # The fields follow the tool (X/Y before the first point, then length/angle)
        # before the key is used; otherwise the first digit after a click got lost.
        self.dynamic.set_mode(mode[0])
        key, text = event.key(), event.text()
        if key == Qt.Key.Key_Backspace and self.dynamic.has_input():
            self.dynamic.backspace()
        elif (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.dynamic.has_input()
            and mode[0] in ("factor", "scale_start")
            and self.dynamic.value("factor") is not None
        ):
            value = self.dynamic.value("factor")
            if mode[0] == "scale_start" and self.dynamic.has_point():
                # Typed X/Y as well: that is the base point.
                raw = self.map_to_scene_f(self._cursor_view) if self._cursor_view else QPointF()
                self.controller.pick(self.dynamic.constrain(None, mpt(self._cursor_scene or raw)))
            if self.controller.typed_value("factor", value):
                self.dynamic.clear()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.dynamic.has_input():
            raw = self.map_to_scene_f(self._cursor_view) if self._cursor_view else QPointF()
            self.dynamic.scale = self.drawing_scale()
            point = self.dynamic.constrain(mode[1], mpt(self._cursor_scene or raw))
            self.dynamic.clear()
            self._forget_tracking_point(point)
            self.controller.hover(point)
            self.controller.pick(point)
        elif key == Qt.Key.Key_Escape and self.dynamic.has_input():
            self.dynamic.clear()
        elif text and self.dynamic.type(text):
            pass
        else:
            return False
        if mode[0] in ("factor", "scale_start"):
            self.controller.typed_changed("factor", self.dynamic.value("factor"))
        if self._cursor_view is not None:
            self._update_cursor(self._cursor_view)
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self._initial_view = None
        if self._dynamic_key(event):
            event.accept()
            self.viewport().update()
            return
        key = event.key()
        controller = self.controller
        text = event.text()
        if key == Qt.Key.Key_Escape:
            if self.acquired:
                self.clear_tracking()
            if self._tool_active():
                controller.cancel()
            elif self.navigator is not None:
                self.navigator.deactivate()
            else:
                self._rubber_start = self._rubber_end = None
                self.scene().clearSelection()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._tool_active():
                controller.finish()
        elif key == Qt.Key.Key_Space:
            if self._tool_active():
                controller.finish()
            elif controller is not None:
                controller.repeat()
        elif (
            text
            and text in COORD_INPUT_CHARS
            and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self.text_typed.emit(text)
        else:
            super().keyPressEvent(event)
            return
        event.accept()
        self.viewport().update()

    # -- helper display (never printed) -------------------------------------

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, theme.surface(self.background_color))
        paper = self.paper_item
        if paper is not None:
            paper.paint_paper(painter)
            if self._grid_visible:
                painter.save()
                painter.setClipRect(paper.rect)
                self._draw_grid(painter, rect.intersected(paper.rect))
                painter.restore()
        elif self._grid_visible:
            self._draw_grid(painter, rect)
        if self.show_origin:
            self._draw_origin(painter)

    def _draw_grid(self, painter: QPainter, rect: QRectF) -> None:
        scale = self.transform().m11()
        step = visible_grid_step(self._grid_spacing, scale, MIN_GRID_PX)
        major = step * MAJOR_GRID_EVERY
        xs = grid_lines(rect.left(), rect.right(), step)
        ys = grid_lines(rect.top(), rect.bottom(), step)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        colors = theme.current
        for color, want_major in ((colors.grid_minor, False), (colors.grid_major, True)):
            pen = QPen(color, 0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for x in xs:
                if _is_multiple(x, major) == want_major:
                    painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            for y in ys:
                if _is_multiple(y, major) == want_major:
                    painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.restore()

    def _draw_origin(self, painter: QPainter) -> None:
        # Draw in view pixels so the marker keeps its screen size.
        o = self.map_from_scene_f(QPointF(0.0, 0.0))
        arm = ORIGIN_ARM_PX
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        font = QFont(painter.font())
        font.setPixelSize(11)
        painter.setFont(font)
        for color, end, label, label_pos in (
            (AXIS_X_COLOR, QPointF(o.x() + arm, o.y()), "X", QPointF(o.x() + arm + 3, o.y() + 4)),
            (AXIS_Y_COLOR, QPointF(o.x(), o.y() + arm), "Y", QPointF(o.x() - 4, o.y() + arm + 13)),
        ):
            pen = QPen(color, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(o, end)
            painter.drawText(label_pos, label)
        painter.setPen(QPen(theme.current.origin_box, 1))
        painter.drawRect(QRectF(o.x() - 3, o.y() - 3, 6, 6))
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self._rendering_layer:
            return
        scale = self.transform().m11()
        if self.extra_overlay is not None:
            self.extra_overlay(painter, scale)
        if self.controller is not None:
            base = self.controller.base_point()
            if base is not None and self._cursor_scene is not None:
                pen = QPen(theme.current.rubber_line, 0, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawLine(qpt(base), self._cursor_scene)
            previews = self.controller.preview()
            if not previews:
                self._preview_blocks.clear()  # block definitions may change between commands
            simple: list[Entity] = []
            for e in previews:
                if isinstance(e, BlockReference) and self.expand is not None:
                    self._paint_block_preview(painter, e, scale)
                else:
                    simple += self.expand(e) if self.expand is not None else [e]
            self._paint_preview(painter, simple, scale)
        self._paint_preview(painter, self._drag_preview_entities(), scale)
        if not self._tool_active():
            self._draw_grips(painter)
        self._draw_rubber_band(painter)
        self._draw_tracking(painter)
        self._draw_snap_marker(painter)
        self._draw_polar_ray(painter)
        self._draw_crosshair(painter)
        self._draw_dynamic_input(painter)

    def _paint_block_preview(self, painter: QPainter, ref: BlockReference, scale: float) -> None:
        """A block in the preview: recorded once at the origin, then only replayed
        shifted (moving hundreds of modules stays fluid)."""
        key = (replace(ref, id="", insert=Point(0.0, 0.0)), scale)
        picture = self._preview_blocks.get(key)
        if picture is None:
            if len(self._preview_blocks) > 2000:
                self._preview_blocks.clear()
            parts = self.expand(key[0]) if self.expand is not None else [key[0]]
            picture = QPicture()
            recorder = QPainter(picture)
            recorder.setRenderHints(painter.renderHints())
            self._paint_preview(recorder, parts, scale)
            recorder.end()
            self._preview_blocks[key] = picture
        painter.drawPicture(QPointF(ref.insert.x, ref.insert.y), picture)

    def _paint_preview(self, painter: QPainter, entities: list[Entity], scale: float) -> None:
        for e in entities:
            if self.resolve_style:
                style = self.resolve_style(e)
                style = Style(theme.current.preview, style.lineweight, style.linetype)
            else:
                style = Style(theme.current.preview, 0.25)
            paint_entity(painter, e, style, scale)

    def _draw_grips(self, painter: QPainter) -> None:
        grips = self._grips()
        if not grips:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#0d47a1"), 1))
        r = GRIP_PX
        kinds = {item.entity_id: grip_kinds(item.entity) for item in self._selected_entity_items()}
        hovered = self.grip_at(self._cursor_view) if self._cursor_view is not None else None
        for entity_id, index, p in grips:
            v = self.map_from_scene_f(qpt(p))
            if (entity_id, index) == hovered:
                # The grip a click would take: drawn bigger and red.
                painter.setBrush(QBrush(QColor(GRIP_HOVER_COLOR)))
                h = GRIP_PX + 2
                painter.drawRect(QRectF(v.x() - h, v.y() - h, 2 * h, 2 * h))
                continue
            entity_kinds = kinds.get(entity_id, [])
            kind = entity_kinds[index] if index < len(entity_kinds) else "point"
            if kind == "label":
                # Diamond: drags the label along the wire.
                painter.setBrush(QBrush(QColor("#ff9800")))
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                d = r + 1
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(v.x(), v.y() - d),
                            QPointF(v.x() + d, v.y()),
                            QPointF(v.x(), v.y() + d),
                            QPointF(v.x() - d, v.y()),
                        ]
                    )
                )
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            else:
                # Hollow squares shift a segment, filled ones move a point.
                painter.setBrush(
                    QBrush(QColor("#ffffff") if kind == "segment" else SELECTION_COLOR)
                )
                painter.drawRect(QRectF(v.x() - r, v.y() - r, 2 * r, 2 * r))
        painter.restore()

    def _draw_tracking(self, painter: QPainter) -> None:
        if not self.otrack_enabled or (not self.acquired and not self._track_lines):
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        vp = self.viewport().rect()
        pen = QPen(TRACK_COLOR, 1, Qt.PenStyle.DotLine)
        painter.setPen(pen)
        for line in self._track_lines:
            o = self.map_from_scene_f(qpt(line.origin))
            if line.vertical:
                painter.drawLine(QPointF(o.x(), vp.top()), QPointF(o.x(), vp.bottom()))
            else:
                painter.drawLine(QPointF(vp.left(), o.y()), QPointF(vp.right(), o.y()))
        painter.setPen(QPen(TRACK_COLOR, 2))
        r = 5
        for p in self.acquired:
            c = self.map_from_scene_f(qpt(p))
            painter.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
            painter.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        painter.restore()

    def _draw_snap_marker(self, painter: QPainter) -> None:
        hit = self._snap_hit
        if hit is None or self._cursor_view is None:
            return
        c = self.map_from_scene_f(qpt(hit.point))
        r = SNAP_MARKER_PX
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(SNAP_MARKER_COLOR, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        x, y = c.x(), c.y()
        match hit.mode:
            case SnapMode.ENDPOINT:
                painter.drawRect(QRectF(x - r, y - r, 2 * r, 2 * r))
            case SnapMode.MIDPOINT:
                painter.drawPolygon(
                    QPolygonF([QPointF(x, y - r), QPointF(x + r, y + r), QPointF(x - r, y + r)])
                )
            case SnapMode.CENTER:
                painter.drawEllipse(c, r, r)
            case SnapMode.INSERTION:
                # Two overlapping squares: where a text is anchored.
                h = r * 0.7
                painter.drawRect(QRectF(x - r, y - r, r + h, r + h))
                painter.drawRect(QRectF(x - h, y - h, r + h, r + h))
            case SnapMode.INTERSECTION:
                painter.drawLine(QPointF(x - r, y - r), QPointF(x + r, y + r))
                painter.drawLine(QPointF(x - r, y + r), QPointF(x + r, y - r))
            case SnapMode.NEAREST:
                # Hourglass: a free point on the object.
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(x - r, y - r),
                            QPointF(x + r, y - r),
                            QPointF(x - r, y + r),
                            QPointF(x + r, y + r),
                        ]
                    )
                )
            case SnapMode.CONNECTION:
                painter.drawEllipse(c, r, r)
                painter.drawLine(QPointF(x - r, y), QPointF(x + r, y))
                painter.drawLine(QPointF(x, y - r), QPointF(x, y + r))
        painter.restore()

    def _draw_rubber_band(self, painter: QPainter) -> None:
        if self._rubber_start is None or self._rubber_end is None:
            return
        crossing = self._rubber_end.x() < self._rubber_start.x()
        color = CROSSING_SELECT_COLOR if crossing else WINDOW_SELECT_COLOR
        painter.save()
        painter.resetTransform()
        pen = QPen(color, 1, Qt.PenStyle.DashLine if crossing else Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        fill = QColor(color)
        fill.setAlpha(40)
        painter.setBrush(QBrush(fill))
        painter.drawRect(QRectF(self._rubber_start, self._rubber_end).normalized())
        painter.restore()

    def _draw_dynamic_input(self, painter: QPainter) -> None:
        """Boxes with length and angle (or X/Y, width/height) next to the rubber band."""
        mode = self._dynamic_mode()
        if mode is None or self._cursor_scene is None or self._cursor_view is None:
            return
        name, anchor = mode
        self.dynamic.set_mode(name)  # the tool may have changed since the last mouse move
        point = mpt(self._cursor_scene)
        self.dynamic.scale = self.drawing_scale()
        shown = self.dynamic.shown(anchor, point, self.decimal_comma)
        cur = self.map_from_scene_f(self._cursor_scene)
        boxes: dict[str, QPointF] = {}
        if name == "polar" and anchor is not None:
            a = self.map_from_scene_f(qpt(anchor))
            mid = (a + cur) / 2
            dx, dy = cur.x() - a.x(), cur.y() - a.y()
            norm = max((dx * dx + dy * dy) ** 0.5, 1e-9)
            # The length sits on the line, the angle next to the start point.
            boxes["length"] = mid
            boxes["angle"] = a + QPointF(-dy / norm, dx / norm) * 26 + QPointF(dx, dy) / norm * 26
        elif name == "factor":
            boxes["factor"] = cur + QPointF(60, 26)
        elif name == "size" and anchor is not None:
            a = self.map_from_scene_f(qpt(anchor))
            boxes["width"] = QPointF((a.x() + cur.x()) / 2, cur.y() + 16)
            boxes["height"] = QPointF(cur.x() + 34, (a.y() + cur.y()) / 2)
        elif name == "scale_start":
            boxes["factor"] = cur + QPointF(60, 26)
            boxes["x"] = cur + QPointF(52, 48)
            boxes["y"] = cur + QPointF(52, 70)
        else:
            boxes["x"] = cur + QPointF(52, 26)
            boxes["y"] = cur + QPointF(52, 48)
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for field, center in boxes.items():
            label = shown[field]
            if field in ("x", "y"):
                label = f"{field.upper()}  {label}"
            elif field == "factor":
                label = self.tr("Faktor  {value}").format(value=label)
            w = metrics.horizontalAdvance(label) + 12
            h = metrics.height() + 6
            rect = QRectF(center.x() - w / 2, center.y() - h / 2, w, h)
            typed = bool(self.dynamic.texts.get(field))
            active = field == self.dynamic.active_name
            painter.setPen(
                QPen(QColor("#1e88e5") if active else QColor("#8a8a8a"), 2 if active else 1)
            )
            colors = theme.current
            painter.setBrush(QBrush(colors.field_typed if typed else colors.field))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(colors.field_text)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
        painter.restore()

    def _draw_crosshair(self, painter: QPainter) -> None:
        if self._cursor_view is None or self._cursor_scene is None or self._pan_last is not None:
            return
        c = self.map_from_scene_f(self._cursor_scene)
        arm = CROSSHAIR_ARM_PX
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(theme.current.crosshair, 1))
        painter.drawLine(QPointF(c.x() - arm, c.y()), QPointF(c.x() + arm, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - arm), QPointF(c.x(), c.y() + arm))
        if self._selecting():
            r = PICKBOX_PX
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
        painter.restore()


def _is_multiple(value: float, step: float) -> bool:
    q = value / step
    return abs(q - round(q)) < 1e-6
