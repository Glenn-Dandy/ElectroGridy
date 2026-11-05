"""Photos of circuit diagrams into lines and texts: straightening, tracing, texts."""

import math

import pytest

from electrogridy.fileio import ocr
from electrogridy.model import dewarp, text_layout
from electrogridy.model.text_layout import Box
from electrogridy.model.vectorize import Ring, Stroke, frame_box, vectorize


def _ink(width, height, pixels):
    data = bytearray(width * height)
    for x, y in pixels:
        if 0 <= x < width and 0 <= y < height:
            data[y * width + x] = 1
    return bytes(data)


def test_bent_and_slanted_lines_come_out_straight():
    """Horizontal lines bowed like a sheet held at its sides, vertical ones slanted
    and converging like a sheet photographed from below: the fitted map puts every
    piece on one coordinate."""
    w, h = 900, 600
    pixels = set()

    def row(y0, x):
        # bowed the more the farther from the middle, as a sheet bent round an axis
        return y0 + 0.00012 * (x - 450) ** 2 * (y0 - 300) / 250 + 0.01 * x

    def col(x0, y):
        return x0 + (0.03 + 0.00004 * (x0 - 450)) * y

    rows = (80, 200, 330, 450, 540)
    cols = (60, 250, 460, 650, 830)
    for y0 in rows:
        for x in range(30, 870):
            y = round(row(y0, x))
            pixels |= {(x, y), (x, y + 1)}
    for x0 in cols:
        for y in range(40, 580):
            x = round(col(x0, y))
            pixels |= {(x, y), (x + 1, y)}
    warp = dewarp.estimate(w, h, _ink(w, h, pixels))
    for y0 in rows:
        vs = [warp.forward(x, row(y0, x) + 0.5)[1] for x in range(60, 840, 20)]
        assert max(vs) - min(vs) < 3.0, y0
    for x0 in cols:
        us = [warp.forward(col(x0, y) + 0.5, y)[0] for y in range(60, 560, 20)]
        assert max(us) - min(us) < 3.0, x0
    # the inverse goes back
    for x, y in ((100, 100), (450, 300), (800, 520)):
        u, v = warp.forward(x, y)
        bx, by = warp.inverse(u, v)
        assert abs(bx - x) < 0.05 and abs(by - y) < 0.05


def test_dashed_box_terminal_ring_and_diagonal_of_a_branch():
    w, h = 400, 300
    pixels = set()
    # a dashed box: dashes of 12 with gaps of 6, two pixels thick
    for x in range(40, 200):
        if (x - 40) % 18 < 12:
            pixels |= {(x, 40), (x, 41), (x, 160), (x, 161)}
    for y in range(40, 162):
        if (y - 40) % 18 < 12:
            pixels |= {(40, y), (41, y), (199, y), (200, y)}
    # a wire through a terminal (a ring of radius 7)
    for x in range(220, 380):
        pixels |= {(x, 100), (x, 101)}
    for a in range(0, 360, 2):
        x, y = 300 + 7 * math.cos(math.radians(a)), 100.5 + 7 * math.sin(math.radians(a))
        pixels |= {(round(x), round(y)), (round(x + 0.6), round(y))}
    # a branch down from a rail, joined by a short diagonal as in many plans
    for x in range(220, 380):
        pixels |= {(x, 220), (x, 221)}
    for y in range(232, 290):
        pixels |= {(260, y), (261, y)}
    for t in range(12):
        pixels |= {(260 + t, 232 - t), (261 + t, 232 - t)}
    shapes = vectorize(w, h, _ink(w, h, pixels), cap=14, stroke=2)
    strokes = [s for s in shapes if isinstance(s, Stroke)]
    rings = [s for s in shapes if isinstance(s, Ring)]
    dashed = [s for s in strokes if s.dashed]
    assert len(dashed) == 4  # the four sides
    assert any(abs(s.y1 - 40.5) < 1.5 and abs(s.x2 - s.x1) > 140 for s in dashed)
    (ring,) = rings
    assert abs(ring.cx - 300) < 1.5 and abs(ring.r - 7) < 1.5
    # the wire runs on through the ring as one line
    assert [s for s in strokes if abs(s.y1 - 100.5) < 1.5 and abs(s.x2 - s.x1) > 140]
    sloped = [s for s in strokes if abs(s.x2 - s.x1) > 4 and abs(s.y2 - s.y1) > 4]
    assert len(sloped) == 1 and 6 <= abs(sloped[0].x2 - sloped[0].x1) <= 14


