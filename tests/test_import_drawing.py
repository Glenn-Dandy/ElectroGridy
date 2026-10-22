"""Import of circuit diagrams: pictures, lines from pictures, lines and texts from PDFs."""

import pytest

from sldgridy.fileio import pdf_import
from sldgridy.fileio.json_format import entity_from_dict, entity_to_dict
from sldgridy.model.entities import Circle, Line, Polyline, RasterImage, Rectangle, Text
from sldgridy.model.geometry import Point
from sldgridy.model.vectorize import Ring, Stroke, vectorize


def _picture(w=40, h=20) -> RasterImage:
    return RasterImage(id="p", p1=Point(0, 0), p2=Point(w, h), data=b"\x89PNG-fake")


def test_picture_round_trip_and_transforms():
    pic = _picture()
    assert entity_from_dict(entity_to_dict(pic)) == pic
    turned = pic.rotated(Point(0, 0), 1)
    assert turned.rotation == 1 and entity_from_dict(entity_to_dict(turned)) == turned
    # Mirrored at a vertical line: flipped left to right; at a horizontal one also turned.
    assert pic.mirrored(Point(0, 0), False).flipped
    flipped = turned.mirrored(Point(0, 0), True)
    assert (flipped.rotation, flipped.flipped) == (1, True)
    assert "data" not in repr(pic)


def test_picture_scales_and_counts_for_the_bounds():
    from sldgridy.model.blocks import bounds
    from sldgridy.model.rotate import rotate_entity
    from sldgridy.model.scale import scale_entity

    pic = _picture()
    assert scale_entity(pic, Point(0, 0), 2).p2 == Point(80, 40)
    assert rotate_entity(pic, Point(0, 0), 30) is None  # only quarter turns
    assert bounds([pic]) == (0, 0, 40, 20)


def _grid(width, height, ink):
    data = bytearray(width * height)
    for x, y in ink:
        data[y * width + x] = 1
    return bytes(data)


def test_vectorize_finds_lines_slopes_and_rings():
    import math

    w, h = 200, 120
    ink = set()
    for x in range(20, 180):  # a horizontal wire, 2 px thick
        ink |= {(x, 30), (x, 31)}
    for y in range(31, 100):  # a vertical one from its middle down
        ink |= {(100, y), (101, y)}
    for t in range(40):  # a sloped blade
        ink |= {(130 + t, 60 + t // 2), (130 + t, 61 + t // 2)}
    for a in range(360):  # a circle, radius 15
        x = 50 + 15 * math.cos(math.radians(a))
        y = 80 + 15 * math.sin(math.radians(a))
        ink |= {(round(x), round(y))}
    for dx in range(3):  # a speck of lettering: ignored
        ink.add((180 + dx, 100))
    shapes = vectorize(w, h, _grid(w, h, ink), min_length=10, max_thickness=4)
    strokes = [s for s in shapes if isinstance(s, Stroke)]
    rings = [s for s in shapes if isinstance(s, Ring)]
    horizontal = [s for s in strokes if abs(s.y1 - s.y2) < 1 and abs(s.x2 - s.x1) > 100]
    vertical = [s for s in strokes if abs(s.x1 - s.x2) < 1 and abs(s.y2 - s.y1) > 50]
    sloped = [s for s in strokes if abs(s.x1 - s.x2) > 5 and abs(s.y1 - s.y2) > 5]
    assert len(horizontal) == 1 and abs(horizontal[0].y1 - 30.5) < 0.6
    # The vertical wire reaches the horizontal one.
    assert len(vertical) == 1 and abs(min(vertical[0].y1, vertical[0].y2) - 30.5) < 0.6
    assert len(sloped) == 1
    assert len(rings) == 1 and abs(rings[0].r - 15) < 1.5


def test_traced_picture_becomes_lines(qapp):
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen

    from sldgridy.ui.picture_import import picture_entity, traced

    image = QImage(800, 400, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("black"), 3))
    painter.drawLine(100, 100, 700, 100)
    painter.drawLine(400, 100, 400, 350)
    painter.end()
    lines = [e for e in traced(image, 200.0) if isinstance(e, Line)]
    long = [e for e in lines if abs(e.p2.x - e.p1.x) > 100 or abs(e.p2.y - e.p1.y) > 40]
    assert len(long) == 2
    pic = picture_entity(image, 200.0, photo=True)
    assert pic.p2 == Point(200.0, 100.0) and pic.data[:2] == b"\xff\xd8"  # JPEG


def _cad_pdf(path):
    """A small vector PDF: a box, a wire, a circle and two texts (one turned)."""
    from PyQt6.QtCore import QMarginsF, QPointF, QRectF
    from PyQt6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

    writer = QPdfWriter(str(path))
    writer.setResolution(72)  # one unit = one point
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Landscape,
            QMarginsF(0, 0, 0, 0),
        )
    )
    painter = QPainter(writer)
    pen = QPen()
    pen.setWidthF(0.7)
    painter.setPen(pen)
    painter.drawRect(QRectF(100, 100, 200, 100))
    painter.drawLine(QPointF(300, 150), QPointF(500, 150))
    painter.drawEllipse(QPointF(600, 150), 20, 20)
    font = QFont("DejaVu Sans")
    font.setPixelSize(10)
    painter.setFont(font)
    painter.drawText(QPointF(110, 90), "-Q1 B16")
    painter.save()
    painter.translate(400, 300)
    painter.rotate(-90)
    painter.drawText(QPointF(0, 0), "-W1")
    painter.restore()
    painter.end()


