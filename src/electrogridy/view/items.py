"""QGraphicsItem wrapper around a model entity."""

from collections.abc import Callable

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker
from PyQt6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from electrogridy.model.entities import ConnectionPoint, Entity, JunctionMark, Text
from electrogridy.view.render import (
    Style,
    connection_marker_path,
    displayed,
    entity_bounds,
    entity_path,
    junction_mark_path,
    paint_entity,
    text_scene_path,
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
                stroker = QPainterPathStroker()
                stroker.setWidth(max(style.lineweight, 0.01))
                shape.addPath(stroker.createStroke(entity_path(shown)))
        self._bounds = bounds
        self._shape = shape

    def boundingRect(self) -> QRectF:
        return self._bounds

    def shape(self) -> QPainterPath:
        return self._shape

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        selected = self.isSelected()
        for part, style in zip(self._parts, self._styles, strict=True):
            if selected:
                style = Style(SELECTION_COLOR, style.lineweight, style.linetype)
            paint_entity(painter, part, style, lod)
