"""Reference point of a text picked on a rectangle with nine points: top, middle and
bottom, each left, centre and right (Florian 2026-11-04)."""

from PyQt6.QtCore import QCoreApplication, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from electrogridy.model.entities import Text

Anchor = tuple[str, str]  # (halign, valign) of a text
COLUMNS = ("left", "center", "right")
ROWS = ("top", "middle", "bottom")
DEFAULT_ANCHOR: Anchor = ("left", "bottom")
WIDTH, HEIGHT, MARGIN, DOT = 108, 64, 10, 5.0


def tr(text: str) -> str:
    return QCoreApplication.translate("AnchorPicker", text)


def anchor_names() -> dict[Anchor, str]:
    return {
        ("left", "top"): tr("oben links"),
        ("center", "top"): tr("oben mittig"),
        ("right", "top"): tr("oben rechts"),
        ("left", "middle"): tr("Mitte links"),
        ("center", "middle"): tr("Mitte"),
        ("right", "middle"): tr("Mitte rechts"),
        ("left", "bottom"): tr("unten links"),
        ("center", "bottom"): tr("unten mittig"),
        ("right", "bottom"): tr("unten rechts"),
    }


def shown_anchor(t: Text) -> Anchor | None:
    """Which of the nine points a text has. The older "baseline" (first baseline) is
    the bottom of a one-line text and none of the nine for several lines."""
    if t.valign == "baseline":
        return (t.halign, "bottom") if "\n" not in t.text else None
    return t.halign, t.valign


class AnchorPicker(QWidget):
    """A rectangle with nine points; a click picks one. ``None`` shows none (texts
    with different points)."""

    chosen = pyqtSignal(str, str)

    def __init__(self, anchor: Anchor | None = DEFAULT_ANCHOR, parent=None) -> None:
        super().__init__(parent)
        self._anchor = anchor
        self._hover: Anchor | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        return QSize(WIDTH, HEIGHT)

    def anchor(self) -> Anchor | None:
        return self._anchor

    def set_anchor(self, anchor: Anchor | None) -> None:
        self._anchor = anchor
        self.update()

    def _points(self) -> dict[Anchor, QPointF]:
        w, h = self.width() - 2 * MARGIN, self.height() - 2 * MARGIN
        return {
            (c, r): QPointF(MARGIN + i * w / 2, MARGIN + j * h / 2)
            for j, r in enumerate(ROWS)
            for i, c in enumerate(COLUMNS)
        }

    def _at(self, pos: QPointF) -> Anchor | None:
        key, p = min(self._points().items(), key=lambda kp: (kp[1] - pos).manhattanLength())
        return key if (p - pos).manhattanLength() <= MARGIN + DOT else None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        hover = self._at(event.position())
        if hover != self._hover:
            self._hover = hover
            self.setToolTip(anchor_names()[hover] if hover else "")
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        key = self._at(event.position())
        if key is not None and event.button() == Qt.MouseButton.LeftButton:
            self._anchor = key
            self.update()
            self.chosen.emit(*key)

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = self.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(palette.text().color(), 1))
        painter.drawRect(
            QRectF(MARGIN, MARGIN, self.width() - 2 * MARGIN, self.height() - 2 * MARGIN)
        )
        for key, p in self._points().items():
            if key == self._anchor:
                painter.setPen(QPen(palette.highlight().color(), 1.5))
                painter.setBrush(palette.highlight())
                radius = DOT + 1
            else:
                painter.setPen(QPen(palette.text().color(), 1.5 if key == self._hover else 1))
                painter.setBrush(palette.base())
                radius = DOT + (1 if key == self._hover else 0)
            painter.drawEllipse(p, radius, radius)
        painter.end()
