"""Rendering sheets onto printers, PDF, SVG and PNG."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QMarginsF, QPointF, QRectF, QSizeF
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPagedPaintDevice,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)
from PyQt6.QtSvg import QSvgGenerator

from sldgridy import __version__
from sldgridy.model.document import Document, SheetLayout
from sldgridy.printing.layout import Mode, Page, fit, fit_rect, one_to_one, tiles
from sldgridy.view.display import OutputOptions, expand_for_display, paint_entities, paint_sheet
from sldgridy.view.render import entity_bounds

MM_PER_INCH = 25.4
PDF_RESOLUTION = 1200
SVG_PX_PER_MM = 10
MARK_LENGTH = 6.0
MARK_WEIGHT = 0.18
TILE_LABEL_HEIGHT = 2.5


@dataclass(frozen=True)
class Job:
    """What to print: sheets (or the model for quick print) and how."""

    sheets: Sequence[SheetLayout]
    mode: Mode = Mode.ONE_TO_ONE
    paper: tuple[float, float] = (210.0, 297.0)  # portrait size; orientation is chosen
    options: OutputOptions = OutputOptions(helpers=False)
    model: bool = False  # quick print of the model extents


def model_extents(doc: Document, options: OutputOptions) -> QRectF | None:
    rect = QRectF()
    for e in doc.model_space:
        layer = doc.layer(e.layer)
        if not layer.visible or (options.printable_only and not layer.printable):
            continue
        for part in expand_for_display(doc, e):
            rect = rect.united(entity_bounds(part, doc.effective_lineweight(part)))
    return rect if not rect.isEmpty() else None


def plan(doc: Document, job: Job) -> list[tuple[SheetLayout | None, Page]]:
    """All pages of a job in order."""
    pw, ph = job.paper
    if job.model:
        extents = model_extents(doc, job.options)
        if extents is None:
            return []
        page = fit_rect(extents.left(), extents.top(), extents.width(), extents.height(), pw, ph)
        return [(None, page)]
    pages: list[tuple[SheetLayout | None, Page]] = []
    for sheet in job.sheets:
        w, h = sheet.size
        if job.mode is Mode.ONE_TO_ONE:
            sheet_pages = one_to_one(w, h)
        elif job.mode is Mode.FIT:
            sheet_pages = fit(w, h, pw, ph)
        else:
            sheet_pages = tiles(w, h, pw, ph)
        pages += [(sheet, p) for p in sheet_pages]
    return pages


def page_layout(page: Page) -> QPageLayout:
    """Full page layout for ``page``: a standard paper size (A4, A3 …) with portrait or
    landscape orientation where it is one, so the printer gets "A4 landscape" and prints
    it 1:1 instead of scaling an unknown custom size to its paper."""
    short, long = sorted((page.width, page.height))
    size = QPageSize(
        QSizeF(short, long),
        QPageSize.Unit.Millimeter,
        "",
        QPageSize.SizeMatchPolicy.FuzzyMatch,
    )
    orientation = (
        QPageLayout.Orientation.Landscape
        if page.width > page.height
        else QPageLayout.Orientation.Portrait
    )
    layout = QPageLayout(size, orientation, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    layout.setMode(QPageLayout.Mode.FullPageMode)
    return layout


def paint_page(
    painter: QPainter,
    doc: Document,
    sheet: SheetLayout | None,
    page: Page,
    options: OutputOptions,
) -> None:
    """Paint one page; the painter must use millimetres with the origin at the page corner."""
    painter.save()
    painter.setClipRect(QRectF(0, 0, page.width, page.height))
    painter.translate(page.offset_x, page.offset_y)
    painter.scale(page.scale, page.scale)
    painter.translate(-page.origin_x, -page.origin_y)
    if sheet is None:
        paint_entities(painter, doc, list(doc.model_space), 0, options)
    else:
        paint_sheet(painter, doc, sheet, 0, options)
    painter.restore()
    if page.tile is not None:
        _paint_tile_marks(painter, page)


def _paint_tile_marks(painter: QPainter, page: Page) -> None:
    pen = QPen(QColor("black"), MARK_WEIGHT)
    painter.setPen(pen)
    for x in page.cut_x:
        painter.drawLine(QPointF(x, 0), QPointF(x, MARK_LENGTH))
        painter.drawLine(QPointF(x, page.height - MARK_LENGTH), QPointF(x, page.height))
    for y in page.cut_y:
        painter.drawLine(QPointF(0, y), QPointF(MARK_LENGTH, y))
        painter.drawLine(QPointF(page.width - MARK_LENGTH, y), QPointF(page.width, y))
    row, col = page.tile
    font = QFont("DejaVu Sans")
    font.setPixelSize(100)
    painter.save()
    painter.translate(MARK_LENGTH + 2, 2 + TILE_LABEL_HEIGHT)
    k = TILE_LABEL_HEIGHT / 72.0  # cap height of DejaVu Sans at 100 px is about 72 px
    painter.scale(k, k)
    painter.setFont(font)
    label = QCoreApplication.translate("printing", "Z{row}/S{col}")
    painter.drawText(QPointF(0, 0), label.format(row=row, col=col))
    painter.restore()


def _mm_painter(painter: QPainter) -> None:
    dpi = painter.device().logicalDpiX()
    painter.scale(dpi / MM_PER_INCH, painter.device().logicalDpiY() / MM_PER_INCH)


def render(
    device: QPagedPaintDevice,
    doc: Document,
    pages: list[tuple[SheetLayout | None, Page]],
    options: OutputOptions,
) -> int:
    """Paint pages onto a printer or PDF writer. Returns the number of pages."""
    if not pages:
        return 0
    device.setPageLayout(page_layout(pages[0][1]))
    painter = QPainter()
    if not painter.begin(device):
        raise OSError("cannot start painting on the output device")
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        for i, (sheet, page) in enumerate(pages):
            if i:
                device.setPageLayout(page_layout(page))
                device.newPage()
            painter.save()
            _mm_painter(painter)
            paint_page(painter, doc, sheet, page, options)
            painter.restore()
    finally:
        painter.end()
    return len(pages)


def export_pdf(
    path: Path, doc: Document, sheets: Sequence[SheetLayout], options: OutputOptions
) -> int:
    """Vector PDF with one page per sheet in its exact size."""
    writer = QPdfWriter(str(path))
    writer.setResolution(PDF_RESOLUTION)
    writer.setCreator(f"SLDGridy {__version__}")
    writer.setTitle(Path(path).stem)
    pages = [(s, p) for s in sheets for p in one_to_one(*s.size)]
    return render(writer, doc, pages, options)


def export_svg(path: Path, doc: Document, sheet: SheetLayout, options: OutputOptions) -> None:
    w, h = sheet.size
    gen = QSvgGenerator()
    gen.setFileName(str(path))
    gen.setResolution(round(SVG_PX_PER_MM * MM_PER_INCH))
    gen.setSize(QSizeF(w * SVG_PX_PER_MM, h * SVG_PX_PER_MM).toSize())
    gen.setViewBox(QRectF(0, 0, w, h))
    gen.setTitle(sheet.name)
    gen.setDescription(f"SLDGridy {__version__}")
    painter = QPainter()
    if not painter.begin(gen):
        raise OSError(f"cannot write {path}")
    try:
        painter.fillRect(QRectF(0, 0, w, h), QColor("white"))
        paint_page(painter, doc, sheet, Page(w, h), options)
    finally:
        painter.end()


def sheet_image(doc: Document, sheet: SheetLayout, dpi: int, options: OutputOptions) -> QImage:
    w, h = sheet.size
    px_per_mm = dpi / MM_PER_INCH
    image = QImage(round(w * px_per_mm), round(h * px_per_mm), QImage.Format.Format_ARGB32)
    image.setDotsPerMeterX(round(px_per_mm * 1000))
    image.setDotsPerMeterY(round(px_per_mm * 1000))
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(px_per_mm, px_per_mm)
    paint_page(painter, doc, sheet, Page(w, h), options)
    painter.end()
    return image


def export_png(
    path: Path, doc: Document, sheet: SheetLayout, dpi: int, options: OutputOptions
) -> None:
    if not sheet_image(doc, sheet, dpi, options).save(str(path), "PNG"):
        raise OSError(f"cannot write {path}")
