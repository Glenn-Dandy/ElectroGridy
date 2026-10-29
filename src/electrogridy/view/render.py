"""Painting of model entities with Qt. Shared by scene items, previews and later printing."""

import functools
import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)

from electrogridy.fileio.paths import fonts_dir
from electrogridy.model.entities import (
    Arc,
    AttributeDefinition,
    Busbar,
    Circle,
    ConnectionPoint,
    Entity,
    JunctionMark,
    Line,
    Polyline,
    RasterImage,
    Rectangle,
    Text,
    Wire,
)
from electrogridy.model.geometry import Point

TEXT_FONT_FAMILY = "DejaVu Sans"
# Fonts are laid out at this pixel size and scaled down to the text height in mm.
_FONT_LAYOUT_PX = 100
LINE_SPACING = 1.6  # baseline distance as a multiple of the text height
# On screen, texts smaller than this are not drawn (unreadable anyway, and text is the
# most expensive part of a big drawing). Output devices always get every text.
MIN_SCREEN_TEXT_PX = 2.0

CONNECTION_COLOR = QColor("#c000c0")
SEPARATION_COLOR = QColor("#e65100")
JUNCTION_MARK_RADIUS = 0.9  # mm
CONNECTION_RADIUS = 0.8  # mm
CONNECTION_TICK = 2.0  # mm


