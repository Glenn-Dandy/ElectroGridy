"""How document entities are displayed: styles, expansion and whole-area painting.

Shared by the scene items on screen and by printing and export.
"""

from dataclasses import dataclass, replace

from PyQt6.QtCore import QCoreApplication, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen

from sldgridy.model.blocks import BlockError, expand
from sldgridy.model.devices import crossref_texts, crossrefs
from sldgridy.model.dimensions import dimension_geometry
from sldgridy.model.document import (
    GENERATED_KINDS,
    PAGE_KINDS,
    SCHEMATIC_FRAME,
    Document,
    SheetLayout,
)
from sldgridy.model.entities import (
    BlockReference,
    Dimension,
    Entity,
    InterruptionPoint,
    Viewport,
    Wire,
)
from sldgridy.model.interruptions import interruption_geometry, interruption_targets
from sldgridy.model.reports import generated_entities, report_rows
from sldgridy.model.sheet import (
    frame_entities,
    schematic_frame_entities,
    schematic_title_insert,
    title_block_reference,
)
from sldgridy.model.title_block import CAPTIONS, FIELD_LABELS
from sldgridy.model.wires import junction_diameter, junctions, label_text
from sldgridy.view.render import Style, entity_bounds, make_pen, paint_entity

BLACK = QColor("black")
VIEWPORT_HELPER_COLOR = QColor("#8a8a8a")


@dataclass(frozen=True)
class OutputOptions:
    """Rendering choices; screen uses the defaults, printing switches helpers off."""

    helpers: bool = True
    printable_only: bool = False
    monochrome: bool = False


SCREEN = OutputOptions()


def resolve_style(doc: Document, e: Entity, monochrome: bool = False) -> Style:
    color = BLACK if monochrome else QColor(doc.effective_color(e))
    return Style(color, doc.effective_lineweight(e), doc.effective_linetype(e))


def _page_key(doc: Document) -> tuple:
    """Content the generated parts depend on, for documents without a revision counter
    (printing and export outside the user interface)."""
    return (
        tuple(
            (p.id, p.kind, p.plant, p.location, p.paper, p.orientation, p.columns, len(p.entities))
            + tuple(
                (e.id, e.name, e.position)
                if isinstance(e, InterruptionPoint)
                else (e.id, e.name, e.insert, e.attributes)
                for e in p.entities
                if isinstance(e, InterruptionPoint | BlockReference)
            )
            for p in doc.sheets
        ),
        tuple(
            (e.id, e.name, e.insert, e.attributes)
            for e in doc.model_space
            if isinstance(e, BlockReference)
        ),
        len(doc.model_space),
        tuple((b.name, b.function, b.contact, b.description) for b in doc.blocks.values()),
        tuple(sorted(doc.properties.items())),
    )


def page_cache(doc: Document) -> dict:
    """Generated content computed once per change: the user interface counts changes in
    ``doc._revision``; elsewhere a key from the content decides."""
    revision = getattr(doc, "_revision", None)
    key = ("revision", revision) if revision is not None else _page_key(doc)
    cached = getattr(doc, "_page_cache", None)
    if cached is None or cached[0] != key:
        cached = (key, {})
        doc._page_cache = cached  # noqa: SLF001 - plain cache attribute
    return cached[1]


def contact_letters() -> dict[str, str]:
    return {
        "no": QCoreApplication.translate("contact", "S"),
        "nc": QCoreApplication.translate("contact", "Ö"),
        "co": QCoreApplication.translate("contact", "W"),
        "": "",
    }


def interruption_targets_of(doc: Document) -> dict[str, tuple[str, str]]:
    cache = page_cache(doc)
    if "targets" not in cache:
        cache["targets"] = interruption_targets(doc)
    return cache["targets"]


def crossrefs_of(doc: Document) -> dict[str, list[str]]:
    cache = page_cache(doc)
    if "xrefs" not in cache:
        cache["xrefs"] = crossrefs(doc, contact_letters())
    return cache["xrefs"]


def report_rows_of(doc: Document, kind: str) -> list[list[str]]:
    cache = page_cache(doc)
    key = ("rows", kind)
    if key not in cache:
        cache[key] = report_rows(doc, kind, _tr_reports)
    return cache[key]


def _tr_reports(text: str) -> str:
    return QCoreApplication.translate("reports", text)


def kind_names() -> dict[str, str]:
    """Page types in the active language."""
    return {k: QCoreApplication.translate("pages", v) for k, v in PAGE_KINDS.items()}


def expand_for_display(doc: Document, e: Entity) -> list[Entity]:
    """Simple entities that make up ``e`` on screen and on paper."""
    if isinstance(e, Wire):
        label = label_text(e)
        return [e, label] if label is not None else [e]
    if isinstance(e, Dimension):
        return dimension_geometry(e, _decimal_comma())
    if isinstance(e, InterruptionPoint):
        target = interruption_targets_of(doc).get(e.id)
        return interruption_geometry(e, target[0] if target else None)
    if isinstance(e, BlockReference):
        try:
            parts = expand(e, doc.blocks)
        except BlockError:
            return []
        lines = crossrefs_of(doc).get(e.id)
        if lines:
            parts = parts + crossref_texts(e, doc.blocks, lines)
        return [
            q
            for p in parts
            for q in (dimension_geometry(p, _decimal_comma()) if isinstance(p, Dimension) else [p])
        ]
    return [e]


def _decimal_comma() -> bool:
    from sldgridy.i18n import ui_locale

    return ui_locale().decimalPoint() == ","


