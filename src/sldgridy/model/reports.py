"""Generated pages: cover, table of contents, parts list, terminal plan, cable list.
Pure Python.

Their content is not stored; it is laid out from the project whenever the page is drawn,
so it is always up to date. Several pages of the same type continue the list in page
order. Captions are German source texts; the caller passes ``tr`` to translate them.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sldgridy.model.devices import MODEL, SHEET, devices, place
from sldgridy.model.document import (
    CABLES,
    COVER,
    PAGE_KINDS,
    PARTS,
    TERMINALS,
    TOC,
    Document,
    SheetLayout,
)
from sldgridy.model.entities import Entity, Line, Text
from sldgridy.model.geometry import Point
from sldgridy.model.netlist import Netlist, Pin, netlist
from sldgridy.model.sheet import schematic_inner
from sldgridy.model.title_block import SCHEMATIC_TITLE_HEIGHT

Translate = Callable[[str], str]

TEXT = 2.5
ROW = 5.0
TITLE = 7.0
MARGIN = 5.0
COVER_HEIGHT = 267.0  # drawing area height of A3 landscape, the cover's design size
OVERFLOW_COLOR = "#c62828"

# Columns of the lists: caption and share of the table width.
COLUMNS: dict[str, list[tuple[str, float]]] = {
    TOC: [
        ("Anlage (=)", 1.4),
        ("Ort (+)", 1.0),
        ("Seite", 0.6),
        ("Seitentyp", 1.8),
        ("Beschreibung", 3.6),
        ("Rev.", 0.5),
        ("Datum", 1.0),
    ],
    PARTS: [
        ("BMK", 1.0),
        ("Hersteller", 1.6),
        ("Typ", 2.0),
        ("Bezeichnung", 2.6),
        ("Blatt", 0.5),
        ("Pfad", 0.5),
    ],
    TERMINALS: [
        ("Leiste", 0.8),
        ("Klemme", 0.6),
        ("Ziel innen", 2.6),
        ("Ziel außen", 2.6),
        ("Blatt", 0.5),
        ("Pfad", 0.5),
    ],
    CABLES: [
        ("Kabel", 0.8),
        ("Typ", 2.0),
        ("Adern", 0.6),
        ("Von", 2.0),
        ("Nach", 2.0),
        ("Blatt", 0.8),
    ],
}


def _natural(text: str) -> list:
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def _where(doc: Document, area: str, x: float) -> tuple[str, str]:
    """Page and column ("Blatt", "Pfad") of a point; empty in the model."""
    if area == MODEL:
        return "", ""
    number, column = place(doc, area, x)
    return str(number), "" if column is None else str(column)


# -- rows ---------------------------------------------------------------------------


def toc_rows(doc: Document, tr: Translate = str) -> list[list[str]]:
    rows = []
    for page in doc.sheets:
        kind = tr(PAGE_KINDS[page.kind]) if page.kind in PAGE_KINDS else ""
        rows.append(
            [
                f"={page.plant}" if page.plant else "",
                f"+{page.location}" if page.location else "",
                str(doc.page_number(page.id)),
                kind,
                page.name,
                page.fields.get("AENDERUNG", ""),
                page.fields.get("DATUM", ""),
            ]
        )
    return rows


def parts_rows(doc: Document) -> list[list[str]]:
    """Every device (BMK) once, with manufacturer, type, designation and where its main
    function (else its first appearance on a page) sits."""
    rows = []
    for bmk, group in devices(doc).items():
        on_pages = [o for o in group if o.where == SHEET]
        main = next((o for o in on_pages if o.function == "main"), None)
        main = main or (on_pages[0] if on_pages else group[0])
        manufacturer = next((o.manufacturer for o in group if o.manufacturer), "")
        type_ = next((o.type for o in group if o.type), "")
        definition = doc.blocks.get(main.block)
        name = (definition.description if definition else "") or main.block
        area = main.layout_id if main.where == SHEET else MODEL
        page, column = _where(doc, area, main.position.x)
        rows.append([bmk, manufacturer, type_, name, page, column])
    return rows


def _targets(nl: Netlist, pin: Pin) -> str:
    net = nl.net_of_pin(pin.entity_id, pin.name)
    if net is None:
        return ""
    # A terminal's tag already names the point (-X1:3); its pins add nothing.
    others = sorted(
        {
            p.bmk if ":" in p.bmk else f"{p.bmk}:{p.name}"
            for p in nl.pins_of_net(net)
            if p.entity_id != pin.entity_id
        },
        key=_natural,
    )
    return ", ".join(others)


def terminal_rows(doc: Document, nl: Netlist | None = None) -> list[list[str]]:
    """Strip, terminal, what is connected on either side, page and column.
    A terminal is a block with the role "terminal"; its tag reads "-X1:3"."""
    nl = nl or netlist(doc)
    pins_by_entity: dict[str, list[Pin]] = {}
    for pin, _node in nl.pins:
        pins_by_entity.setdefault(pin.entity_id, []).append(pin)
    rows = []
    for bmk, group in devices(doc).items():
        for occ in group:
            if occ.function != "terminal":
                continue
            strip, _, number = bmk.partition(":")
            pins = pins_by_entity.get(occ.entity_id, [])
            sides = [_targets(nl, p) for p in pins[:2]] + ["", ""]
            area = occ.layout_id if occ.where == SHEET else MODEL
            page, column = _where(doc, area, occ.position.x)
            rows.append([strip, number, sides[0], sides[1], page, column])
    rows.sort(key=lambda r: (_natural(r[0]), _natural(r[1])))
    return rows


def cable_rows(doc: Document, nl: Netlist | None = None) -> list[list[str]]:
    """Cable, type (wire labels), cores, devices at either end, pages."""
    nl = nl or netlist(doc)
    cables: dict[str, dict] = {}
    for ends in nl.wire_ends():
        cable = ends.wire.cable.strip()
        if not cable:
            continue
        entry = cables.setdefault(
            cable, {"types": set(), "count": 0, "from": set(), "to": set(), "pages": []}
        )
        if ends.wire.label:
            entry["types"].add(ends.wire.label)
        entry["count"] += 1
        entry["from"] |= {p.bmk for p in nl.pins_at(ends.start)}
        entry["to"] |= {p.bmk for p in nl.pins_at(ends.end)}
        page, _column = _where(doc, ends.area, ends.wire.points[0].x)
        if page and page not in entry["pages"]:
            entry["pages"].append(page)
    rows = []
    for cable in sorted(cables, key=_natural):
        e = cables[cable]
        rows.append(
            [
                cable,
                ", ".join(sorted(e["types"])),
                str(e["count"]),
                ", ".join(sorted(e["from"], key=_natural)),
                ", ".join(sorted(e["to"], key=_natural)),
                ", ".join(e["pages"]),
            ]
        )
    return rows


def report_rows(doc: Document, kind: str, tr: Translate = str) -> list[list[str]]:
    if kind == TOC:
        return toc_rows(doc, tr)
    if kind == PARTS:
        return parts_rows(doc)
    nl = netlist(doc)
    if kind == TERMINALS:
        return terminal_rows(doc, nl)
    if kind == CABLES:
        return cable_rows(doc, nl)
    return []


# -- layout -------------------------------------------------------------------------


@dataclass(frozen=True)
class TableArea:
    left: float
    right: float
    top: float  # first row (below title and header)
    bottom: float

    @property
    def rows(self) -> int:
        return max(1, int((self.bottom - self.top) // ROW))


def table_area(page: SheetLayout) -> TableArea:
    w, h = page.size
    a, b = schematic_inner(w, h)
    top = a.y + MARGIN + TITLE + MARGIN + ROW  # title, gap, header row
    bottom = b.y - SCHEMATIC_TITLE_HEIGHT - MARGIN
    return TableArea(a.x + MARGIN, b.x - MARGIN, top, bottom)


def _text(x: float, y: float, value: str, height: float = TEXT, color=None, **kw) -> Text:
    return Text(
        id=f"gen:{x:.1f}:{y:.1f}:{value[:12]}",
        position=Point(x, y),
        text=value,
        height=height,
        color=color,
        **kw,
    )


def _line(x1: float, y1: float, x2: float, y2: float, weight: float = 0.25) -> Line:
    return Line(
        id=f"gen:{x1:.1f}:{y1:.1f}:{x2:.1f}:{y2:.1f}",
        p1=Point(x1, y1),
        p2=Point(x2, y2),
        lineweight=weight,
    )


def table_entities(
    page: SheetLayout, title: str, headers: Sequence[str], widths: Sequence[float], rows
) -> list[Entity]:
    area = table_area(page)
    total = sum(widths)
    xs = [area.left]
    for share in widths:
        xs.append(xs[-1] + (area.right - area.left) * share / total)
    head_top = area.top - ROW
    out: list[Entity] = [_text(area.left, head_top - MARGIN, title, TITLE)]
    out.append(_line(area.left, head_top, area.right, head_top, 0.35))
    for x, caption in zip(xs, headers, strict=False):
        out.append(_text(x + 1.0, head_top + ROW - (ROW - TEXT) / 2, caption))
    out.append(_line(area.left, area.top, area.right, area.top, 0.35))
    for i, values in enumerate(rows):
        y = area.top + i * ROW
        for x, value in zip(xs, values, strict=False):
            if value:
                out.append(_text(x + 1.0, y + ROW - (ROW - TEXT) / 2, value))
        out.append(_line(area.left, y + ROW, area.right, y + ROW))
    bottom = area.top + ROW * max(len(rows), 1)
    for x in xs:
        out.append(_line(x, head_top, x, bottom))
    return out


COVER_CAPTIONS = (
    "Schaltplan",
    "Kunde",
    "Auftragsnummer",
    "Anlagenbezeichnung",
    "Hersteller (Firma)",
    "Schaltplanersteller",
    "Schaltplan Nr.",
    "Baujahr",
    "Anzahl der Seiten",
)


def cover_entities(doc: Document, page: SheetLayout, tr: Translate = str) -> list[Entity]:
    """Cover page from the project data, laid out like a usual circuit diagram cover;
    laid out for A3 landscape and scaled down on smaller pages (A4)."""
    w, h = page.size
    a, b = schematic_inner(w, h)
    k = min(1.0, (b.y - a.y) / COVER_HEIGHT)
    p = doc.properties
    left = a.x + 20 * k
    value_x = left + 85 * k
    big, normal = 10.0 * k, 5.0 * k
    out: list[Entity] = []
    y = a.y + 30 * k
    title = p.get("PROJEKT", "") or tr("Schaltplan")
    out.append(_text(left, y, title, big))
    y += 18 * k
    out.append(_line(left - 10 * k, y, b.x - 20 * k, y, 0.5))
    y += 14 * k
    for caption, value in (
        ("Kunde", p.get("KUNDE", "")),
        ("Auftragsnummer", p.get("AUFTRAG", "")),
        ("Anlagenbezeichnung", ", ".join(v for v in (p.get("ANLAGE"), p.get("ORT")) if v)),
    ):
        out.append(_text(left, y, tr(caption) + ":", normal))
        out.append(_text(value_x, y, value, normal))
        y += 11 * k
    y += 3 * k
    out.append(_line(left - 10 * k, y, b.x - 20 * k, y, 0.5))
    y += 14 * k
    address = [part.strip() for part in p.get("ADRESSE", "").split(",") if part.strip()]
    out.append(_text(left, y, tr("Hersteller (Firma)") + ":", normal))
    for i, value in enumerate([p.get("FIRMA", ""), *address]):
        out.append(_text(value_x, y + i * 7 * k, value, normal))
    y += (7 * max(len(address) + 1, 1) + 8) * k
    for caption, value in (
        ("Schaltplanersteller", p.get("BEARBEITER", "")),
        ("Schaltplan Nr.", p.get("SCHALTPLANNR", "")),
        ("Baujahr", p.get("BAUJAHR", "")),
        ("Anzahl der Seiten", str(len(doc.sheets))),
    ):
        out.append(_text(left, y, tr(caption) + ":", normal))
        out.append(_text(value_x, y, value, normal))
        y += 9 * k
    return out


def generated_entities(
    doc: Document,
    page: SheetLayout,
    rows_of: Callable[[str], list[list[str]]],
    tr: Translate = str,
    helpers: bool = False,
) -> list[Entity]:
    """Content of a generated page. Lists continue over the pages of the same type in
    page order; ``helpers`` adds a (screen only) note when rows do not fit."""
    if page.kind == COVER:
        return cover_entities(doc, page, tr)
    if page.kind not in COLUMNS:
        return []
    same = [p for p in doc.sheets if p.kind == page.kind]
    index = [p.id for p in same].index(page.id)
    per_page = table_area(page).rows
    rows = rows_of(page.kind)
    chunk = rows[index * per_page : (index + 1) * per_page]
    captions = [tr(c) for c, _ in COLUMNS[page.kind]]
    widths = [share for _, share in COLUMNS[page.kind]]
    title = tr(PAGE_KINDS[page.kind])
    if len(same) > 1:
        title = f"{title} ({index + 1}/{len(same)})"
    out = table_entities(page, title, captions, widths, chunk)
    missing = len(rows) - len(same) * per_page
    if helpers and missing > 0 and index == len(same) - 1:
        area = table_area(page)
        out.append(
            _text(
                area.left,
                area.bottom + 3.5,
                tr("Es fehlen {n} Zeilen: weitere Seite dieses Typs anlegen").format(n=missing),
                TEXT,
                OVERFLOW_COLOR,
            )
        )
    return out


def pages_needed(doc: Document, kind: str, rows: int) -> int:
    """How many pages of a list type the rows need."""
    probe = next((p for p in doc.sheets if p.kind == kind), None)
    if probe is None:
        return 1
    per_page = table_area(probe).rows
    return max(1, -(-rows // per_page))
