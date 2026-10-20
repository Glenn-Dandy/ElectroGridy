"""Interruption points: conductors continuing on another page. Pure Python.

All points with the same name across the pages of the multi-line diagram belong
together. In page order (then column, then top to bottom) each one refers to the next,
the last one back to the first; so a pair refers to each other. The reference reads
"/3.4" (page 3, column 4), with the plant and location in front when the target lies
in another group ("=PV1 +UV2 /1.7").
"""

import math
from collections.abc import Iterable

from sldgridy.model.document import Document, designation
from sldgridy.model.entities import Entity, InterruptionPoint, Line, Text
from sldgridy.model.geometry import Point
from sldgridy.model.sheet import column_at

ARROW = 1.0  # × text height: length of the arrow wings
GAP = 0.6  # × text height: between arrow and texts


def _places(doc: Document) -> list[tuple[InterruptionPoint, str, int, int]]:
    """Every interruption point with its page id, page index and column."""
    out = []
    for index, page in enumerate(doc.pages):
        w, h = page.size
        for e in page.entities:
            if isinstance(e, InterruptionPoint):
                out.append((e, page.id, index, column_at(w, h, page.columns, e.position.x)))
    return out


def reference(doc: Document, from_page: str, to_page: str, column: int) -> str:
    """ "/3.4", or with the designation when the target is in another plant/location."""
    src, dst = doc.page(from_page), doc.page(to_page)
    number = doc.page_number(to_page)[0]
    ref = f"/{number}.{column}" if column else f"/{number}"
    if (src.plant, src.location) != (dst.plant, dst.location):
        prefix = designation(dst.plant, dst.location)
        if prefix:
            ref = f"{prefix} {ref}"
    return ref


def interruption_targets(doc: Document) -> dict[str, tuple[str, str]]:
    """Point id -> (reference text, id of the page it refers to); unpaired points are
    left out."""
    groups: dict[str, list[tuple[InterruptionPoint, str, int, int]]] = {}
    for place in _places(doc):
        name = place[0].name.strip()
        if name:
            groups.setdefault(name, []).append(place)
    targets: dict[str, tuple[str, str]] = {}
    for places in groups.values():
        if len(places) < 2:
            continue
        places.sort(key=lambda p: (p[2], p[3], p[0].position.y, p[0].position.x))
        for i, (point, page_id, _index, _column) in enumerate(places):
            target, target_page, _ti, target_column = places[(i + 1) % len(places)]
            targets[point.id] = (reference(doc, page_id, target_page, target_column), target_page)
    return targets


def partner(doc: Document, point_id: str) -> tuple[str, InterruptionPoint] | None:
    """Page id and point the given point refers to."""
    places = _places(doc)
    by_id = {p[0].id: p for p in places}
    if point_id not in by_id:
        return None
    name = by_id[point_id][0].name.strip()
    same = sorted(
        (p for p in places if p[0].name.strip() == name),
        key=lambda p: (p[2], p[3], p[0].position.y, p[0].position.x),
    )
    if len(same) < 2:
        return None
    i = [p[0].id for p in same].index(point_id)
    target = same[(i + 1) % len(same)]
    return target[1], target[0]


def unpaired_names(doc: Document) -> list[str]:
    """Names used only once, in page order: the usual next name to place."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for point, *_ in _places(doc):
        name = point.name.strip()
        if name and name not in counts:
            order.append(name)
        counts[name] = counts.get(name, 0) + 1
    return [n for n in order if counts[n] == 1]


def interruption_geometry(p: InterruptionPoint, ref: str | None) -> list[Entity]:
    """Arrow pointing the way the conductor runs on, name and (if paired) reference."""
    h = p.height
    a = math.radians(p.direction)
    ux, uy = math.cos(a), -math.sin(a)
    style = {"layer": p.layer, "color": p.color, "lineweight": p.lineweight}
    tip = Point(p.position.x + ux * ARROW * h, p.position.y + uy * ARROW * h)
    parts: list[Entity] = [Line(id=f"{p.id}:stem", p1=p.position, p2=tip, linetype=None, **style)]
    for k, turn in enumerate((135.0, -135.0)):
        r = math.radians(p.direction + turn)
        wing = Point(tip.x + math.cos(r) * ARROW * h, tip.y - math.sin(r) * ARROW * h)
        parts.append(Line(id=f"{p.id}:wing{k}", p1=tip, p2=wing, linetype=None, **style))
    # One horizontal line of text (conductors lie 5 mm apart): name and reference,
    # beyond the tip of a horizontal arrow, right of a vertical one.
    if abs(ux) >= abs(uy):
        x = tip.x + (GAP * h if ux >= 0 else -GAP * h)
        align = "left" if ux >= 0 else "right"
        y = p.position.y
    else:
        x = p.position.x + GAP * h + ARROW * h
        align = "left"
        y = (p.position.y + tip.y) / 2
    text = f"{p.name}  {ref}" if ref else p.name
    parts.append(
        Text(
            id=f"{p.id}:text",
            position=Point(x, y + 0.5 * h),
            text=text,
            height=h,
            halign=align,
            **style,
        )
    )
    return parts


def points(entities: Iterable[Entity]) -> list[InterruptionPoint]:
    return [e for e in entities if isinstance(e, InterruptionPoint)]