def _shown(doc: Document, e: Entity, options: OutputOptions) -> bool:
    layer = doc.layer(e.layer)
    return layer.visible and (layer.printable or not options.printable_only)


def paint_entities(
    painter: QPainter,
    doc: Document,
    entities: list[Entity],
    px_per_mm: float,
    options: OutputOptions,
    weight_factor: float = 1.0,
) -> None:
    """Paint a container's entities (no viewports) plus the junction dots of its wires.

    ``weight_factor`` converts line widths (paper mm) into the painter's units, e.g.
    1 / scale inside a viewport, so a 0.5 mm line stays 0.5 mm on paper at any scale.
    """
    shown = [e for e in entities if not isinstance(e, Viewport) and _shown(doc, e, options)]
    for e in shown:
        for part in expand_for_display(doc, e):
            if not _shown(doc, part, options):
                continue
            style = resolve_style(doc, part, options.monochrome)
            if weight_factor != 1.0:
                style = Style(style.color, style.lineweight * weight_factor, style.linetype)
            paint_entity(painter, part, style, px_per_mm, options.helpers)
    painter.setPen(Qt.PenStyle.NoPen)
    for p, wire in junctions(shown):
        style = resolve_style(doc, wire, options.monochrome)
        d = junction_diameter(style.lineweight) * weight_factor
        painter.setBrush(QBrush(style.color))
        painter.drawEllipse(QPointF(p.x, p.y), d / 2, d / 2)


def viewport_rect(vp: Viewport) -> QRectF:
    return QRectF(vp.left, vp.top, vp.width, vp.height)


def paint_viewport(
    painter: QPainter,
    doc: Document,
    vp: Viewport,
    px_per_mm: float,
    options: OutputOptions,
) -> None:
    """Model content clipped to the viewport, then its border if wanted."""
    rect = viewport_rect(vp)
    painter.save()
    painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    c = vp.sheet_center
    painter.translate(c.x, c.y)
    painter.scale(vp.scale, vp.scale)
    painter.translate(-vp.center.x, -vp.center.y)
    # Line widths are paper widths (ISO 128): they do not shrink or grow with the scale.
    paint_entities(
        painter, doc, list(doc.model_space), px_per_mm * vp.scale, options, 1.0 / vp.scale
    )
    painter.restore()
    if vp.print_border and _shown(doc, vp, options):
        style = resolve_style(doc, vp, options.monochrome)
        painter.setPen(make_pen(style.color, style.lineweight, px_per_mm if options.helpers else 0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
    elif options.helpers:
        pen = QPen(VIEWPORT_HELPER_COLOR, 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)


def title_labels() -> dict[str, str]:
    """Cell captions of the standard title block in the active language."""
    return {
        tag: QCoreApplication.translate("title_block", label)
        for tag, label in {**FIELD_LABELS, **CAPTIONS}.items()
    }


def title_block_parts(doc: Document, sheet: SheetLayout) -> list[Entity]:
    if not sheet.title_block or sheet.title_block not in doc.blocks:
        return []
    w, h = sheet.size
    values = doc.field_values(
        sheet.id,
        of=QCoreApplication.translate("display", "von"),
        landscape=QCoreApplication.translate("display", "quer"),
        portrait=QCoreApplication.translate("display", "hoch"),
        kinds=kind_names(),
    )
    ref = title_block_reference(sheet.title_block, w, h, values)
    if sheet.frame == SCHEMATIC_FRAME:
        ref = replace(ref, insert=schematic_title_insert(w, h))
    try:
        return expand(ref, doc.blocks)
    except BlockError:
        return []


def frame_parts(doc: Document, sheet: SheetLayout, helpers: bool = False) -> list[Entity]:
    """Frame lines (and band) plus the generated content of cover and list pages."""
    w, h = sheet.size
    if sheet.frame == SCHEMATIC_FRAME:
        parts = schematic_frame_entities(w, h, sheet.columns or 10)
    else:
        parts = frame_entities(w, h)
    if sheet.kind in GENERATED_KINDS:
        parts += generated_entities(
            doc, sheet, lambda kind: report_rows_of(doc, kind), _tr_reports, helpers
        )
    return parts


def _style(part: Entity, options: OutputOptions, default_weight: float) -> Style:
    return Style(
        BLACK if options.monochrome or part.color is None else QColor(part.color),
        part.lineweight if part.lineweight is not None else default_weight,
        part.linetype or "continuous",
    )


def paint_frame(
    painter: QPainter,
    doc: Document,
    sheet: SheetLayout,
    px_per_mm: float,
    options: OutputOptions,
) -> None:
    """Frame, generated content and the title block (opaque) of a page."""
    for e in frame_parts(doc, sheet, options.helpers):
        paint_entity(painter, e, _style(e, options, 0.25), px_per_mm, options.helpers)
    parts = title_block_parts(doc, sheet)
    if not parts:
        return
    bounds = QRectF()
    for part in parts:
        bounds = bounds.united(entity_bounds(part, part.lineweight or 0.35))
    painter.fillRect(bounds, QColor("white"))
    for part in parts:
        paint_entity(painter, part, _style(part, options, 0.25), px_per_mm, options.helpers)


def paint_sheet(
    painter: QPainter,
    doc: Document,
    sheet: SheetLayout,
    px_per_mm: float,
    options: OutputOptions,
) -> None:
    """Everything printed on a sheet, in the same stacking order as on screen."""
    for vp in sheet.viewports():
        paint_viewport(painter, doc, vp, px_per_mm, options)
    paint_entities(painter, doc, list(sheet.entities), px_per_mm, options)
    paint_frame(painter, doc, sheet, px_per_mm, options)
