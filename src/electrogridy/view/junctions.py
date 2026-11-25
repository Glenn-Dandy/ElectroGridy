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
CHANGED_RECTS_MAX = 64  # more changed dots at once: one update over all of them


def _dot_key(dot) -> tuple:
    center, d, color = dot
    return (center.x(), center.y(), d, color.rgba())


def _dot_rect(dot) -> QRectF:
    center, d, _color = dot
    return QRectF(center.x() - d, center.y() - d, 2 * d, 2 * d)


def _tee_key(tee) -> tuple:
    branch, weight, color = tee
    return (branch, weight, color.rgba())


def _tee_rect(tee) -> QRectF:
    branch, weight, _color = tee
    r = TEE_SIZE + weight
    p = branch.position
    return QRectF(p.x - r, p.y - r, 2 * r, 2 * r)


class JunctionItem(QGraphicsItem):
    # The dots sit on wires, which count already; the item's bounds grow with room
    # to spare and would widen "zoom to extents".
    in_extents = False

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
        # paint() draws only the dots in the exposed area (a change redraws a small part).
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
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
        self._update_changed()

    def recompute(self) -> None:
        """Everything anew, drawn again as a whole (styles or colours changed)."""
        self._pending = False
        self.prepareGeometryChange()
        self._dots, self._tees, self._bounds = self._compute()
        self.update()

    def _update_changed(self) -> None:
        """After a change of the drawing: only the dots that came or went are drawn
        again, not the whole drawing."""
        self._pending = False
        dots, tees_, bounds = self._compute()
        old = {_dot_key(d): d for d in self._dots}
        new = {_dot_key(d): d for d in dots}
        old_tees = {_tee_key(t): t for t in self._tees}
        new_tees = {_tee_key(t): t for t in tees_}
        changed = [_dot_rect(old.get(k) or new[k]) for k in old.keys() ^ new.keys()]
        changed += [
            _tee_rect(old_tees.get(k) or new_tees[k]) for k in old_tees.keys() ^ new_tees.keys()
        ]
        if not changed:
            self._dots, self._tees = dots, tees_
            return
        grown = not bounds.isEmpty() and (
            self._bounds.isEmpty() or not self._bounds.contains(bounds)
        )
        if grown:
            # The bounds only grow (with room to spare), so adding dots at the edge of
            # the drawing does not redraw everything each time.
            box = bounds if self._bounds.isEmpty() else self._bounds.united(bounds)
            room = max(box.width(), box.height(), 10.0) * 0.25
            self.prepareGeometryChange()
            self._bounds = box.adjusted(-room, -room, room, room)
        self._dots, self._tees = dots, tees_
        if len(changed) > CHANGED_RECTS_MAX:
            area = QRectF()
            for r in changed:
                area = area.united(r)
            changed = [area]
        for r in changed:
            self.update(r)

    def _compute(self):
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
        return dots, branches, bounds

    def boundingRect(self) -> QRectF:
        # Never empty: Qt redraws the whole scene for an item update with an empty rect
        # (every first dot redrew the whole view).
        return self._bounds if not self._bounds.isEmpty() else QRectF(0, 0, 1e-6, 1e-6)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        exposed = option.exposedRect
        if self._tees:
            # At least one pixel wide like the wires (minimum width on the screen).
            px = option.levelOfDetailFromTransform(painter.worldTransform())
            background = self._background()
            for tee, weight, color in self._tees:
                if not exposed.intersects(_tee_rect((tee, weight, color))):
                    continue
                weight = max(weight, 1.0 / px) if px > 0 else weight
                paint_tee(painter, tee, weight, color, background, TEE_SIZE)
        painter.setPen(Qt.PenStyle.NoPen)
        for center, d, color in self._dots:
            if not exposed.intersects(QRectF(center.x() - d, center.y() - d, 2 * d, 2 * d)):
                continue
            painter.setBrush(QBrush(color))
            painter.drawEllipse(center, d / 2, d / 2)
