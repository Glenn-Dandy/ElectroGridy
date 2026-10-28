"""File > Import circuit diagram: a PDF page or a picture (photo, scan), a region of
it marked with the mouse, brought in as lines and texts (PDF from a CAD program), as
a picture, or converted from the picture into lines (an attempt).

PDF pages are shown with QtPdf (python3-pyqt6.qtpdf), their lines and texts read with
pdfminer (python3-pdfminer); both are optional, without them only pictures work.
"""

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sldgridy.fileio import ocr, pdf_import
from sldgridy.model.entities import Circle, Entity, Line, RasterImage, Text, new_id
from sldgridy.model.geometry import Point
from sldgridy.model.paper import Orientation, paper_of
from sldgridy.model.vectorize import Ring, Stroke, vectorize

PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")
PREVIEW_DPI = 100
IMAGE_DPI = 200  # PDF regions brought in as pictures
TRACE_SIDE = 2000  # pixels of the longer side when converting a picture into lines
TRACE_MIN_SIDE = 1600
TEXT_SIDE = 2800  # pixels of the longer side for a first look at the texts
TEXT_HEIGHT = 24  # pixels of capitals tesseract reads best
TEXT_SIDES = (1600, 6000)
MAX_PICTURE_SIDE = 2400  # pixels kept of a picture
PICTURE_WIDTH = 250.0  # mm, first suggestion for pictures without a size
VECTORS, PICTURE, TRACE = "vectors", "picture", "trace"


def pdf_available() -> bool:
    try:
        from PyQt6.QtPdf import QPdfDocument  # noqa: F401
    except ImportError:
        return False
    return True


# -- pictures -------------------------------------------------------------------


def load_picture(path: Path) -> QImage:
    """A picture turned the way the camera was held (EXIF)."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    return reader.read()


def limited(image: QImage, side: int) -> QImage:
    if max(image.width(), image.height()) <= side:
        return image
    return image.scaled(
        side,
        side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def encoded(image: QImage, photo: bool) -> bytes:
    """JPEG for photos (small), PNG for drawings rendered from a PDF (sharp)."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if photo:
        image.convertToFormat(QImage.Format.Format_RGB32).save(buffer, "JPG", 85)
    else:
        image.save(buffer, "PNG")
    return bytes(buffer.data())


def _gray_bytes(image: QImage) -> tuple[int, int, bytes]:
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = gray.width(), gray.height()
    bits = gray.constBits()
    bits.setsize(gray.sizeInBytes())
    raw = bytes(bits)
    stride = gray.bytesPerLine()
    if stride == w:
        return w, h, raw[: w * h]
    return w, h, b"".join(raw[y * stride : y * stride + w] for y in range(h))


def _gray(image: QImage) -> QImage:
    """Grey, transparent parts white, light on dark (a dark screen) turned round."""
    if image.hasAlphaChannel():
        white = QImage(image.size(), QImage.Format.Format_RGB32)
        white.fill(QColor("white"))
        painter = QPainter(white)
        painter.drawImage(0, 0, image)
        painter.end()
        image = white
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    _w, _h, sample = _gray_bytes(limited(gray, 200))
    if sample and sum(sample) / len(sample) < 100:
        gray.invertPixels()
    return gray


