"""A photographed or scanned circuit diagram turned into lines, circles and texts.

Steps (each reported to ``progress``, which may stop the work):

1. straighten: the sheet's own long lines give the perspective and the bending
   (``model.dewarp``); the picture is drawn straight in cells, once at working size
   (longer side ``WORK_SIDE``) and once at full size for reading;
2. graphics: rings and lines of the whole ink (``model.vectorize``);
3. texts, read two ways: tesseract's own layout over the page (three directions),
   and our lines of letters (``model.text_layout``) cut out one by one and read as a
   single character, a word or a line; where both read the same place the surer one
   wins, the cells of a terminal strip always go to ours;
4. lines again from the ink without the texts, cut to the drawing frame.
"""

import math
import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QBuffer, QCoreApplication, QIODevice, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform

from electrogridy.fileio import ocr
from electrogridy.model import dewarp, text_layout
from electrogridy.model.entities import Circle, Entity, Line, Text, new_id
from electrogridy.model.geometry import Point
from electrogridy.model.vectorize import (
    Ring,
    Stroke,
    circles,
    frame_box,
    inside,
    stroke_width,
    vectorize,
)

WORK_SIDE = 4096  # pixels of the longer side the lines are found on
CELL = 48  # pixels of a cell of the straight picture drawn in one go
OCR_CAP = 32  # pixels of capitals handed to tesseract
SINGLE = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+-"
SURE = 70.0  # confidence above which an upright line is not read the other way round


def tr(text: str) -> str:
    return QCoreApplication.translate("PictureTrace", text)


class Cancelled(Exception):
    """The user stopped the work."""


