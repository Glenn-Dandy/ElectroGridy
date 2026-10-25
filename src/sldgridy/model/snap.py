"""Object snap: find characteristic points of entities near the cursor."""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from sldgridy.model.entities import (
    Arc,
    Busbar,
    Circle,
    Entity,
    Line,
    Polyline,
    Rectangle,
    Viewport,
    Wire,
)
from sldgridy.model.geometry import Point, distance
from sldgridy.model.primitives import (
    ArcPrim,
    Segment,
    arc_endpoints,
    arc_midpoint,
    intersect,
    primitives,
    rect_corners,
    segment_midpoint,
)


class SnapMode(StrEnum):
    CONNECTION = "connection"
    ENDPOINT = "endpoint"
    MIDPOINT = "midpoint"
    INTERSECTION = "intersection"
    CENTER = "center"
    PERPENDICULAR = "perpendicular"
    BUSBAR = "busbar"
    NEAREST = "nearest"


ALL_MODES = frozenset(SnapMode)

# Tie-break for hits at the same distance.
_RANK = {
    SnapMode.CONNECTION: 0,
    SnapMode.PERPENDICULAR: 1,
    SnapMode.ENDPOINT: 2,
    SnapMode.INTERSECTION: 3,
    SnapMode.MIDPOINT: 4,
    SnapMode.CENTER: 5,
    SnapMode.BUSBAR: 6,
    SnapMode.NEAREST: 7,
}


@dataclass(frozen=True)
class SnapHit:
    point: Point
    mode: SnapMode


# Hook for entity types that contribute extra candidates (block references,
# connection points). Each returns hits regardless of the cursor position.
ExtraCandidates = Callable[[Entity], list[SnapHit]]


def candidates(e: Entity, modes: frozenset[SnapMode]) -> list[SnapHit]:
    hits: list[SnapHit] = []
    end, mid, cen = SnapMode.ENDPOINT, SnapMode.MIDPOINT, SnapMode.CENTER
    match e:
        case Line() | Busbar():
            if end in modes:
                hits += [SnapHit(e.p1, end), SnapHit(e.p2, end)]
        case Wire():
            if end in modes:
                hits += [SnapHit(p, end) for p in e.points]
        case Polyline() | Rectangle() | Viewport():
            pts = list(e.points) if isinstance(e, Polyline) else rect_corners(e)
            if end in modes:
                hits += [SnapHit(p, end) for p in pts]
        case Circle():
            if cen in modes:
                hits.append(SnapHit(e.center, cen))
        case Arc():
            if end in modes:
                hits += [SnapHit(p, end) for p in arc_endpoints(e)]
            if mid in modes:
                hits.append(SnapHit(arc_midpoint(e), mid))
            if cen in modes:
                hits.append(SnapHit(e.center, cen))
    if mid in modes and isinstance(e, Line | Polyline | Rectangle | Wire | Busbar | Viewport):
        hits += [SnapHit(segment_midpoint(s), mid) for s in primitives(e)]
    return hits


def nearest_on_segment(p: Point, a: Point, b: Point) -> Point:
    # Exact results for axis-parallel segments (bus bars), so wire ends lie on them.
    if a.y == b.y:
        return Point(min(max(p.x, min(a.x, b.x)), max(a.x, b.x)), a.y)
    if a.x == b.x:
        return Point(a.x, min(max(p.y, min(a.y, b.y)), max(a.y, b.y)))
    dx, dy = b.x - a.x, b.y - a.y
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return a
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length2))
    return Point(a.x + t * dx, a.y + t * dy)


def _snap_value(v: float, grid: float | None) -> float:
    return math.floor(v / grid + 0.5) * grid if grid else v


def on_busbar(cursor: Point, bar: Busbar, grid: float | None) -> Point:
    """Point of the bar nearest to the cursor, on the grid along axis-parallel bars."""
    return on_segment(cursor, bar.p1, bar.p2, grid)


