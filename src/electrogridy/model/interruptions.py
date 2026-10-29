"""Interruption points: conductors continuing on another page. Pure Python.

All points with the same name across the pages belong together, in page order (then
column, then top to bottom). A pair refers to each other; in a longer chain (a rail
over several pages) each end refers to the neighbouring page it runs to. The two ends
of a rail on one page (on one line, left end pointing left, right end pointing right)
refer to nothing until the rail continues elsewhere. The reference
reads "/3.4" (page 3, column 4).

The arrow always shows the way the conductor flows through the project: at a point
leading on (right, down) it points out of the page, at a point coming from a previous
page (left, up) it points into the page, so both ends of a rail point right.
"""

import math
from collections.abc import Iterable

from electrogridy.model.document import Document
from electrogridy.model.entities import Busbar, Entity, InterruptionPoint, Line, Text, Wire
from electrogridy.model.geometry import Point
from electrogridy.model.sheet import column_at
from electrogridy.model.wires import on_segment, same, segments

ARROW = 1.0  # × text height: length of the arrow wings
GAP = 0.6  # × text height: between arrow and texts


def _places(doc: Document) -> list[tuple[InterruptionPoint, str, int, int]]:
    """Every interruption point with its page id, page index and column (-1: none)."""
    out = []
    for index, page in enumerate(doc.sheets):
        w, h = page.size
        for e in page.entities:
            if isinstance(e, InterruptionPoint):
                column = column_at(w, h, page.columns, e.position.x)
                out.append((e, page.id, index, -1 if column is None else column))
    return out


def reference(doc: Document, to_page: str, column: int) -> str:
    """ "/3.4" (page 3, column 4), "/3" on a page without columns."""
    number = doc.page_number(to_page)
    return f"/{number}.{column}" if column >= 0 else f"/{number}"


def _target(places: list, i: int) -> int | None:
    """Index of the point ``places[i]`` refers to. Two points refer to each other. With
    more (a rail running over several pages) a point pointing on (right, down) refers to
    the next one, a point pointing back (left, up) to the previous one; the ends of the
    chain refer to nothing."""
    n = len(places)
    forward = [_forward(p[0]) for p in places]
    if n == 2:
        # A pair refers to each other, except the two ends of one rail on one page: on
        # one line, the left end pointing left, the right end pointing right.
        (a, page_a, *_), (b, page_b, *_) = places
        rail = (
            page_a == page_b
            and not forward[0]
            and forward[1]
            and abs(a.position.y - b.position.y) < 1e-6
            and a.position.x < b.position.x
        )
        return None if rail else 1 - i
    j = i + 1 if forward[i] else i - 1
    return j if 0 <= j < n else None


def _forward(point: InterruptionPoint) -> bool:
    """Pointing on (right or down) rather than back (left or up)."""
    return not 90.0 <= point.direction % 360 <= 180.0


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
        for i, (point, _page, _index, _column) in enumerate(places):
            j = _target(places, i)
            if j is None:
                continue
            target, target_page, _ti, target_column = places[j]
            targets[point.id] = (reference(doc, target_page, target_column), target_page)
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
    j = _target(same, i)
    if j is None:
        return None
    target = same[j]
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


def axis_direction(dx: float, dy: float) -> float:
    """0 (right), 90 (up), 180 (left) or 270 (down), whichever is nearest to the vector."""
    if abs(dx) >= abs(dy):
        return 0.0 if dx >= 0 else 180.0
    return 270.0 if dy > 0 else 90.0


def outward_direction(entities: Iterable[Entity], p: Point) -> float | None:
    """Direction leading out of the one conductor (wire, line, bus bar) that ends at
    ``p``: where the stem and the texts of an interruption point placed there belong, so
    that they never lie on the conductor. None if no conductor or several end there, or
    one runs through."""
    inner: list[Point] = []
    for e in entities:
        if isinstance(e, Wire):
            pairs = segments(e.points)
        elif isinstance(e, Line | Busbar):
            pairs = [(e.p1, e.p2)]
        else:
            continue
        for a, b in pairs:
            if same(a, b):
                continue
            if same(p, a):
                inner.append(b)
            elif same(p, b):
                inner.append(a)
            elif on_segment(p, a, b):
                return None
    if len(inner) != 1:
        return None
    return axis_direction(p.x - inner[0].x, p.y - inner[0].y)


def interruption_geometry(p: InterruptionPoint, ref: str | None) -> list[Entity]:
    """Arrow on the stem leading out of the conductor end, name and (if paired)
    reference beyond it. The arrow head points the way the conductor flows: outwards
    where it leads on, back onto the conductor end where it comes from a previous page."""
    h = p.height
    a = math.radians(p.direction)
    ux, uy = math.cos(a), -math.sin(a)
    style = {"layer": p.layer, "color": p.color, "lineweight": p.lineweight}
    tip = Point(p.position.x + ux * ARROW * h, p.position.y + uy * ARROW * h)
    parts: list[Entity] = [Line(id=f"{p.id}:stem", p1=p.position, p2=tip, linetype=None, **style)]
    head, pointing = (tip, p.direction) if _forward(p) else (p.position, p.direction + 180.0)
    for k, turn in enumerate((135.0, -135.0)):
        r = math.radians(pointing + turn)
        wing = Point(head.x + math.cos(r) * ARROW * h, head.y - math.sin(r) * ARROW * h)
        parts.append(Line(id=f"{p.id}:wing{k}", p1=head, p2=wing, linetype=None, **style))
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