def darkness(image: QImage) -> QImage:
    """How much darker each pixel is than the paper around it: uneven light on a photo
    and a grey scan background drop out."""
    gray = _gray(image)
    w, h = gray.width(), gray.height()
    background = gray.scaled(
        max(1, w // 24),
        max(1, h // 24),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    # max(paper, pixel) - pixel: only what is darker than the paper counts.
    pixels = gray.convertToFormat(QImage.Format.Format_RGB32)
    result = background.convertToFormat(QImage.Format.Format_RGB32)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)
    painter.drawImage(0, 0, pixels)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
    painter.drawImage(0, 0, pixels)
    painter.end()
    return result.convertToFormat(QImage.Format.Format_Grayscale8)


def _threshold(values: bytes) -> int:
    """Otsu's threshold of a sample, at least a clear step above the paper."""
    counts = Counter(values[:: max(1, len(values) // 200000)])
    total = sum(counts.values())
    if not total:
        return 128
    mean_all = sum(v * n for v, n in counts.items()) / total
    best, best_t = -1.0, 40
    weight, mean_sum = 0, 0.0
    for t in range(256):
        weight += counts.get(t, 0)
        mean_sum += t * counts.get(t, 0)
        if weight == 0 or weight == total:
            continue
        m0 = mean_sum / weight
        m1 = (mean_all * total - mean_sum) / (total - weight)
        between = weight * (total - weight) * (m0 - m1) ** 2
        if between > best:
            best, best_t = between, t
    return max(best_t, 30)


def ink(image: QImage) -> tuple[int, int, bytes]:
    """One byte per pixel, 1 for ink."""
    w, h, values = _gray_bytes(darkness(image))
    # Below Otsu's value: thin, faint lines of a photo stay whole.
    t = max(20, int(_threshold(values) * 0.6))
    table = bytes(1 if v > t else 0 for v in range(256))
    return w, h, values.translate(table)


def skew_angle(image: QImage) -> float:
    """Small turn (degrees, counter-clockwise) that makes the strokes horizontal:
    the turn whose rows of ink are the most uneven."""
    small = limited(image, 800)
    w, h, data = ink(small)
    picture = QImage(data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    best, best_angle = -1.0, 0.0
    for step in range(-20, 21):
        angle = step * 0.25
        turned = picture.transformed(QTransform().rotate(-angle))
        tw, th, rows = _gray_bytes(turned)
        score = sum(rows.count(1, y * tw, (y + 1) * tw) ** 2 for y in range(th))
        if score > best:
            best, best_angle = score, angle
    return best_angle


def straightened(image: QImage, angle: float) -> QImage:
    if abs(angle) < 1e-6:
        return image
    turned = QImage(image.convertToFormat(QImage.Format.Format_RGB32))
    turned = turned.transformed(
        QTransform().rotate(-angle), Qt.TransformationMode.SmoothTransformation
    )
    # The corners the turn uncovers become paper, not black.
    filled = QImage(turned.size(), QImage.Format.Format_RGB32)
    filled.fill(QColor("white"))
    painter = QPainter(filled)
    painter.drawImage(0, 0, turned)
    painter.end()
    return filled


def traced(image: QImage, width_mm: float) -> list[Entity]:
    """Lines, circles and texts from a picture, ``width_mm`` wide, top left at (0, 0)."""
    work = limited(image, TRACE_SIDE)
    if max(work.width(), work.height()) < TRACE_MIN_SIDE:
        # Small pictures: lines a pixel thin break apart; enlarge first.
        work = work.scaled(
            TRACE_MIN_SIDE,
            TRACE_MIN_SIDE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    w, h, data = ink(work)
    k = width_mm / w
    shapes = vectorize(w, h, data)
    labels = read_texts(image, w, shapes) if ocr.available() else []
    out: list[Entity] = []
    for shape in shapes:
        if any(_covers(label, shape) for label in labels):
            continue  # a letter
        if isinstance(shape, Stroke):
            p1 = Point(round(shape.x1 * k, 2), round(shape.y1 * k, 2))
            p2 = Point(round(shape.x2 * k, 2), round(shape.y2 * k, 2))
            if p1 != p2:
                linetype = "dashed" if shape.dashed else None
                out.append(Line(id=new_id(), p1=p1, p2=p2, linetype=linetype))
        elif isinstance(shape, Ring):
            out.append(
                Circle(
                    id=new_id(),
                    center=Point(round(shape.cx * k, 2), round(shape.cy * k, 2)),
                    radius=round(shape.r * k, 2),
                )
            )
    for label in labels:
        x, y = {
            0: (label.left, label.baseline),
            90: (label.baseline, label.bottom),
            270: (label.baseline, label.top),
        }[label.rotation]
        out.append(
            Text(
                id=new_id(),
                position=Point(round(x * k, 2), round(y * k, 2)),
                text=label.text,
                height=round(label.cap_height * k, 2),
                rotation=label.rotation,
            )
        )
    return out


@dataclass(frozen=True)
class Label:
    """A text read from the picture, in the pixels of the traced picture. The
    baseline of upright texts is an x."""

    text: str
    left: float
    top: float
    right: float
    bottom: float
    baseline: float
    cap_height: float
    confidence: float
    rotation: int = 0  # 90: reads upwards, 270: downwards


def _covers(label: Label, shape: Stroke | Ring) -> bool:
    m = 2
    if isinstance(shape, Ring):
        xs, ys = (shape.cx - shape.r, shape.cx + shape.r), (shape.cy - shape.r, shape.cy + shape.r)
    else:
        xs, ys = (shape.x1, shape.x2), (shape.y1, shape.y2)
    return (
        label.left - m <= min(xs)
        and max(xs) <= label.right + m
        and label.top - m <= min(ys)
        and max(ys) <= label.bottom + m
    )


def _png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def text_picture(
    image: QImage, scale: float, shapes: list[Stroke | Ring], longer_than: float = 0
) -> QImage:
    """Black letters on white for reading: the picture ``scale`` times the traced one,
    paper evened out, the lines found painted over (those ``longer_than`` traced
    pixels: shorter ones may be part of a letter)."""
    w, h, values = _gray_bytes(darkness(image))
    # Black from where ink() sees ink, white well below: no specks from the paper.
    t = max(20, int(_threshold(values) * 0.6))
    table = bytes(
        255 - round(255 * min(1.0, max(0.0, (v - 0.7 * t) / (0.8 * t)))) for v in range(256)
    )
    picture = QImage(values.translate(table), w, h, w, QImage.Format.Format_Grayscale8).copy()
    f = scale
    painter = QPainter(picture)
    for shape in shapes:
        if isinstance(shape, Stroke):
            if math.hypot(shape.x2 - shape.x1, shape.y2 - shape.y1) <= longer_than:
                continue
            pen = QPen(QColor("white"), (shape.thickness + 3) * f)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(shape.x1 * f, shape.y1 * f), QPointF(shape.x2 * f, shape.y2 * f)
            )
        else:
            painter.setPen(QPen(QColor("white"), 4 * f))
            painter.drawEllipse(QPointF(shape.cx * f, shape.cy * f), shape.r * f, shape.r * f)
    painter.end()
    return picture


def read_texts(image: QImage, traced_width: int, shapes: list[Stroke | Ring]) -> list[Label]:
    """Texts in the picture, across and upright, in the pixels of the traced picture
    (``traced_width`` wide)."""
    side = max(image.width(), image.height())

    def scaled(longer: float) -> QImage:
        return image.scaled(
            round(image.width() * longer / side),
            round(image.height() * longer / side),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def prepared(big: QImage, longer_than: float) -> tuple[QImage, float]:
        f = big.width() / traced_width
        return text_picture(big, f, shapes, longer_than), f

    # A first look tells how high the letters are; then read them at the size tesseract
    # likes, with only the lines painted over that are longer than letters are high.
    picture, f = prepared(scaled(TEXT_SIDE), traced_width / 64)
    first = ocr.text_lines(ocr.read_words(_png(picture)))
    # Measuring needs no sure reading, only one of a few letters.
    sure = sorted(x.cap_height for x in first if x.confidence >= 60 and len(x.text) >= 3)
    if sure:
        cap = sure[len(sure) // 2]
        longer = min(max(TEXT_SIDE * TEXT_HEIGHT / cap, TEXT_SIDES[0]), TEXT_SIDES[1], 4 * side)
        picture, f = prepared(scaled(longer), max(traced_width / 64, 2.5 * cap / f))
        first = None
    # Upright texts read from left to right once the picture is turned a quarter:
    # clockwise for those reading upwards, counter-clockwise for those reading down.
    w, h = picture.width(), picture.height()
    passes = (
        (0, lambda x, y: (x, y)),
        (90, lambda u, v: (v, h - u)),
        (-90, lambda u, v: (w - v, u)),
    )
    found = []
    for turn, back in passes:
        if turn == 0 and first is not None:
            lines = first
        else:
            turned = picture.transformed(QTransform().rotate(turn)) if turn else picture
            lines = ocr.text_lines(ocr.read_words(_png(turned)))
        for line in lines:
            corners = [back(line.left, line.top), back(line.right, line.bottom)]
            xs, ys = [c[0] / f for c in corners], [c[1] / f for c in corners]
            base = back(line.left, line.baseline)
            found.append(
                Label(
                    line.text,
                    min(xs),
                    min(ys),
                    max(xs),
                    max(ys),
                    (base[1] if turn == 0 else base[0]) / f,
                    line.cap_height / f,
                    line.confidence,
                    rotation=(0, 90, 270)[(0, 90, -90).index(turn)],
                )
            )
    # Where two readings found something, the surer one wins; a long text read
    # sideways rarely comes out long, bits of letters do.
    out = []
    for label in sorted(ocr.same_size(found), key=lambda a: -a.confidence * min(8, len(a.text))):
        if not any(_overlap(label, kept) > 0.3 for kept in out):
            out.append(label)
    return out


def _overlap(a: Label, b: Label) -> float:
    """Shared area as a part of the smaller box."""
    w = min(a.right, b.right) - max(a.left, b.left)
    h = min(a.bottom, b.bottom) - max(a.top, b.top)
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a.right - a.left) * (a.bottom - a.top), (b.right - b.left) * (b.bottom - b.top))
    return w * h / max(1e-9, smaller)


def unslanted(image: QImage, quad: list[QPointF]) -> QImage:
    """The part of the picture inside ``quad`` (corners top left, top right, bottom
    right, bottom left) stretched to a rectangle: a sheet photographed at a slant,
    straight."""
    tl, tr, br, bl = quad

    def distance(a: QPointF, b: QPointF) -> float:
        return math.hypot(a.x() - b.x(), a.y() - b.y())

    width = max(1, round((distance(tl, tr) + distance(bl, br)) / 2))
    height = max(1, round((distance(tl, bl) + distance(tr, br)) / 2))
    target = [QPointF(0, 0), QPointF(width, 0), QPointF(width, height), QPointF(0, height)]
    transform = QTransform()
    if not QTransform.quadToQuad(QPolygonF(quad), QPolygonF(target), transform):
        return image
    out = QImage(width, height, QImage.Format.Format_RGB32)
    out.fill(QColor("white"))
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setTransform(transform)
    painter.drawImage(0, 0, image)
    painter.end()
    return out


def picture_entity(image: QImage, width_mm: float, photo: bool) -> RasterImage:
    kept = limited(image, MAX_PICTURE_SIDE)
    height = width_mm * kept.height() / max(1, kept.width())
    return RasterImage(
        id=new_id(), p1=Point(0, 0), p2=Point(width_mm, height), data=encoded(kept, photo)
    )


# -- dialog ---------------------------------------------------------------------


HANDLE = 10  # screen pixels around a corner that grab it


class RegionView(QGraphicsView):
    """The page or picture; dragging marks the region to import (default: all). With
    ``movable_corners`` each corner of the region can then be dragged on its own, onto
    the corners of a sheet photographed at a slant."""

    region_changed = pyqtSignal()  # by the user, after the mouse is released

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#808080")))
        self._pixmap = QGraphicsPixmapItem()
        self.scene().addItem(self._pixmap)
        pen = QPen(QColor("#1565c0"), 0)
        pen.setCosmetic(True)
        pen.setWidth(2)
        self._mark = QGraphicsPolygonItem()
        self._mark.setPen(pen)
        self._mark.setBrush(QBrush(QColor(21, 101, 192, 40)))
        self._mark.setZValue(1)
        self.scene().addItem(self._mark)
        self._handles = []
        for _ in range(4):
            handle = QGraphicsRectItem(-HANDLE / 2, -HANDLE / 2, HANDLE, HANDLE)
            handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            handle.setPen(pen)
            handle.setBrush(QBrush(QColor("white")))
            handle.setZValue(2)
            self.scene().addItem(handle)
            self._handles.append(handle)
        self.movable_corners = False
        self._start: QPointF | None = None
        self._corner: int | None = None
        self.quad: list[QPointF] = [QPointF()] * 4  # top left, top right, bottom right, bottom left
        self.region = QRectF()

    @property
    def region(self) -> QRectF:
        """The marked region; with moved corners the rectangle around them."""
        return QPolygonF(self.quad).boundingRect()

    @region.setter
    def region(self, rect: QRectF) -> None:
        self.quad = [rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]
        self._show()

    def slanted(self) -> bool:
        """Whether the corners were moved off a rectangle."""
        r = self.region
        corners = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
        return any(
            abs(p.x() - q.x()) + abs(p.y() - q.y()) > 0.5
            for p, q in zip(self.quad, corners, strict=True)
        )

    def _show(self) -> None:
        self._mark.setPolygon(QPolygonF(self.quad))
        for handle, corner in zip(self._handles, self.quad, strict=True):
            handle.setPos(corner)
            handle.setVisible(self.movable_corners and not self.region.isEmpty())

    def set_image(self, image: QImage) -> None:
        self._pixmap.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(QRectF(image.rect().toRectF()))
        self.region = QRectF(image.rect().toRectF())
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _clamped(self, p: QPointF) -> QPointF:
        r = self.scene().sceneRect()
        return QPointF(min(max(p.x(), r.left()), r.right()), min(max(p.y(), r.top()), r.bottom()))

    def _grabbed(self, pos: QPointF) -> int | None:
        if not self.movable_corners:
            return None
        for i, corner in enumerate(self.quad):
            on_screen = QPointF(self.mapFromScene(corner))
            if abs(on_screen.x() - pos.x()) <= HANDLE and abs(on_screen.y() - pos.y()) <= HANDLE:
                return i
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._corner = self._grabbed(event.position())
        if self._corner is None:
            self._start = self._clamped(self.mapToScene(event.position().toPoint()))
            self.region = QRectF(self._start, self._start)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        p = self._clamped(self.mapToScene(event.position().toPoint()))
        if self._corner is not None:
            self.quad[self._corner] = p
            self._show()
        elif self._start is not None:
            self.region = QRectF(self._start, p).normalized()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._corner is not None:
            self._corner = None
        elif self._start is not None:
            self._start = None
            rect = self.region
            if rect.width() < 5 or rect.height() < 5:  # a click: everything again
                self.region = self.scene().sceneRect()
        else:
            return
        self.region_changed.emit()


@dataclass
class _Source:
    path: Path
    pdf: object | None  # QPdfDocument
    pages: int


class ImportDialog(QDialog):
    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Schaltplan importieren"))
        self.resize(1100, 760)
        self._vector_counts: dict[int, int] = {}
        pdf = None
        pages = 1
        if path.suffix.lower() == ".pdf":
            from PyQt6.QtPdf import QPdfDocument

            pdf = QPdfDocument(self)
            pdf.load(str(path))
            pages = pdf.pageCount()
        self.source = _Source(path, pdf, pages)
        self._picture = None if pdf is not None else load_picture(path)

        self.pages = QListWidget()
        self.pages.setViewMode(QListWidget.ViewMode.IconMode)
        self.pages.setIconSize(QSize(150, 150))
        self.pages.setFixedWidth(190)
        self.pages.setMovement(QListWidget.Movement.Static)
        self.view = RegionView(self)
        self.view.movable_corners = pdf is None
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Linien und Texte (PDF aus einem CAD-Programm)"), VECTORS)
        self.mode.addItem(self.tr("Bild"), PICTURE)
        self.mode.addItem(self.tr("Bild in Linien umwandeln (Versuch)"), TRACE)
        self.keep = QCheckBox(self.tr("Bild darunter behalten"))
        self.keep.setChecked(True)
        self.width_mm = QDoubleSpinBox()
        self.width_mm.setRange(10.0, 5000.0)
        self.width_mm.setDecimals(1)
        self.width_mm.setSuffix(" mm")
        # The scale stays when the region changes (1 = a PDF at its size on paper,
        # a picture PICTURE_WIDTH wide); a typed width changes it.
        self._factor = 1.0
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.paper = QLabel()  # the format of the PDF page
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        if pdf is not None:
            form.addRow(self.tr("Format der Seite:"), self.paper)
        form.addRow(self.tr("Übernehmen als:"), self.mode)
        form.addRow("", self.keep)
        form.addRow(self.tr("Breite des Bereichs:"), self.width_mm)
        right = QVBoxLayout()
        how = self.tr("Bereich mit der Maus aufziehen; ein Klick wählt wieder alles.")
        if pdf is None:
            how += " " + self.tr(
                "Schräg fotografiert: die Ecken einzeln auf die Ecken des Blatts ziehen."
            )
        right.addWidget(QLabel(how))
        right.addWidget(self.view, 1)
        right.addLayout(form)
        right.addWidget(self.hint)
        right.addWidget(buttons)
        body = QHBoxLayout()
        body.addWidget(self.pages)
        holder = QWidget()
        holder.setLayout(right)
        body.addWidget(holder, 1)
        self.setLayout(body)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.pages.currentRowChanged.connect(self._show_page)
        self.view.region_changed.connect(self._region_changed)
        self.width_mm.valueChanged.connect(self._width_typed)
        if pdf is not None:
            for i in range(pages):
                item = QListWidgetItem(QIcon(QPixmap.fromImage(self._render(i, 20))), str(i + 1))
                self.pages.addItem(item)
        self.pages.setVisible(pages > 1)
        if not self.readable():
            return
        self._show_page(0)
        if pages > 1:
            self.pages.setCurrentRow(0)

    def readable(self) -> bool:
        if self.source.pdf is not None:
            return self.source.pages > 0
        return self._picture is not None and not self._picture.isNull()

    # -- pages ------------------------------------------------------------------

    def _render(self, page: int, dpi: float) -> QImage:
        size = self.source.pdf.pagePointSize(page)
        pixels = QSize(
            max(1, round(size.width() * dpi / 72)), max(1, round(size.height() * dpi / 72))
        )
        image = self.source.pdf.render(page, pixels)
        # Transparent pages on white paper.
        paper = QImage(image.size(), QImage.Format.Format_RGB32)
        paper.fill(QColor("white"))
        painter = QPainter(paper)
        painter.drawImage(0, 0, image)
        painter.end()
        return paper

    @property
    def page(self) -> int:
        return max(0, self.pages.currentRow()) if self.source.pdf is not None else 0

    def _show_page(self, page: int) -> None:
        if page < 0:
            return
        if self.source.pdf is not None:
            self.view.set_image(self._render(page, PREVIEW_DPI))
            has_vectors = self._vectors(page) >= pdf_import.MIN_VECTOR_OBJECTS
            self.paper.setText(self._paper_text(page))
        else:
            self.view.set_image(limited(self._picture, 1600))
            has_vectors = False
        self.mode.model().item(0).setEnabled(has_vectors)
        if has_vectors:
            self.mode.setCurrentIndex(0)
        elif self.mode.currentIndex() == 0:
            self.mode.setCurrentIndex(2)  # a photo or scan: try the lines
        self._region_changed()
        self._mode_changed()

    def _paper_text(self, page: int) -> str:
        """ "A3 quer (420 × 297 mm)", or only the size for other formats."""
        size = self.source.pdf.pagePointSize(page)
        w, h = size.width() * pdf_import.MM_PER_PT, size.height() * pdf_import.MM_PER_PT
        mm = f"{w:.0f} × {h:.0f} mm"
        found = paper_of(w, h)
        if found is None:
            return self.tr("Sonderformat {size}").format(size=mm)
        name, orientation = found
        turn = self.tr("quer") if orientation is Orientation.LANDSCAPE else self.tr("hoch")
        return f"{name} {turn} ({mm})"

    def _vectors(self, page: int) -> int:
        if not pdf_import.available():
            return 0
        if page not in self._vector_counts:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._vector_counts[page] = pdf_import.vector_count(self.source.path, page)
            except Exception:  # noqa: BLE001 - a broken PDF just has no usable vectors
                self._vector_counts[page] = 0
            finally:
                QApplication.restoreOverrideCursor()
        return self._vector_counts[page]

    # -- region and mode --------------------------------------------------------

    def _region_fraction(self) -> QRectF:
        """The marked region as a share of the page (0..1)."""
        scene = self.view.scene().sceneRect()
        r = self.view.region
        return QRectF(
            r.left() / scene.width(),
            r.top() / scene.height(),
            r.width() / scene.width(),
            r.height() / scene.height(),
        )

    def _page_width(self) -> float:
        """Width of the whole page or picture in mm at scale 1."""
        if self.source.pdf is not None:
            return self.source.pdf.pagePointSize(self.page).width() * pdf_import.MM_PER_PT
        return PICTURE_WIDTH

    def _region_changed(self) -> None:
        """The marked region at the current scale."""
        width = self._region_fraction().width() * self._page_width() * self._factor
        self.width_mm.blockSignals(True)
        self.width_mm.setValue(round(width, 1))
        self.width_mm.blockSignals(False)

    def _width_typed(self, width: float) -> None:
        full = self._region_fraction().width() * self._page_width()
        if full > 0:
            self._factor = width / full

    def _mode_changed(self, *_args) -> None:
        mode = self.mode.currentData()
        self.keep.setVisible(mode == TRACE)
        hints = {
            VECTORS: self.tr(
                "Linien, Kreise und Texte werden einzelne Objekte. Symbole kommen als "
                "Striche; markieren und mit „Block erstellen“ zusammenfassen."
            ),
            PICTURE: self.tr("Der Bereich kommt als Bild, zum Nachzeichnen oder so lassen."),
            TRACE: self.tr(
                "Versuch: Linien, gestrichelte Linien, Kreise und Texte werden erkannt. "
                "Texte bitte prüfen, kleine Schrift wird oft falsch gelesen."
            ),
        }
        self.hint.setText(hints[mode])

    # -- result -----------------------------------------------------------------

    def _region_image(self, dpi: float) -> tuple[QImage, bool]:
        """The marked region as a picture and whether it is a photo."""
        f = self._region_fraction()
        if self.source.pdf is not None:
            image, photo = self._render(self.page, dpi), False
        else:
            image, photo = self._picture, True
        w, h = image.width(), image.height()
        if self.view.slanted():
            scene = self.view.scene().sceneRect()
            kx, ky = w / scene.width(), h / scene.height()
            return unslanted(
                image, [QPointF(p.x() * kx, p.y() * ky) for p in self.view.quad]
            ), photo
        rect = QRectF(f.left() * w, f.top() * h, f.width() * w, f.height() * h).toRect()
        return image.copy(rect), photo

    def entities(self) -> list[Entity]:
        """What to place, top left at (0, 0), in mm."""
        mode = self.mode.currentData()
        width = self.width_mm.value()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if mode == VECTORS:
                size = self.source.pdf.pagePointSize(self.page)
                f = self._region_fraction()
                region = pdf_import.Region(
                    f.left() * size.width(),
                    f.top() * size.height(),
                    f.right() * size.width(),
                    f.bottom() * size.height(),
                )
                scale = width / max(1e-9, region_width_mm(region))
                return pdf_import.page_entities(self.source.path, self.page, region, scale)
            image, photo = self._region_image(IMAGE_DPI)
            if mode == PICTURE:
                return [picture_entity(image, width, photo)]
            angle = skew_angle(image)
            image = straightened(image, angle)
            lines = traced(image, width)
            if self.keep.isChecked():
                return [picture_entity(image, width, photo), *lines]
            return lines
        finally:
            QApplication.restoreOverrideCursor()


def region_width_mm(region: pdf_import.Region) -> float:
    return (region.right - region.left) * pdf_import.MM_PER_PT