def on_segment(cursor: Point, a: Point, b: Point, grid: float | None) -> Point:
    """Point of segment a-b nearest to the cursor; along an axis-parallel segment the
    free coordinate stays on the grid (circuit diagrams keep their grid)."""
    if a.y == b.y:
        lo, hi = sorted((a.x, b.x))
        return Point(min(max(_snap_value(cursor.x, grid), lo), hi), a.y)
    if a.x == b.x:
        lo, hi = sorted((a.y, b.y))
        return Point(a.x, min(max(_snap_value(cursor.y, grid), lo), hi))
    return nearest_on_segment(cursor, a, b)


def perpendicular_foot(base: Point, a: Point, b: Point) -> Point | None:
    """Foot of the perpendicular from ``base`` onto segment a-b, if it lies on the segment."""
    dx, dy = b.x - a.x, b.y - a.y
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return None
    t = ((base.x - a.x) * dx + (base.y - a.y) * dy) / length2
    if t < -1e-9 or t > 1 + 1e-9:
        return None
    if a.y == b.y:
        return Point(base.x, a.y)
    if a.x == b.x:
        return Point(a.x, base.y)
    return Point(a.x + t * dx, a.y + t * dy)


# Intersections are searched pair by pair; with more edges than this near the cursor
# (a detailed device drawing zoomed out) they are left out, the rest still snaps.
MAX_INTERSECTION_PRIMITIVES = 300


def _prim_near(prim, cursor: Point, r: float) -> bool:
    """Whether a snap point of the primitive can lie within ``r`` of the cursor."""
    if isinstance(prim, Segment):
        return (
            min(prim.a.x, prim.b.x) - r <= cursor.x <= max(prim.a.x, prim.b.x) + r
            and min(prim.a.y, prim.b.y) - r <= cursor.y <= max(prim.a.y, prim.b.y) + r
        )
    # Arcs and circles: the curve or the centre near the cursor.
    d = distance(cursor, prim.center)
    return d <= r or abs(d - prim.radius) <= r


def _near(e: Entity, cursor: Point, r: float) -> bool:
    prims = primitives(e)
    return not prims or any(_prim_near(p, cursor, r) for p in prims)


def find_snap(
    cursor: Point,
    entities: Iterable[Entity],
    aperture: float,
    modes: frozenset[SnapMode] = ALL_MODES,
    extra: ExtraCandidates | None = None,
    decompose: Callable[[Entity], list[Entity]] | None = None,
    base: Point | None = None,
    grid: float | None = None,
) -> SnapHit | None:
    """Best snap point within ``aperture`` mm of ``cursor``.

    Priority: connection points of symbols, then the perpendicular foot from
    ``base`` (the command's last point), then the nearest characteristic
    point, and only then a free point on a bus bar (on the grid along it).
    ``decompose`` may expand compound entities into simple ones.
    """
    simple: list[Entity] = []
    hits: list[SnapHit] = []
    for e in entities:
        if extra is not None:
            hits += [h for h in extra(e) if h.mode in modes]
        parts = decompose(e) if decompose is not None else [e]
        # A symbol is found by its whole outline; only its parts near the cursor count
        # (a device drawing has thousands).
        simple += parts if len(parts) <= 1 else [q for q in parts if _near(q, cursor, aperture)]
    for e in simple:
        hits += candidates(e, modes)
        if isinstance(e, Busbar) and SnapMode.BUSBAR in modes:
            hits.append(SnapHit(on_busbar(cursor, e, grid), SnapMode.BUSBAR))
        if base is not None and SnapMode.PERPENDICULAR in modes:
            for prim in primitives(e):
                if isinstance(prim, Segment):
                    foot = perpendicular_foot(base, prim.a, prim.b)
                    if foot is not None and distance(foot, base) > 1e-9:
                        hits.append(SnapHit(foot, SnapMode.PERPENDICULAR))
        if SnapMode.NEAREST in modes and not isinstance(e, Busbar):
            for prim in primitives(e):
                if isinstance(prim, Segment):
                    hits.append(SnapHit(on_segment(cursor, prim.a, prim.b, grid), SnapMode.NEAREST))
                else:
                    on_arc = _nearest_on_arc(cursor, prim)
                    if on_arc is not None:
                        hits.append(SnapHit(on_arc, SnapMode.NEAREST))
    if SnapMode.INTERSECTION in modes:
        prims = [p for e in simple for p in primitives(e) if _prim_near(p, cursor, aperture)]
        if len(prims) > MAX_INTERSECTION_PRIMITIVES:
            prims = []
        for i, p in enumerate(prims):
            for q in prims[i + 1 :]:
                hits += [SnapHit(x, SnapMode.INTERSECTION) for x in intersect(p, q)]

    near = [h for h in hits if distance(h.point, cursor) <= aperture]
    if not near:
        return None
    for group in (
        {SnapMode.CONNECTION},
        {SnapMode.PERPENDICULAR},
        {SnapMode.ENDPOINT, SnapMode.INTERSECTION, SnapMode.MIDPOINT, SnapMode.CENTER},
        {SnapMode.BUSBAR},
        {SnapMode.NEAREST},
    ):
        pool = [h for h in near if h.mode in group]
        if pool:
            return min(pool, key=lambda h: (round(distance(h.point, cursor), 9), _RANK[h.mode]))
    return None