@dataclass
class Found:
    """A text read, in pixels of the working picture."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float  # height of the capitals
    rotation: int  # 0, 90 (reads upwards) or 270 (downwards)
    confidence: float
    walled: bool = False  # a cell of a strip, cut out of a longer line
    baseline: float | None = None  # where tesseract saw it (across: y, upright: x)


@dataclass
class TraceResult:
    entities: list[Entity] = field(default_factory=list)
    picture: QImage | None = None  # the straightened picture, as wide as the entities
    seconds: dict[str, float] = field(default_factory=dict)


def _picture_tools():
    # picture_import imports this module; its helpers are taken when needed
    from electrogridy.ui import picture_import

    return picture_import


# -- straightening ------------------------------------------------------------------


def scaled_to(image: QImage, side: int) -> QImage:
    k = side / max(1, image.width(), image.height())
    if k >= 1:
        return image
    return image.scaled(
        round(image.width() * k),
        round(image.height() * k),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def drawn_straight(
    image: QImage, warp, k: float, out_w: int, out_h: int, x0: float, y0: float
) -> QImage:
    """``image`` (``k`` times the size the warp was fitted on) drawn straight: output
    pixel (X, Y) shows the picture point whose (u, v) is (x0 + X / k, y0 + Y / k).
    Each cell is a perspective piece of the picture (quadToQuad)."""
    out = QImage(max(1, out_w), max(1, out_h), QImage.Format.Format_RGB32)
    out.fill(QColor("white"))
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    nx, ny = -(-out_w // CELL), -(-out_h // CELL)
    grid: dict[tuple[int, int], tuple[float, float]] = {}
    for j in range(ny + 1):
        start = grid.get((0, j - 1))
        for i in range(nx + 1):
            u, v = x0 + min(i * CELL, out_w) / k, y0 + min(j * CELL, out_h) / k
            grid[i, j] = warp.inverse(u, v, grid.get((i - 1, j)) or start)
    bounds = QRectF(image.rect().toRectF())
    for j in range(ny):
        for i in range(nx):
            X0, Y0 = i * CELL, j * CELL
            X1, Y1 = min(X0 + CELL, out_w), min(Y0 + CELL, out_h)
            src = QPolygonF(
                [
                    QPointF(grid[i, j][0] * k, grid[i, j][1] * k),
                    QPointF(grid[i + 1, j][0] * k, grid[i + 1, j][1] * k),
                    QPointF(grid[i + 1, j + 1][0] * k, grid[i + 1, j + 1][1] * k),
                    QPointF(grid[i, j + 1][0] * k, grid[i, j + 1][1] * k),
                ]
            )
            dst = QPolygonF([QPointF(X0, Y0), QPointF(X1, Y0), QPointF(X1, Y1), QPointF(X0, Y1)])
            t = QTransform()
            if not QTransform.quadToQuad(src, dst, t):
                continue
            box = src.boundingRect().adjusted(-2, -2, 2, 2).intersected(bounds)
            if box.isEmpty():
                continue
            painter.resetTransform()
            painter.setClipRect(QRectF(X0, Y0, X1 - X0, Y1 - Y0))
            painter.setTransform(t)
            painter.drawImage(box.topLeft(), image, box)
    painter.end()
    return out


def straight_pictures(image: QImage) -> tuple[QImage, QImage]:
    """The picture straightened at working size and at full size (grey)."""
    pi = _picture_tools()
    work = scaled_to(image, WORK_SIDE)
    w, h, data = pi.ink(work)
    warp = dewarp.estimate(w, h, data)
    corners = [warp.forward(x, y) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
    u0, u1 = min(c[0] for c in corners), max(c[0] for c in corners)
    v0, v1 = min(c[1] for c in corners), max(c[1] for c in corners)
    out_w, out_h = round(u1 - u0), round(v1 - v0)
    straight = drawn_straight(work, warp, 1.0, out_w, out_h, u0, v0)
    k = image.width() / work.width()
    if abs(k - 1) < 1e-6:
        full = straight
    else:
        full = drawn_straight(image, warp, k, round(out_w * k), round(out_h * k), u0, v0)
    return straight, full.convertToFormat(QImage.Format.Format_Grayscale8)


# -- reading lines of letters ---------------------------------------------------------


def _png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class Cropper:
    """Lines of letters cut from the full picture, black on white: a narrow band along
    the line; strokes much longer than its letters and rings in it painted out; a
    short group (up to three letters) shows only its own letters."""

    def __init__(self, full: QImage, k: float, strokes: list[Stroke], rings: list[Ring]):
        pi = _picture_tools()
        self.k = k
        self.dark = pi.darkness(full)
        _w, _h, sample = pi._gray_bytes(pi.limited(self.dark, 1500))
        self.t = max(20, int(pi._threshold(sample) * 0.6))
        self.strokes = strokes
        self.rings = rings

    def crop(self, line: text_layout.TextLine, turn: int) -> QImage:
        pi = _picture_tools()
        k, size = self.k, line.size
        along, across = 0.6 * size, 0.15 * size + 1
        if line.upright:
            bx0, bx1, by0, by1 = (
                line.x0 - across,
                line.x1 + across,
                line.y0 - along,
                line.y1 + along,
            )
        else:
            bx0, bx1, by0, by1 = (
                line.x0 - along,
                line.x1 + along,
                line.y0 - across,
                line.y1 + across,
            )
        x0, y0 = max(0, int(bx0 * k)), max(0, int(by0 * k))
        x1 = min(self.dark.width(), math.ceil(bx1 * k))
        y1 = min(self.dark.height(), math.ceil(by1 * k))
        part = self.dark.copy(QRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))).convertToFormat(
            QImage.Format.Format_RGB32
        )
        painter = QPainter(part)
        paper = QColor("black")  # in the darkness picture paper is black
        for s in self.strokes:
            if math.hypot(s.x2 - s.x1, s.y2 - s.y1) < 2.5 * size:
                continue
            if max(s.x1, s.x2) * k < x0 or min(s.x1, s.x2) * k > x1:
                continue
            if max(s.y1, s.y2) * k < y0 or min(s.y1, s.y2) * k > y1:
                continue
            pen = QPen(paper, (s.thickness + 2) * k)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(s.x1 * k - x0, s.y1 * k - y0), QPointF(s.x2 * k - x0, s.y2 * k - y0)
            )
        if len(line.boxes) <= 3:
            keep = QPainterPath()
            g = 0.12 * size + 1
            for b in line.boxes:
                keep.addRect(
                    QRectF(
                        (b.x0 - g) * k - x0,
                        (b.y0 - g) * k - y0,
                        (b.x1 - b.x0 + 2 * g) * k,
                        (b.y1 - b.y0 + 2 * g) * k,
                    )
                )
            outside = QPainterPath()
            outside.addRect(QRectF(0, 0, part.width(), part.height()))
            painter.fillPath(outside.subtracted(keep), paper)
        for ring in self.rings:
            if bx0 - ring.r <= ring.cx <= bx1 + ring.r and by0 - ring.r <= ring.cy <= by1 + ring.r:
                painter.setPen(QPen(paper, max(3.0, 0.35 * ring.r * k)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(
                    QPointF(ring.cx * k - x0, ring.cy * k - y0), ring.r * k, ring.r * k
                )
        painter.end()
        scale = OCR_CAP / max(1.0, size * k)
        part = part.scaled(
            max(1, round(part.width() * scale)),
            max(1, round(part.height() * scale)),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if turn:
            part = part.transformed(QTransform().rotate(turn))
        w, h, values = pi._gray_bytes(part.convertToFormat(QImage.Format.Format_Grayscale8))
        t = self.t
        table = bytes(
            255 - round(255 * min(1.0, max(0.0, (v - 0.5 * t) / (0.9 * t)))) for v in range(256)
        )
        clean = QImage(values.translate(table), w, h, w, QImage.Format.Format_Grayscale8).copy()
        pad = 14
        out = QImage(w + 2 * pad, h + 2 * pad, QImage.Format.Format_Grayscale8)
        out.fill(255)
        painter = QPainter(out)
        painter.drawImage(pad, pad, clean)
        painter.end()
        return out


def _plausible(text: str, conf: float) -> bool:
    letters = sum(c.isalnum() for c in text)
    if not letters:
        return False
    if len(text) == 1:
        return text.isalnum() and conf >= 80 and text not in "Il|"
    if len(text) == 2:
        return conf >= 75 and not (text.isalpha() and text.islower())
    return conf >= 55 or (conf >= 40 and letters >= 5)


def _share(a: Found, b: Found) -> float:
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0))
    return w * h / max(1e-9, small)


def merged(page: list[Found], own: list[Found]) -> list[Found]:
    """Where both readings meet: tesseract's line over several of ours loses when ours
    are cells of a strip or surer, else the surer reading of a place wins."""
    kept_own = set(range(len(own)))
    out = []
    for a in page:
        over = [i for i, b in enumerate(own) if _share(a, b) > 0.3]
        if len(over) >= 2:
            mean = sum(own[i].confidence for i in over) / len(over)
            if any(own[i].walled for i in over) or mean > a.confidence + 5:
                continue
            kept_own.difference_update(over)
        elif len(over) == 1:
            b = own[over[0]]
            if a.confidence * min(1.0, len(a.text) / 3) < b.confidence * min(1.0, len(b.text) / 3):
                continue
            kept_own.discard(over[0])
        out.append(a)
    return out + [own[i] for i in sorted(kept_own)]


# -- the whole ------------------------------------------------------------------------


def trace_picture(
    image: QImage, width_mm: float, quality: str = ocr.FAST, progress=None
) -> TraceResult:
    """Lines, circles and texts of ``image``, ``width_mm`` wide, top left at (0, 0);
    ``progress(fraction, text)`` returning False stops with Cancelled."""
    pi = _picture_tools()
    seconds: dict[str, float] = {}
    clock = [time.monotonic()]

    def step(fraction: float, text: str, name: str | None = None) -> None:
        if name:  # the end of a stage: its time
            now = time.monotonic()
            seconds[name] = now - clock[0]
            clock[0] = now
        if progress is not None and progress(round(fraction, 4), text) is False:
            raise Cancelled

    step(0.0, tr("Das Blatt wird gerade gerichtet …"))
    work, full = straight_pictures(image)
    step(0.15, tr("Linien und Kreise werden gesucht …"), "straighten")
    w, h, ink = pi.ink(work)
    _gw, _gh, gray = pi._gray_bytes(work)
    cap = text_layout.estimate_cap(text_layout.components(w, h, ink))
    sw = stroke_width(w, h, ink)
    rings = circles(w, h, ink, sw, cap)
    apart, pieces = text_layout.letters_apart(w, h, ink, cap)
    lettered = text_layout.letter_rings(rings, pieces, cap)
    rings = [r for r in rings if r not in lettered]
    shapes0 = vectorize(w, h, ink, cap, rings, sw)
    strokes0 = [s for s in shapes0 if isinstance(s, Stroke)]
    step(0.25, tr("Texte werden gelesen …"), "graphics")
    page: list[Found] = []
    own: list[Found] = []
    if ocr.available():
        long_ones = [s for s in strokes0 if not s.dashed]

        def page_read(share: float) -> None:
            step(0.25 + 0.2 * share, tr("Texte werden gelesen …"))

        for lb in pi.read_texts(full, w, long_ones, quality, page_read):
            page.append(
                Found(
                    ocr.corrected(lb.text),
                    lb.left,
                    lb.top,
                    lb.right,
                    lb.bottom,
                    lb.cap_height,
                    lb.rotation,
                    lb.confidence,
                    baseline=lb.baseline,
                )
            )
        step(0.45, tr("Texte werden einzeln gelesen …"), "page_ocr")
        letters = [
            b
            for b in pieces
            if text_layout.letter_like(b, max(3, round(0.25 * cap)), round(3.5 * cap))
        ]
        plain = [b for b in letters if not text_layout.ring_like(b, rings)]
        lines = text_layout.split_by_walls(
            text_layout.split_at_walls(text_layout.text_lines(plain)), strokes0
        )
        cropper = Cropper(full, full.width() / w, strokes0, rings)
        jobs, keys = [], []
        for n, line in enumerate(lines):
            psm, allowed = (
                (10, SINGLE) if len(line.boxes) == 1 else (8 if len(line.boxes) <= 3 else 7, "")
            )
            for turn in (90, -90) if line.upright else (0,):
                jobs.append((_png(cropper.crop(line, turn)), psm, allowed))
                keys.append((n, turn))

        def read(done: int, total: int):
            step(
                0.45 + 0.4 * done / max(1, total),
                tr("Texte werden einzeln gelesen ({done} von {total}) …").format(
                    done=done, total=total
                ),
            )

        try:
            words = ocr.read_many(jobs, quality, done=read)
        except InterruptedError as stop:
            raise Cancelled from stop
        best: dict[int, tuple[float, str, int]] = {}
        for (n, turn), ws in zip(keys, words, strict=True):
            ws = [wd for wd in ws if wd.text.strip()]
            if not ws:
                continue
            text = " ".join(wd.text for wd in ws)
            conf = sum(wd.confidence * len(wd.text) for wd in ws) / sum(len(wd.text) for wd in ws)
            if n not in best or conf > best[n][0]:
                best[n] = (conf, text, turn)
        for n, (conf, text, turn) in best.items():
            line = lines[n]
            text = ocr.corrected(text.strip())
            if not _plausible(text, conf):
                continue
            rotation = 0 if not line.upright else (90 if turn == 90 else 270)
            own.append(
                Found(
                    text, line.x0, line.y0, line.x1, line.y1, line.size, rotation, conf, line.walled
                )
            )
        step(0.85, tr("Linien werden gezogen …"), "own_ocr")
    found = merged(page, own)
    # the lines once more, from the ink without the letters of the texts (only the
    # pieces shaped like letters inside a text: a dash of a dashed line touching it
    # stays, else the line falls apart)
    rest = bytearray(ink)
    smallest, largest = max(3, round(0.25 * cap)), round(3.5 * cap)
    cell = max(16, round(2 * cap))
    grid: dict[tuple[int, int], list[text_layout.Box]] = {}
    for b in pieces:
        if text_layout.letter_like(b, smallest, largest) or text_layout.thin_letter(b, cap):
            grid.setdefault(
                (int((b.x0 + b.x1) / 2) // cell, int((b.y0 + b.y1) / 2) // cell), []
            ).append(b)
    for f in found:
        x0, y0, x1, y1 = f.x0 - 2, f.y0 - 2, f.x1 + 2, f.y1 + 2
        for gx in range(int(x0) // cell, int(x1) // cell + 1):
            for gy in range(int(y0) // cell, int(y1) // cell + 1):
                for b in grid.get((gx, gy), ()):
                    if x0 <= (b.x0 + b.x1) / 2 <= x1 and y0 <= (b.y0 + b.y1) / 2 <= y1:
                        for y in range(b.y0, b.y1):
                            row = y * w
                            for x in range(b.x0, b.x1):
                                if apart[row + x]:
                                    rest[row + x] = 0
    shapes = vectorize(w, h, bytes(rest), cap, rings, sw)
    box = frame_box(shapes, w, h, gray)
    if box is not None:
        margin = 0.6 * cap
        shapes = inside(shapes, box, margin)
        x0, y0, x1, y1 = box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin
        found = [
            f for f in found if x0 <= (f.x0 + f.x1) / 2 <= x1 and y0 <= (f.y0 + f.y1) / 2 <= y1
        ]
    step(1.0, tr("Fertig"), "lines")
    return TraceResult(_entities(w, shapes, found, width_mm), work, seconds)


def _entities(w: int, shapes, found: list[Found], width_mm: float) -> list[Entity]:
    k = width_mm / w
    out: list[Entity] = []
    for s in shapes:
        if isinstance(s, Stroke):
            p1 = Point(round(s.x1 * k, 2), round(s.y1 * k, 2))
            p2 = Point(round(s.x2 * k, 2), round(s.y2 * k, 2))
            if p1 != p2:
                out.append(Line(id=new_id(), p1=p1, p2=p2, linetype="dashed" if s.dashed else None))
        elif isinstance(s, Ring):
            out.append(
                Circle(
                    id=new_id(),
                    center=Point(round(s.cx * k, 2), round(s.cy * k, 2)),
                    radius=round(s.r * k, 2),
                )
            )
    for f in found:
        x, y = {0: (f.x0, f.y1), 90: (f.x1, f.y1), 270: (f.x0, f.y0)}[f.rotation]
        if f.baseline is not None:  # the baseline as tesseract saw it
            if f.rotation == 0:
                y = f.baseline
            else:
                x = f.baseline
        out.append(
            Text(
                id=new_id(),
                position=Point(round(x * k, 2), round(y * k, 2)),
                text=f.text,
                height=round(f.size * k, 2),
                rotation=f.rotation,
            )
        )
    return out
