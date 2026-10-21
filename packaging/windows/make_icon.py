"""Render the program icon (SVG) into a Windows .ico with the usual sizes.

Usage: python make_icon.py <icon.svg> <out.ico>   (needs PyQt6 and Pillow)
"""

import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PyQt6.QtCore import QBuffer, Qt  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main(svg: str, ico: str) -> None:
    app = QGuiApplication([])  # noqa: F841 - Qt needs it for painting
    renderer = QSvgRenderer(svg)
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    png = Image.open(io.BytesIO(bytes(buffer.data())))
    png.save(ico, sizes=[(s, s) for s in SIZES])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