def _nearest_on_arc(cursor: Point, arc: ArcPrim) -> Point | None:
    dx, dy = cursor.x - arc.center.x, cursor.y - arc.center.y
    d = math.hypot(dx, dy)
    if d <= 1e-12 or arc.radius <= 0:
        return None
    angle = math.degrees(math.atan2(-dy, dx)) % 360
    if not arc.contains_angle(angle):
        return None
    k = arc.radius / d
    return Point(arc.center.x + dx * k, arc.center.y + dy * k)


def _circle_segment(center: Point, r: float, a: Point, b: Point) -> list[Point]:
    dx, dy = b.x - a.x, b.y - a.y
    fx, fy = a.x - center.x, a.y - center.y
    qa = dx * dx + dy * dy
    if qa <= 1e-12:
        return []
    qb = 2 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - r * r
    disc = qb * qb - 4 * qa * qc
    if disc < 0:
        return []
    root = math.sqrt(disc)
    hits = []
    for t in ((-qb - root) / (2 * qa), (-qb + root) / (2 * qa)):
        if -1e-9 <= t <= 1 + 1e-9:
            hits.append(Point(a.x + t * dx, a.y + t * dy))
    return hits


def _circle_circle(c1: Point, r1: float, c2: Point, r2: float) -> list[Point]:
    d = math.hypot(c2.x - c1.x, c2.y - c1.y)
    if d <= 1e-12 or d > r1 + r2 or d < abs(r1 - r2):
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    mx, my = c1.x + a * (c2.x - c1.x) / d, c1.y + a * (c2.y - c1.y) / d
    ox, oy = h * (c2.y - c1.y) / d, h * (c2.x - c1.x) / d
    return [Point(mx + ox, my - oy), Point(mx - ox, my + oy)]


def circle_hits(center: Point, radius: float, entities: Iterable[Entity]) -> list[Point]:
    """Where a circle (e.g. a line of fixed length turning around its start) crosses
    the given entities' edges: lines, polylines, rectangles, wires, bus bars, circles."""
    hits: list[Point] = []
    for e in entities:
        if isinstance(e, Circle):
            hits += _circle_circle(center, radius, e.center, e.radius)
            continue
        for a, b in edges_of(e):
            hits += _circle_segment(center, radius, a, b)
    return hits


def edges_of(e: Entity) -> list[tuple[Point, Point]]:
    if isinstance(e, Line | Busbar):
        return [(e.p1, e.p2)]
    if isinstance(e, Rectangle):
        c = [e.p1, Point(e.p2.x, e.p1.y), e.p2, Point(e.p1.x, e.p2.y)]
        return [(c[i], c[(i + 1) % 4]) for i in range(4)]
    if isinstance(e, Polyline):
        pts = list(e.points)
        edges = list(zip(pts, pts[1:], strict=False))
        if e.closed and len(pts) > 2:
            edges.append((pts[-1], pts[0]))
        return edges
    if isinstance(e, Wire):
        return list(zip(e.points, e.points[1:], strict=False))
    return []
