"""File > Import circuit diagram: a PDF page or a picture (photo, scan), a region of
it marked with the mouse, brought in as lines and texts (PDF from a CAD program), as
a picture, or converted from the picture into lines (an attempt).

PDF pages are shown with QtPdf (python3-pyqt6.qtpdf), their lines and texts read with
pdfminer (python3-pdfminer); both are optional, without them only pictures work.
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
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
    QGraphicsPixmapItem,
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

from sldgridy.fileio import pdf_import
from sldgridy.model.entities import Circle, Entity, Line, RasterImage, new_id
from sldgridy.model.geometry import Point
from sldgridy.model.vectorize import Ring, Stroke, vectorize

PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")
PREVIEW_DPI = 100
IMAGE_DPI = 200  # PDF regions brought in as pictures
TRACE_SIDE = 2000  # pixels of the longer side when converting a picture into lines
TRACE_MIN_SIDE = 1600
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


def darkness(image: QImage) -> QImage:
    """How much darker each pixel is than the paper around it: uneven light on a photo
    and a grey scan background drop out."""
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
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
    """Lines and circles from a picture, ``width_mm`` wide, top left at (0, 0)."""
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
    out: list[Entity] = []
    for shape in vectorize(w, h, data):
        if isinstance(shape, Stroke):
            p1 = Point(round(shape.x1 * k, 2), round(shape.y1 * k, 2))
            p2 = Point(round(shape.x2 * k, 2), round(shape.y2 * k, 2))
            if p1 != p2:
                out.append(Line(id=new_id(), p1=p1, p2=p2))
        elif isinstance(shape, Ring):
            out.append(
                Circle(
                    id=new_id(),
                    center=Point(round(shape.cx * k, 2), round(shape.cy * k, 2)),
                    radius=round(shape.r * k, 2),
                )
            )
    return out


def picture_entity(image: QImage, width_mm: float, photo: bool) -> RasterImage:
    kept = limited(image, MAX_PICTURE_SIDE)
    height = width_mm * kept.height() / max(1, kept.width())
    return RasterImage(
        id=new_id(), p1=Point(0, 0), p2=Point(width_mm, height), data=encoded(kept, photo)
    )


# -- dialog ---------------------------------------------------------------------


class RegionView(QGraphicsView):
    """The page or picture; dragging marks the region to import (default: all)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#808080")))
        self._pixmap = QGraphicsPixmapItem()
        self.scene().addItem(self._pixmap)
        self._mark = QGraphicsRectItem()
        pen = QPen(QColor("#1565c0"), 0)
        pen.setCosmetic(True)
        pen.setWidth(2)
        self._mark.setPen(pen)
        self._mark.setBrush(QBrush(QColor(21, 101, 192, 40)))
        self._mark.setZValue(1)
        self.scene().addItem(self._mark)
        self._start: QPointF | None = None
        self.region = QRectF()

    def set_image(self, image: QImage) -> None:
        self._pixmap.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(QRectF(image.rect().toRectF()))
        self.region = QRectF(image.rect().toRectF())
        self._mark.setRect(self.region)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _clamped(self, p: QPointF) -> QPointF:
        r = self.scene().sceneRect()
        return QPointF(min(max(p.x(), r.left()), r.right()), min(max(p.y(), r.top()), r.bottom()))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = self._clamped(self.mapToScene(event.position().toPoint()))
            self._mark.setRect(QRectF(self._start, self._start))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._start is not None:
            end = self._clamped(self.mapToScene(event.position().toPoint()))
            self._mark.setRect(QRectF(self._start, end).normalized())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._start is None:
            return
        self._start = None
        rect = self._mark.rect()
        if rect.width() < 5 or rect.height() < 5:  # a click: everything again
            rect = self.scene().sceneRect()
            self._mark.setRect(rect)
        self.region = rect
        changed = getattr(self.parent(), "_region_changed", None)
        if changed is not None:
            changed()


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
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow(self.tr("Übernehmen als:"), self.mode)
        form.addRow("", self.keep)
        form.addRow(self.tr("Breite des Bereichs:"), self.width_mm)
        right = QVBoxLayout()
        right.addWidget(
            QLabel(self.tr("Bereich mit der Maus aufziehen; ein Klick wählt wieder alles."))
        )
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

    def _region_changed(self) -> None:
        f = self._region_fraction()
        if self.source.pdf is not None:
            size = self.source.pdf.pagePointSize(self.page)
            width = f.width() * size.width() * pdf_import.MM_PER_PT
        else:
            width = PICTURE_WIDTH * f.width()
        self.width_mm.setValue(round(width, 1))

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
                "Versuch: waagerechte, senkrechte und schräge Linien und Kreise werden "
                "erkannt, Texte nicht. Am besten gerade von oben fotografieren."
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