@pytest.mark.skipif(not pdf_import.available(), reason="pdfminer missing")
def test_lines_and_texts_from_a_cad_pdf(qapp, tmp_path):
    path = tmp_path / "plan.pdf"
    _cad_pdf(path)
    assert pdf_import.vector_count(path, 0) == 3  # box, wire, circle
    k = pdf_import.MM_PER_PT
    everything = pdf_import.page_entities(path, 0, pdf_import.Region(0, 0, 842, 595))
    texts = {e.text: e for e in everything if isinstance(e, Text)}
    assert set(texts) == {"-Q1 B16", "-W1"}
    assert texts["-W1"].rotation == 90
    assert abs(texts["-Q1 B16"].position.x - 110 * k) < 0.5
    assert any(isinstance(e, Rectangle) for e in everything)
    (circle,) = [e for e in everything if isinstance(e, Circle)]
    assert abs(circle.radius - 20 * k) < 0.2 and abs(circle.center.x - 600 * k) < 0.3
    # Only the region: the wire is cut at its edge, the box and texts outside stay out.
    part = pdf_import.page_entities(path, 0, pdf_import.Region(400, 100, 700, 250), scale=2)
    wires = [e for e in part if isinstance(e, Line | Polyline)]
    assert len(wires) == 1 and not [e for e in part if isinstance(e, Text | Rectangle)]
    (wire,) = wires
    xs = sorted([wire.p1.x, wire.p2.x]) if isinstance(wire, Line) else []
    assert xs and abs(xs[0]) < 1e-6 and abs(xs[1] - 100 * k * 2) < 0.1


def test_import_dialog_with_a_picture(qapp, tmp_path):
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen

    from sldgridy.ui.picture_import import PICTURE, TRACE, ImportDialog

    image = QImage(600, 300, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("black"), 3))
    painter.drawLine(50, 150, 550, 150)
    painter.end()
    path = tmp_path / "foto.jpg"
    image.save(str(path), "JPG", 90)
    dialog = ImportDialog(path)
    assert dialog.readable() and dialog.pages.isHidden()
    assert dialog.mode.currentData() == TRACE  # no vectors in a photo
    assert not dialog.mode.model().item(0).isEnabled()
    traced = dialog.entities()
    assert isinstance(traced[0], RasterImage) and any(isinstance(e, Line) for e in traced)
    dialog.mode.setCurrentIndex(dialog.mode.findData(PICTURE))
    (picture,) = dialog.entities()
    assert isinstance(picture, RasterImage)
    assert abs(picture.p2.x - dialog.width_mm.value()) < 1e-6


def _has_qtpdf() -> bool:
    from sldgridy.ui.picture_import import pdf_available

    return pdf_available()


@pytest.mark.skipif(not pdf_import.available() or not _has_qtpdf(), reason="QtPdf or pdfminer")
def test_import_dialog_with_a_cad_pdf(qapp, tmp_path):
    from PyQt6.QtCore import QRectF

    from sldgridy.ui.picture_import import PICTURE, VECTORS, ImportDialog

    path = tmp_path / "plan.pdf"
    _cad_pdf(path)
    dialog = ImportDialog(path)
    assert dialog.readable() and dialog.mode.currentData() == VECTORS
    assert abs(dialog.width_mm.value() - 297.0) < 0.2  # A4 landscape, 1:1
    texts = {e.text for e in dialog.entities() if isinstance(e, Text)}
    assert texts == {"-Q1 B16", "-W1"}
    # Mark the right half: the width follows, the box on the left stays out.
    scene = dialog.view.scene().sceneRect()
    dialog.view.region = QRectF(scene.width() / 2, 0, scene.width() / 2, scene.height())
    dialog._region_changed()
    assert abs(dialog.width_mm.value() - 148.5) < 0.2
    assert not [e for e in dialog.entities() if isinstance(e, Rectangle)]
    dialog.mode.setCurrentIndex(dialog.mode.findData(PICTURE))
    (picture,) = dialog.entities()
    assert isinstance(picture, RasterImage) and picture.data[:4] == b"\x89PNG"


def test_import_menu_entry_asks_for_a_file(qapp, monkeypatch):
    from sldgridy.ui import main_window
    from sldgridy.ui.main_window import MainWindow

    asked = []

    def ask(*args):
        asked.append(args)
        return "", ""

    monkeypatch.setattr(main_window.QFileDialog, "getOpenFileName", ask)
    window = MainWindow()
    window.act_import_drawing.trigger()
    assert len(asked) == 1
    window.undo_stack.setClean()
    window.close()
