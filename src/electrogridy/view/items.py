"""QGraphicsItem wrapper around a model entity."""

from collections.abc import Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker
from PyQt6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from electrogridy.model.entities import ConnectionPoint, Entity, JunctionMark, Text, is_filled
from electrogridy.view.render import (
    PreparedText,
    Style,
    connection_marker_path,
    displayed,
    entity_bounds,
    entity_path,
    junction_mark_path,
    paint_entity,
    paint_prepared_text,
    prepare_text,
    screen_pen,
    stroked,
    text_scene_path,
    text_shown,
)

SELECTION_COLOR = QColor("#1e88e5")
DETAILED_PARTS = 200  # more parts than this: the item keeps a picture of itself

StyleResolver = Callable[[Entity], Style]
# Resolves compound entities (block references) into simple ones; identity otherwise.
Expander = Callable[[Entity], list[Entity]]


def _identity(e: Entity) -> list[Entity]:
    return [e]


class EntityItem(QGraphicsItem):
    def __init__(
        self, entity: Entity, resolve_style: StyleResolver, expand: Expander = _identity
    ) -> None:
        super().__init__()
        self._resolve_style = resolve_style
        self._expand = expand
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.entity = entity
        self._update_geometry()

    @property
    def entity_id(self) -> str:
        return self.entity.id

    def set_layer_state(self, visible: bool, locked: bool) -> None:
        self.setVisible(visible)
        selectable = visible and not locked
        if not selectable and self.isSelected():
            self.setSelected(False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, selectable)

    def refresh(self) -> None:
        """Style may have changed (layer properties)."""
        self.set_entity(self.entity)

    def set_entity(self, entity: Entity) -> None:
        self.prepareGeometryChange()
        self.entity = entity
        self._update_geometry()
        self.update()

    def _update_geometry(self) -> None:
        self._parts = self._expand(self.entity)
        # A detailed symbol (an imported device drawing) is drawn once into a picture
        # and reused while only the crosshair moves; zoom draws it anew.
        detailed = len(self._parts) > DETAILED_PARTS
        self.setCacheMode(
            QGraphicsItem.CacheMode.DeviceCoordinateCache
            if detailed
            else QGraphicsItem.CacheMode.NoCache
        )
        # Styles are looked up once here, not on every repaint.
        self._styles = [self._resolve_style(part) for part in self._parts]
        bounds = QRectF()
        shape = QPainterPath()
        # What paint() does: (style, path) draws a path with a pen, (style, text) a
        # prepared text, (style, part) paints the part. Neighbouring solid outlines of
        # one style share a path, so a repaint needs one pen and one drawPath for them
        # instead of one per part.
        ops: list[tuple[Style, QPainterPath | PreparedText | Entity]] = []
        for part, style in zip(self._parts, self._styles, strict=True):
            bounds = bounds.united(entity_bounds(part, style.lineweight))
            shown = displayed(part)
            if isinstance(shown, Text):
                shape.addPath(text_scene_path(shown))
            elif isinstance(shown, ConnectionPoint):
                shape.addPath(connection_marker_path(shown))
            elif isinstance(shown, JunctionMark):
                shape.addPath(junction_mark_path(shown))
            else:
                path = entity_path(shown)
                stroker = QPainterPathStroker()
                stroker.setWidth(max(style.lineweight, 0.01))
                outline = stroker.createStroke(path)
                # A filled shape is hit inside too (united: added on its own, the
                # outline band inside would cancel the area under the odd-even rule).
                shape.addPath(outline.united(path) if is_filled(shown) else outline)
            if isinstance(shown, Text):
                ops.append((style, prepare_text(shown)))
            elif not stroked(shown) or is_filled(shown):
                ops.append((style, part))
            elif (
                style.linetype == "continuous"
                and ops
                and ops[-1][0] == style
                and isinstance(ops[-1][1], QPainterPath)
            ):
                ops[-1][1].addPath(path)
            else:
                # Dashes restart at each subpath, so dashed outlines keep a path each.
                ops.append((style, QPainterPath(path)))
        self._bounds = bounds
        self._shape = shape
        self._ops = ops

    def boundingRect(self) -> QRectF:
        return self._bounds

    def shape(self) -> QPainterPath:
        return self._shape

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        selected = self.isSelected()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for style, what in self._ops:
            if selected:
                style = Style(SELECTION_COLOR, style.lineweight, style.linetype)
            if isinstance(what, QPainterPath):
                painter.setPen(screen_pen(style.color, style.lineweight, lod, style.linetype))
                painter.drawPath(what)
            elif isinstance(what, PreparedText):
                if text_shown(what.height, lod):
                    paint_prepared_text(painter, what, style.color)
            else:
                paint_entity(painter, what, style, lod)