def test_frame_found_and_not_the_edge_of_the_sheet():
    """The frame is drawn on paper; left of the sheet lies the darker table."""
    w, h = 600, 400
    gray = bytearray([225]) * (w * h)
    for y in range(h):
        for x in range(0, 40):
            gray[y * w + x] = 110  # the table
    pixels = set()
    for x in range(70, 570):
        pixels |= {(x, 30), (x, 31), (x, 370), (x, 371)}
    for y in range(30, 372):
        pixels |= {(70, y), (71, y), (569, y), (570, y)}
    for x in range(120, 500):  # a wire in the drawing
        pixels |= {(x, 200), (x, 201)}
    for x, y in pixels:
        gray[y * w + x] = 30
    for y in range(0, h):  # the step at the edge of the sheet comes as ink too
        pixels |= {(38, y), (39, y)}
    shapes = vectorize(w, h, _ink(w, h, pixels), cap=14, stroke=2)
    box = frame_box(shapes, w, h, bytes(gray))
    assert box is not None
    x0, y0, x1, y1 = box
    assert abs(x0 - 70.5) < 2 and abs(x1 - 569.5) < 2 and abs(y0 - 30.5) < 2 and abs(y1 - 370.5) < 2


def test_letters_of_a_strip_are_read_cell_by_cell_and_upright_lines():
    def letter(x, y, w=10, h=16):
        return Box(x, y, x + w, y + h, w * h // 3)

    # a terminal strip: digits between walls (the walls are strokes joining the
    # strip's two lines), and a word written upwards
    digits = [letter(105 + 20 * i, 102) for i in range(5)]
    walls = [Stroke(100 + 20 * i, 100, 100 + 20 * i, 120, 2) for i in range(6)]
    rails = [Stroke(100, 100, 200, 100, 2), Stroke(100, 120, 200, 120, 2)]
    upright = [letter(300, 200 + 14 * i, 16, 10) for i in range(6)]  # turned letters
    lines = text_layout.text_lines(digits + upright)
    assert {(len(line.boxes), line.upright) for line in lines} == {(5, False), (6, True)}
    cells = text_layout.split_by_walls(lines, walls + rails)
    strip = [line for line in cells if not line.upright]
    assert len(strip) == 5 and all(len(c.boxes) == 1 and c.walled for c in strip)


def test_cap_height_and_letters_coming_free_from_a_wire():
    w, h = 300, 120
    pixels = set()
    for x in range(10, 290):  # a wire
        pixels |= {(x, 60), (x, 61)}
    for k in range(4):  # four letters "I" standing on the wire, 18 high
        x0 = 40 + 30 * k
        for y in range(43, 61):
            pixels |= {(x0, y), (x0 + 1, y)}
        for x in range(x0 - 4, x0 + 6):
            pixels |= {(x, 43)}
    ink = _ink(w, h, pixels)
    _apart, pieces = text_layout.letters_apart(w, h, ink, 18)
    standing = [b for b in pieces if b.h >= 15 and b.w < 20]
    assert len(standing) == 4


def test_corrections_of_what_is_read():
    assert ocr.corrected("56.21+R01 -X52:12]") == "56.2(+R01 -X52:12)"
    assert ocr.corrected("+RO1 =NSO1/40") == "+R01 =NS01/40"
    assert ocr.corrected("6mm2 NSGAFÖU") == "6mm² NSGAFÖU"
    assert ocr.corrected("-Kl Al -G01 -Kabel") == "-K1 A1 -G01 -Kabel"
    assert ocr.corrected("Ethernet (optional]") == "Ethernet (optional)"


def _png_of(text: str, turned: bool = False) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice, QPointF
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter

    image = QImage(60 + 26 * len(text), 70, QImage.Format.Format_Grayscale8)
    image.fill(QColor("white"))
    painter = QPainter(image)
    font = QFont("DejaVu Sans")
    font.setPixelSize(32)
    painter.setFont(font)
    painter.setPen(QColor("black"))
    painter.drawText(QPointF(20, 48), text)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


@pytest.mark.skipif(not ocr.available(), reason="tesseract missing")
def test_many_small_pictures_read_side_by_side(qapp):
    jobs = [
        (_png_of("-X52:12"), 7, ""),
        (_png_of("7"), 10, "0123456789"),
        (_png_of("Relay"), 8, ""),
    ]
    seen = []
    words = ocr.read_many(jobs, done=lambda n, total: seen.append((n, total)))
    texts = [" ".join(w.text for w in ws) for ws in words]
    assert texts[1] == "7" and texts[2] == "Relay" and "X52" in texts[0]
    assert seen and seen[-1] == (3, 3)
    with pytest.raises(InterruptedError):
        ocr.read_many(jobs, done=lambda n, total: False)


def _sheet(qapp):
    """A small circuit diagram on paper, photographed a little turned and tilted."""
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF, QTransform

    plan = QImage(1600, 1000, QImage.Format.Format_RGB32)
    plan.fill(QColor("white"))
    p = QPainter(plan)
    p.setPen(QPen(QColor("black"), 3))
    p.drawRect(QRectF(60, 60, 1480, 880))  # the frame
    for y in (300, 360, 420):  # three wires
        p.drawLine(QPointF(200, y), QPointF(1300, y))
    p.drawLine(QPointF(700, 300), QPointF(700, 800))
    dash = QPen(QColor("black"), 3)
    dash.setDashPattern([5, 3.5])  # dashes and gaps as plans have them (Qt's are tighter)
    p.setPen(dash)
    p.drawRect(QRectF(900, 550, 300, 250))  # a device drawn dashed
    p.setPen(QPen(QColor("black"), 3))
    p.drawEllipse(QPointF(700, 600), 14, 14)
    font = QFont("DejaVu Sans")
    font.setPixelSize(36)
    p.setFont(font)
    p.drawText(QPointF(220, 280), "-X1")
    p.end()
    photo = QImage(1800, 1200, QImage.Format.Format_RGB32)
    photo.fill(QColor(120, 120, 120))
    quad = QPolygonF([QPointF(120, 140), QPointF(1700, 90), QPointF(1660, 1110), QPointF(90, 1080)])
    t = QTransform()
    QTransform.quadToQuad(QPolygonF(QRectF(plan.rect().toRectF())), quad, t)
    p = QPainter(photo)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setTransform(t)
    p.drawImage(0, 0, plan)
    p.end()
    return photo


def test_photo_of_a_sheet_traced_with_progress(qapp):
    from electrogridy.model.entities import Circle, Line
    from electrogridy.ui.picture_trace import Cancelled, trace_picture

    photo = _sheet(qapp)
    steps = []
    result = trace_picture(photo, 400.0, ocr.FAST, lambda f, text: steps.append(f))
    assert steps[0] == 0.0 and steps[-1] == 1.0 and steps == sorted(steps)
    lines = [e for e in result.entities if isinstance(e, Line)]
    long_h = sorted(
        (e for e in lines if abs(e.p1.y - e.p2.y) < 1e-6 and abs(e.p2.x - e.p1.x) > 150),
        key=lambda e: e.p1.y,
    )
    # the frame and the three wires, horizontal again, evenly spaced as drawn
    frame = max(abs(e.p2.x - e.p1.x) for e in long_h)
    wires = [
        e for e in long_h if not e.linetype and 0.6 * frame < abs(e.p2.x - e.p1.x) < 0.9 * frame
    ]
    assert len(wires) == 3
    assert [e for e in long_h if abs(e.p2.x - e.p1.x) > 0.95 * frame]  # top and bottom
    gaps = [wires[1].p1.y - wires[0].p1.y, wires[2].p1.y - wires[1].p1.y]
    assert abs(gaps[0] - gaps[1]) < 0.03 * gaps[0]
    assert [e for e in lines if e.linetype == "dashed"]
    assert [e for e in result.entities if isinstance(e, Circle)]
    assert result.picture is not None
    with pytest.raises(Cancelled):
        trace_picture(photo, 400.0, ocr.FAST, lambda f, text: f < 0.2)