def ensure_text_font() -> None:
    """Load the shipped DejaVu Sans where the system has none (Windows), so that texts
    keep their width on every system. Needs a QGuiApplication."""
    if TEXT_FONT_FAMILY in QFontDatabase.families():
        return
    for path in sorted(fonts_dir().glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


# ISO 128-20 patterns in multiples of the line width d: dashed 12d/3d,
# long dash dot 24d/3d/0.5d/3d.
DASH_PATTERNS: dict[str, list[float]] = {
    "dashed": [12.0, 3.0],
    "dashdot": [24.0, 3.0, 0.5, 3.0],
}


@dataclass(frozen=True)
class Style:
    color: QColor
    lineweight: float  # mm
    linetype: str = "continuous"


def qpt(p: Point) -> QPointF:
    return QPointF(p.x, p.y)


def mpt(p: QPointF) -> Point:
    return Point(p.x(), p.y())


def entity_path(e: Entity) -> QPainterPath:
    """Outline path of a non-text entity in scene mm."""
    path = QPainterPath()
    match e:
        case Line() | Busbar():
            path.moveTo(qpt(e.p1))
            path.lineTo(qpt(e.p2))
        case Wire():
            path.moveTo(qpt(e.points[0]))
            for p in e.points[1:]:
                path.lineTo(qpt(p))
        case Polyline():
            path.moveTo(qpt(e.points[0]))
            for p in e.points[1:]:
                path.lineTo(qpt(p))
            if e.closed:
                path.closeSubpath()
        case Rectangle() | RasterImage():
            path.addRect(QRectF(qpt(e.p1), qpt(e.p2)).normalized())
        case Circle():
            path.addEllipse(qpt(e.center), e.radius, e.radius)
        case Arc():
            r = e.radius
            rect = QRectF(e.center.x - r, e.center.y - r, 2 * r, 2 * r)
            path.arcMoveTo(rect, e.start_angle)
            path.arcTo(rect, e.start_angle, e.sweep)
    return path


# -- text -----------------------------------------------------------------


@functools.cache
def _layout_font() -> QFont:
    font = QFont(TEXT_FONT_FAMILY)
    font.setPixelSize(_FONT_LAYOUT_PX)
    return font


@functools.cache
def _metrics() -> QFontMetricsF:
    """Metrics of the layout font; texts are measured often, the font never changes."""
    return QFontMetricsF(_layout_font())


@functools.lru_cache(maxsize=20000)
def _advance(line: str) -> float:
    return _metrics().horizontalAdvance(line)


def _text_scale(height: float) -> float:
    """Factor from layout pixels to mm so that capital letters are ``height`` mm tall."""
    return height / _metrics().capHeight()


def text_width(text: str, height: float) -> float:
    """Width in mm of one line of text ``height`` mm high."""
    return _advance(text) * _text_scale(height)


def _text_lines(e: Text) -> list[str]:
    return e.text.split("\n")


def _line_widths(e: Text) -> list[float]:
    k = _text_scale(e.height)
    return [_advance(line) * k for line in _text_lines(e)]


def _x_offset(e: Text, width: float) -> float:
    if e.halign == "center":
        return -width / 2
    if e.halign == "right":
        return -width
    return 0.0


def _y_offset(e: Text) -> float:
    """Shift of the first baseline relative to the anchor."""
    if e.valign == "middle":
        last = (len(_text_lines(e)) - 1) * LINE_SPACING * e.height
        return (e.height - last) / 2
    return 0.0


def text_local_rect(e: Text) -> QRectF:
    """Bounding box in the text's unrotated local frame (origin at the anchor, mm)."""
    fm = _metrics()
    k = _text_scale(e.height)
    widths = _line_widths(e)
    left = min(_x_offset(e, w) for w in widths)
    right = max(_x_offset(e, w) + w for w in widths)
    dy = _y_offset(e)
    top = dy - fm.ascent() * k
    bottom = dy + (len(widths) - 1) * LINE_SPACING * e.height + fm.descent() * k
    return QRectF(left, top, right - left, bottom - top)


def text_scene_path(e: Text) -> QPainterPath:
    """Bounding box of a text as a polygon in scene coordinates."""
    path = QPainterPath()
    path.addRect(text_local_rect(e))
    return _text_transform(e).map(path)


def _text_transform(e: Text) -> QTransform:
    t = QTransform()
    t.translate(e.position.x, e.position.y)
    t.rotate(-e.rotation)  # positive model rotation is counter-clockwise on screen
    return t


def _paint_text(painter: QPainter, e: Text, color: QColor) -> None:
    painter.save()
    painter.setTransform(_text_transform(e), combine=True)
    k = _text_scale(e.height)
    widths = _line_widths(e)
    dy = _y_offset(e)
    painter.scale(k, k)
    painter.setFont(_layout_font())
    painter.setPen(QPen(color))
    for i, (line, w) in enumerate(zip(_text_lines(e), widths, strict=True)):
        x = _x_offset(e, w) / k
        y = (dy + i * LINE_SPACING * e.height) / k
        painter.drawText(QPointF(x, y), line)
    painter.restore()


# -- painting -------------------------------------------------------------


def make_pen(
    color: QColor, lineweight: float, px_per_mm: float, linetype: str = "continuous"
) -> QPen:
    """Pen with a real mm width that is never thinner than one screen pixel.

    ``px_per_mm`` 0 disables the minimum width (used for output devices).
    """
    width = max(lineweight, 1.0 / px_per_mm) if px_per_mm > 0 else lineweight
    pen = QPen(color, width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pattern = DASH_PATTERNS.get(linetype)
    if pattern:
        # Qt scales dash patterns by the pen width; keep the mm lengths of the
        # nominal width when the pen was widened for the screen.
        k = lineweight / width
        pen.setDashPattern([max(v * k, 0.01) for v in pattern])
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    else:
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def displayed(e: Entity) -> Entity:
    """Attribute definitions show their tag outside of block references."""
    if isinstance(e, AttributeDefinition):
        return e.as_text(e.tag)
    return e


def junction_mark_path(m: JunctionMark) -> QPainterPath:
    """Small ring with a cross: marks a point where wires are explicitly not connected."""
    path = QPainterPath()
    p = qpt(m.position)
    r = JUNCTION_MARK_RADIUS
    path.addEllipse(p, r, r)
    path.moveTo(p + QPointF(-r, -r))
    path.lineTo(p + QPointF(r, r))
    path.moveTo(p + QPointF(-r, r))
    path.lineTo(p + QPointF(r, -r))
    return path


def connection_marker_path(c: ConnectionPoint) -> QPainterPath:
    path = QPainterPath()
    p = qpt(c.position)
    path.addEllipse(p, CONNECTION_RADIUS, CONNECTION_RADIUS)
    rad = math.radians(c.direction)
    path.moveTo(p)
    path.lineTo(p + QPointF(math.cos(rad), -math.sin(rad)) * CONNECTION_TICK)
    return path


@functools.lru_cache(maxsize=32)
def decoded_image(data: bytes) -> QImage:
    return QImage.fromData(data)


def _paint_image(painter: QPainter, e: RasterImage) -> None:
    """The picture in its rectangle: content mirrored first, then turned."""
    image = decoded_image(e.data)
    rect = QRectF(qpt(e.p1), qpt(e.p2)).normalized()
    upright = e.rotation % 2 == 0
    w, h = (rect.width(), rect.height()) if upright else (rect.height(), rect.width())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.translate(rect.center())
    painter.rotate(-90.0 * e.rotation)
    if e.flipped:
        painter.scale(-1.0, 1.0)
    painter.drawImage(QRectF(-w / 2, -h / 2, w, h), image)
    painter.restore()


def paint_entity(
    painter: QPainter, e: Entity, style: Style, px_per_mm: float, helpers: bool = True
) -> None:
    """Paint one simple entity. ``helpers`` False leaves out connection markers (output)."""
    if isinstance(e, JunctionMark):
        # Forced dots are drawn with the automatic ones; "separated" marks are helpers.
        if helpers and not e.connected:
            pen = QPen(SEPARATION_COLOR, 0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(junction_mark_path(e))
        return
    if isinstance(e, ConnectionPoint):
        if helpers:
            pen = QPen(CONNECTION_COLOR, 0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(connection_marker_path(e))
        return
    e = displayed(e)
    if isinstance(e, Text):
        if px_per_mm <= 0 or e.height * px_per_mm >= MIN_SCREEN_TEXT_PX:
            _paint_text(painter, e, style.color)
        return
    if isinstance(e, RasterImage):
        _paint_image(painter, e)
        return
    painter.setPen(make_pen(style.color, style.lineweight, px_per_mm, style.linetype))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(entity_path(e))


def entity_bounds(e: Entity, lineweight: float) -> QRectF:
    e = displayed(e)
    if isinstance(e, JunctionMark):
        r = JUNCTION_MARK_RADIUS * 1.5
        return QRectF(e.position.x - r, e.position.y - r, 2 * r, 2 * r)
    if isinstance(e, ConnectionPoint):
        r = CONNECTION_TICK
        return QRectF(e.position.x - r, e.position.y - r, 2 * r, 2 * r)
    if isinstance(e, Text):
        return text_scene_path(e).boundingRect()
    half = lineweight / 2
    return entity_path(e).boundingRect().adjusted(-half, -half, half, half)
