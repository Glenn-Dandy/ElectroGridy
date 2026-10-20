"""Reports of the project: table of contents, parts list, terminal plan, cable list.
Pure Python: rows of text, and tables laid out on report pages.

Report pages are pages of the multi-line diagram marked with ``report`` (their kind);
creating the reports again replaces them. Headers and titles come from the caller
(translated); the rows are data.
"""

import math
import re
from collections.abc import Sequence

from sldgridy.model.container import EntityContainer
from sldgridy.model.devices import MODEL, PAGE, devices, page_reference
from sldgridy.model.document import Document, SheetLayout, designation, new_page
from sldgridy.model.entities import Line, Text, new_id
from sldgridy.model.geometry import Point
from sldgridy.model.netlist import Netlist, Pin, netlist
from sldgridy.model.sheet import COLUMN_STRIP, frame_corners

TOC, PARTS, TERMINALS, CABLES = "toc", "parts", "terminals", "cables"
REPORTS = (TOC, PARTS, TERMINALS, CABLES)

TEXT = 2.5
ROW = 5.0
TITLE = 5.0
MARGIN = 5.0
TITLE_BLOCK_HEIGHT = 36.0  # free space left above the title block


def _natural(text: str) -> list:
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def _place(doc: Document, area: str, layout_id: str | None, position: Point) -> str:
    if area == MODEL:
        return "SLD"
    from sldgridy.model.devices import Occurrence

    probe = Occurrence("", "", "", PAGE, layout_id, position, "", "", ())
    return page_reference(doc, None, probe)


# -- rows ---------------------------------------------------------------------


def toc_rows(doc: Document) -> list[list[str]]:
    """Designation, page number and description of every page."""
    rows = []
    for page in doc.pages:
        number = doc.page_number(page.id)[0]
        rows.append([designation(page.plant, page.location), f"/{number}", page.name])
    return rows


def parts_rows(doc: Document) -> list[list[str]]:
    """One row per kind of device (block, manufacturer, type) with count and tags.
    Terminals and contacts of a device are not parts of their own."""
    groups: dict[tuple[str, str, str], list[str]] = {}
    for bmk, group in devices(doc).items():
        if all(o.function in ("aux", "terminal") for o in group):
            continue
        main = next((o for o in group if o.function == "main"), None) or group[0]
        manufacturer = next((o.manufacturer for o in group if o.manufacturer), "")
        type_ = next((o.type for o in group if o.type), "")
        groups.setdefault((main.block, manufacturer, type_), []).append(bmk)
    rows = []
    for i, (key, tags) in enumerate(
        sorted(groups.items(), key=lambda kv: [_natural(x) for x in kv[0]]), start=1
    ):
        block, manufacturer, type_ = key
        rows.append([str(i), str(len(tags)), block, manufacturer, type_, ", ".join(tags)])
    return rows


def _targets(nl: Netlist, pin: Pin) -> str:
    net = nl.net_of_pin(pin.entity_id, pin.name)
    if net is None:
        return ""
    others = sorted(
        {f"{p.bmk}:{p.name}" for p in nl.pins_of_net(net) if p.entity_id != pin.entity_id},
        key=_natural,
    )
    return ", ".join(others)


def terminal_rows(doc: Document, nl: Netlist | None = None) -> list[list[str]]:
    """Terminal strip, terminal, what is connected on either side, place.
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
            area = occ.layout_id if occ.where == PAGE else MODEL
            rows.append(
                [strip, number, sides[0], sides[1], _place(doc, area, occ.layout_id, occ.position)]
            )
    rows.sort(key=lambda r: (_natural(r[0]), _natural(r[1])))
    return rows


def cable_rows(doc: Document, nl: Netlist | None = None) -> list[list[str]]:
    """Cable, type (wire labels), conductors, devices at either end, places."""
    nl = nl or netlist(doc)
    cables: dict[str, dict] = {}
    for ends in nl.wire_ends():
        cable = ends.wire.cable.strip()
        if not cable:
            continue
        entry = cables.setdefault(
            cable, {"types": set(), "count": 0, "from": set(), "to": set(), "places": []}
        )
        if ends.wire.label:
            entry["types"].add(ends.wire.label)
        entry["count"] += 1
        entry["from"] |= {p.bmk for p in nl.pins_at(ends.start)}
        entry["to"] |= {p.bmk for p in nl.pins_at(ends.end)}
        place = _place(
            doc, ends.area, None if ends.area == MODEL else ends.area, ends.wire.points[0]
        )
        if place not in entry["places"]:
            entry["places"].append(place)
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
                ", ".join(e["places"]),
            ]
        )
    return rows


# -- layout -------------------------------------------------------------------


def rows_per_page(page: SheetLayout) -> int:
    w, h = page.size
    a, b = frame_corners(w, h)
    top = a.y + COLUMN_STRIP + MARGIN + TITLE + ROW  # title, then the header row
    bottom = b.y - TITLE_BLOCK_HEIGHT - MARGIN
    return max(1, int((bottom - top) // ROW))


def table_entities(
    page: SheetLayout,
    title: str,
    headers: Sequence[str],
    widths: Sequence[float],
    rows: Sequence[Sequence[str]],
) -> list:
    """Title, header row and ``rows`` as texts and lines; widths are shares of the
    table width."""
    w, h = page.size
    a, b = frame_corners(w, h)
    left, right = a.x + MARGIN, b.x - MARGIN
    total = sum(widths)
    xs = [left]
    for share in widths:
        xs.append(xs[-1] + (right - left) * share / total)
    y = a.y + COLUMN_STRIP + MARGIN + TITLE
    out = [Text(id=new_id(), position=Point(left, y), text=title, height=TITLE)]
    y += ROW * 0.6

    def row(values: Sequence[str], top: float) -> None:
        for x, value in zip(xs, values, strict=False):
            if value:
                out.append(
                    Text(
                        id=new_id(),
                        position=Point(x + 1.0, top + ROW - (ROW - TEXT) / 2),
                        text=value,
                        height=TEXT,
                    )
                )
        out.append(Line(id=new_id(), p1=Point(left, top + ROW), p2=Point(right, top + ROW)))

    out.append(Line(id=new_id(), p1=Point(left, y), p2=Point(right, y), lineweight=0.35))
    row(headers, y)
    out[-1] = Line(id=new_id(), p1=Point(left, y + ROW), p2=Point(right, y + ROW), lineweight=0.35)
    for i, values in enumerate(rows):
        row(values, y + ROW * (i + 1))
    bottom = y + ROW * (len(rows) + 1)
    for x in xs:
        out.append(Line(id=new_id(), p1=Point(x, y), p2=Point(x, bottom)))
    return out


def report_pages(
    kind: str,
    title: str,
    headers: Sequence[str],
    widths: Sequence[float],
    rows: Sequence[Sequence[str]],
) -> list[SheetLayout]:
    """As many report pages as the rows need (at least one)."""
    probe = new_page()
    per_page = rows_per_page(probe)
    count = max(1, math.ceil(len(rows) / per_page))
    pages = []
    for i in range(count):
        page = new_page(title if count == 1 else f"{title} ({i + 1})")
        page.report = kind
        chunk = rows[i * per_page : (i + 1) * per_page]
        page.entities = EntityContainer(table_entities(page, title, headers, widths, chunk))
        pages.append(page)
    return pages
