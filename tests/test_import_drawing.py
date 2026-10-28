"""Import of circuit diagrams: pictures, lines from pictures, lines and texts from PDFs."""

import pytest

from sldgridy.fileio import ocr, pdf_import
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
    for t in range(40):  # a sloped blade from the vertical wire
        ink |= {(102 + t, 60 + t // 2), (102 + t, 61 + t // 2)}
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


def test_vectorize_joins_pieces_finds_dashes_and_drops_lettering():
    w, h = 300, 120
    ink = set()
    for x in range(20, 160):  # one wire drawn as two overlapping pieces a pixel apart
        ink |= {(x, 20), (x, 21)}
    for x in range(140, 280):
        ink |= {(x, 21), (x, 22)}
    for x in range(20, 280):  # dashes 12 long, gaps 6
        if (x - 20) % 18 < 12:
            ink |= {(x, 60), (x, 61)}
    for y in range(90, 103):  # a letter E, away from everything
        ink.add((150, y))
    for x in range(150, 162):
        ink |= {(x, 90), (x, 96), (x, 102)}
    shapes = vectorize(w, h, _grid(w, h, ink), min_length=10, max_thickness=4)
    wire = [s for s in shapes if abs(s.y1 - 21) < 2]
    assert len(wire) == 1 and wire[0].x1 == 20 and wire[0].x2 >= 278 and not wire[0].dashed
    (dashes,) = [s for s in shapes if abs(s.y1 - 60.5) < 2]
    assert dashes.dashed and dashes.x2 - dashes.x1 > 240
    assert not [s for s in shapes if s.y1 > 80]


def test_reading_texts_from_tesseract_output():
    from sldgridy.fileio import ocr

    head = "\t".join(
        [
            "level",
            "page_num",
            "block_num",
            "par_num",
            "line_num",
            "word_num",
            "left",
            "top",
            "width",
            "height",
            "conf",
            "text",
        ]
    )
    rows = [
        (1, 1, 1, 100, 50, 60, 20, 96, "Switch"),
        (1, 1, 1, 165, 50, 40, 20, 90, "-YO4"),
        (1, 1, 1, 400, 50, 40, 20, 92, "OC"),  # far off: a label of its own
        (1, 1, 1, 445, 50, 40, 20, 91, "24V"),
        (2, 1, 1, 100, 200, 10, 20, 70, "il"),  # a bit of a line
        (3, 1, 1, 100, 300, 12, 20, 95, "“8"),
    ]
    tsv = "\n".join(
        [head, "1\t1\t0\t0\t0\t0\t0\t0\t800\t600\t-1\t"]
        + [
            f"5\t1\t{b}\t{p}\t{n}\t1\t{x}\t{y}\t{w}\t{hh}\t{c}\t{t}"
            for b, p, n, x, y, w, hh, c, t in rows
        ]
    )
    lines = ocr.text_lines(ocr.parse_tsv(tsv))
    texts = {line.text: line for line in lines}
    assert set(texts) == {"Switch -Y04", "DC 24V", "8"}
    switch = texts["Switch -Y04"]
    assert (switch.left, switch.baseline, switch.cap_height) == (100, 70, 20)
    assert ocr.corrected("-Kl Al -G01 -Kabel") == "-K1 A1 -G01 -Kabel"


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
    assert dialog.paper.text() == "A4 quer (297 × 210 mm)"
    texts = {e.text for e in dialog.entities() if isinstance(e, Text)}
    assert texts == {"-Q1 B16", "-W1"}
    # Mark the right half: the width follows, the box on the left stays out.
    scene = dialog.view.scene().sceneRect()
    dialog.view.region = QRectF(scene.width() / 2, 0, scene.width() / 2, scene.height())
    dialog.view.region_changed.emit()
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


def test_dark_background_and_slanted_photo(qapp):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

    from sldgridy.ui.picture_import import traced, unslanted

    image = QImage(800, 400, QImage.Format.Format_RGB32)
    image.fill(QColor("black"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("white"), 3))  # a dark screen
    painter.drawLine(100, 100, 700, 100)
    painter.drawLine(400, 100, 400, 350)
    painter.end()
    lines = [e for e in traced(image, 200.0) if isinstance(e, Line)]
    assert len([e for e in lines if abs(e.p2.x - e.p1.x) > 100 or abs(e.p2.y - e.p1.y) > 40]) == 2
    # A sheet photographed at a slant: its corners stretched back to a rectangle.
    photo = QImage(600, 400, QImage.Format.Format_RGB32)
    photo.fill(QColor("white"))
    sheet = [QPointF(100, 50), QPointF(500, 80), QPointF(480, 350), QPointF(120, 330)]
    painter = QPainter(photo)
    painter.setPen(QPen(QColor("black"), 1))
    painter.setBrush(QColor("black"))
    painter.drawPolygon(QPolygonF(sheet))
    painter.end()
    straight = unslanted(photo, sheet)
    assert abs(straight.width() - 390) < 15 and abs(straight.height() - 275) < 15
    dark = sum(
        QColor(straight.pixel(x, y)).value() < 100
        for x in range(5, straight.width() - 5, 10)
        for y in range(5, straight.height() - 5, 10)
    )
    total = len(range(5, straight.width() - 5, 10)) * len(range(5, straight.height() - 5, 10))
    assert dark == total


def test_marked_region_keeps_the_scale(qapp, tmp_path):
    """Whole sheet or only the drawing inside: same size in the drawing (1.3.2.dev4 kept
    the width of the whole sheet for a smaller region and enlarged it)."""
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtTest import QTest

    from sldgridy.ui.picture_import import PICTURE_WIDTH, ImportDialog

    image = QImage(600, 300, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    path = tmp_path / "plan.png"
    image.save(str(path))
    dialog = ImportDialog(path)
    dialog.show()
    view = dialog.view

    def drag(x1, x2):
        a = view.mapFromScene(QPointF(x1, 50))
        b = view.mapFromScene(QPointF(x2, 250))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(view.viewport(), b)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)

    assert dialog.width_mm.value() == pytest.approx(PICTURE_WIDTH)
    drag(150, 450)  # the middle half
    assert dialog.width_mm.value() == pytest.approx(PICTURE_WIDTH / 2, abs=1)
    dialog.width_mm.setValue(PICTURE_WIDTH)  # typed: twice as large
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(10, 10))  # all
    assert dialog.width_mm.value() == pytest.approx(2 * PICTURE_WIDTH, abs=2)
    dialog.close()


def test_import_dialog_corners_can_be_dragged(qapp, tmp_path):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtTest import QTest

    from sldgridy.ui.picture_import import PICTURE, ImportDialog

    image = QImage(600, 300, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    path = tmp_path / "foto.png"
    image.save(str(path))
    dialog = ImportDialog(path)
    dialog.show()
    view = dialog.view
    assert view.movable_corners and not view.slanted()
    corner = view.mapFromScene(view.quad[1])  # top right
    target = corner + QPoint(-40, 30)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(view.viewport(), target)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert view.slanted() and view.quad[0] == view.scene().sceneRect().topLeft()
    dialog.mode.setCurrentIndex(dialog.mode.findData(PICTURE))
    (picture,) = dialog.entities()
    assert picture.p2.y / picture.p2.x != 300 / 600  # stretched from the moved corners
    dialog.close()


@pytest.mark.skipif(not ocr.available(), reason="tesseract missing")
def test_traced_picture_reads_texts(qapp):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

    from sldgridy.ui.picture_import import traced

    image = QImage(1200, 600, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("black"), 3))
    painter.drawRect(300, 150, 500, 250)
    painter.drawLine(800, 275, 1100, 275)
    font = QFont("DejaVu Sans")
    font.setPixelSize(28)
    painter.setFont(font)
    painter.drawText(QPointF(320, 200), "Switch -Y04")
    painter.save()
    painter.translate(1000, 560)
    painter.rotate(-90)
    painter.drawText(QPointF(0, 0), "Versorgung")
    painter.restore()
    painter.end()
    out = traced(image, 300.0)
    texts = {e.text: e for e in out if isinstance(e, Text)}
    # How sure tesseract is of "-Y04" differs between its versions; "Switch" it reads.
    (switch,) = [e for t, e in texts.items() if t.startswith("Switch")]
    assert texts["Versorgung"].rotation == 90 and switch.rotation == 0
    assert abs(switch.position.x - 80) < 2 and abs(switch.position.y - 50) < 2  # 320/4, 200/4
    assert abs(switch.height - 5) < 1.5  # capitals of 28 px type, a quarter mm per pixel
    # The letters do not come as lines; the box and the wire do.
    lines = [e for e in out if isinstance(e, Line)]
    assert not [e for e in lines if 80 < e.p1.x < 140 and 40 < e.p1.y < 52]
    assert len([e for e in lines if abs(e.p2.x - e.p1.x) > 50 or abs(e.p2.y - e.p1.y) > 50]) >= 5
