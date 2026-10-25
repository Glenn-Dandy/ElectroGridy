"""Small preview images of block definitions."""

from collections.abc import Mapping

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPalette, QPixmap

from sldgridy.model.blocks import BlockDefinition, BlockError, expand
from sldgridy.model.entities import BlockReference
from sldgridy.view.render import Style, entity_bounds, paint_entity

THUMB_LINEWEIGHT = 0.25


def block_image(name: str, blocks: Mapping[str, BlockDefinition], size: int = 64) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))  # the list shows through, light or dark
    definition = blocks.get(name)
    if definition is None:
        return image
    ref = BlockReference(id="thumb", name=name, insert=definition.base_point)
    try:
        parts = expand(ref, blocks)
    except BlockError:
        return image
    parts += definition.connection_points()
    if not parts:
        return image
    bounds = QRectF()
    for p in parts:
        bounds = bounds.united(entity_bounds(p, THUMB_LINEWEIGHT))
    if bounds.isEmpty():
        return image
    margin = 4
    scale = min(
        (size - 2 * margin) / max(bounds.width(), 1e-6),
        (size - 2 * margin) / max(bounds.height(), 1e-6),
    )
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(size / 2, size / 2)
    painter.scale(scale, scale)
    painter.translate(-bounds.center())
    style = Style(QGuiApplication.palette().color(QPalette.ColorRole.Text), THUMB_LINEWEIGHT)
    for p in parts:
        paint_entity(painter, p, style, scale)
    painter.end()
    return image


def block_icon(name: str, blocks: Mapping[str, BlockDefinition], size: int = 64) -> QIcon:
    return QIcon(QPixmap.fromImage(block_image(name, blocks, size)))
