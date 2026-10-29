"""Scene item drawing the automatic wire junction dots of a container."""

from collections.abc import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QPainter
from PyQt6.QtWidgets import QGraphicsItem

from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Entity
from electrogridy.model.wires import junction_diameter, junctions
from electrogridy.view.items import StyleResolver

JUNCTION_Z = 1e9


class JunctionItem(QGraphicsItem):
    def __init__(
        self,
        container: EntityContainer,
        resolve_style: StyleResolver,
        visible: Callable[[Entity], bool],
    ) -> None:
        super().__init__()
        self._container = container
        self._resolve_style = resolve_style
        self._visible = visible
        self._dots: list[tuple[QPointF, float, object]] = []
        self._pending = False
        self._bounds = QRectF()
        self.setZValue(JUNCTION_Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        container.subscribe(self._on_change)
        self.recompute()

    def detach(self) -> None:
        self._container.unsubscribe(self._on_change)

    def _on_change(self, _event: str, _entity: Entity | None) -> None:
        # Many changes come at once (paste, open, move of a selection): compute once,
        # when control is back in the event loop.
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._flush)

    def _flush(self) -> None:
        if not self._pending:
            return
        try:
            if self.scene() is None:
                return
        except RuntimeError:  # the item is gone already
            return
        self.recompute()

    def recompute(self) -> None:
        self._pending = False
        self.prepareGeometryChange()
        dots = []
        bounds = QRectF()
        visible = [e for e in self._container if self._visible(e)]
        for p, wire in junctions(visible):
            style = self._resolve_style(wire)
            d = junction_diameter(style.lineweight)
            dots.append((QPointF(p.x, p.y), d, style.color))
            bounds = bounds.united(QRectF(p.x - d, p.y - d, 2 * d, 2 * d))
        self._dots = dots
        self._bounds = bounds
        self.update()

    def boundingRect(self) -> QRectF:
        return self._bounds

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for center, d, color in self._dots:
            painter.setBrush(QBrush(color))
            painter.drawEllipse(center, d / 2, d / 2)
