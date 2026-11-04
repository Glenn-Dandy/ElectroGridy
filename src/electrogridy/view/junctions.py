"""Scene item drawing the automatic wire junction dots of a container."""

from collections.abc import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import QGraphicsItem

from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Entity
from electrogridy.model.wires import TEE_SIZE, junction_diameter, junctions, tees
from electrogridy.view.items import StyleResolver
from electrogridy.view.render import paint_tee

JUNCTION_Z = 1e9


class JunctionItem(QGraphicsItem):
    def __init__(
        self,
        container: EntityContainer,
        resolve_style: StyleResolver,
        visible: Callable[[Entity], bool],
        tee_style: Callable[[], bool] = lambda: False,
        background: Callable[[], QColor] = lambda: QColor("white"),
    ) -> None:
        super().__init__()
        self._container = container
        self._resolve_style = resolve_style
        self._visible = visible
        self._tee_style = tee_style
        self._background = background
        self._dots: list[tuple[QPointF, float, object]] = []
        self._tees: list[tuple[object, float, object]] = []
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
        branches = []
        if self._tee_style():
            found, branched = tees(visible)
        else:
            found, branched = junctions(visible), []
        for p, wire in found:
            style = self._resolve_style(wire)
            d = junction_diameter(style.lineweight)
            dots.append((QPointF(p.x, p.y), d, style.color))
            bounds = bounds.united(QRectF(p.x - d, p.y - d, 2 * d, 2 * d))
        for tee in branched:
            style = self._resolve_style(tee.wire)
            branches.append((tee, style.lineweight, style.color))
            r = TEE_SIZE + style.lineweight
            p = tee.position
            bounds = bounds.united(QRectF(p.x - r, p.y - r, 2 * r, 2 * r))
        self._dots = dots
        self._tees = branches
        self._bounds = bounds
        self.update()

    def boundingRect(self) -> QRectF:
        return self._bounds

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self._tees:
            # At least one pixel wide like the wires (minimum width on the screen).
            px = option.levelOfDetailFromTransform(painter.worldTransform())
            background = self._background()
            for tee, weight, color in self._tees:
                weight = max(weight, 1.0 / px) if px > 0 else weight
                paint_tee(painter, tee, weight, color, background, TEE_SIZE)
        painter.setPen(Qt.PenStyle.NoPen)
        for center, d, color in self._dots:
            painter.setBrush(QBrush(color))
            painter.drawEllipse(center, d / 2, d / 2)
