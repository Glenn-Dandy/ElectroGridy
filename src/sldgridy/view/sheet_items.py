"""Scene items of a sheet: paper, frame with title block, and viewports."""

from collections.abc import Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PyQt6.QtWidgets import QGraphicsItem

from sldgridy.model.document import Document, SheetLayout
from sldgridy.model.entities import Viewport
from sldgridy.view import theme
from sldgridy.view.display import SCREEN, paint_frame, paint_viewport, viewport_rect
from sldgridy.view.items import EntityItem, Expander, StyleResolver

PAPER_Z = -1e9
FRAME_Z = 1e8
SHEET_BACKGROUND = theme.LIGHT_PALETTE.sheet_background  # follows the theme on screen
ACTIVE_VIEWPORT_COLOR = QColor("#1e88e5")


class PaperItem(QGraphicsItem):
    """The sheet on the grey background (helper display)."""

    def __init__(self, sheet_getter: Callable[[], SheetLayout]) -> None:
        super().__init__()
        self._sheet = sheet_getter
        self.setZValue(PAPER_Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._rect = QRectF()
        self.refresh()

    def refresh(self) -> None:
        self.prepareGeometryChange()
        w, h = self._sheet().size
        self._rect = QRectF(0, 0, w, h)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-2, -2, 4, 4)

    @property
    def rect(self) -> QRectF:
        return self._rect

    def paint_paper(self, painter: QPainter) -> None:
        """Shadow, paper and edge; drawn by the canvas as background so that the
        grid shows on the paper too."""
        colors = theme.current
        painter.fillRect(self._rect.translated(1.5, 1.5), colors.shadow)
        painter.fillRect(self._rect, colors.paper)
        pen = QPen(colors.paper_edge, 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._rect)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pass  # see paint_paper


class FrameItem(QGraphicsItem):
    """Border, centring marks and title block, above the viewports."""

    def __init__(
        self, doc_getter: Callable[[], Document], sheet_getter: Callable[[], SheetLayout]
    ) -> None:
        super().__init__()
        self._doc = doc_getter
        self._sheet = sheet_getter
        self.setZValue(FRAME_Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._rect = QRectF()
        self.refresh()

    def refresh(self) -> None:
        self.prepareGeometryChange()
        w, h = self._sheet().size
        self._rect = QRectF(0, 0, w, h)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        paint_frame(painter, self._doc(), self._sheet(), lod, SCREEN)


class ViewportItem(EntityItem):
    """Viewport on a sheet; selectable by its border only."""

    def __init__(
        self,
        entity: Viewport,
        resolve_style: StyleResolver,
        expand: Expander,
        doc_getter: Callable[[], Document],
    ) -> None:
        self._doc = doc_getter
        self.active = False
        super().__init__(entity, resolve_style, expand)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def _update_geometry(self) -> None:
        self._parts = []
        rect = viewport_rect(self.entity)
        self._bounds = rect.adjusted(-1, -1, 1, 1)
        path = QPainterPath()
        path.addRect(rect)
        stroker = QPainterPathStroker()
        stroker.setWidth(0.5)
        self._shape = stroker.createStroke(path)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        paint_viewport(painter, self._doc(), self.entity, lod, SCREEN)
        if self.isSelected() or self.active:
            pen = QPen(ACTIVE_VIEWPORT_COLOR, 2 if self.active else 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(viewport_rect(self.entity))
