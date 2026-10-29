"""Wire helpers: orthogonal routing, junctions, labels and following moved symbols."""

import math
from collections.abc import Iterable, Mapping
from dataclasses import replace

from electrogridy.model.blocks import BlockDefinition, world_connections
from electrogridy.model.entities import (
    BlockReference,
    Busbar,
    ConnectionPoint,
    Entity,
    JunctionMark,
    Text,
    Wire,
)
from electrogridy.model.geometry import Point, distance

EPS = 1e-6
LABEL_GAP = 1.0  # mm between wire and label
LABEL_INSET = 2.5  # mm from the segment end for left or right aligned labels
LABEL_ALIGNS = ("left", "center", "right")


def same(a: Point, b: Point) -> bool:
    return abs(a.x - b.x) <= EPS and abs(a.y - b.y) <= EPS


def simplify(points: Iterable[Point]) -> tuple[Point, ...]:
    """Drop repeated points and points in the middle of straight runs."""
    pts: list[Point] = []
    for p in points:
        if not pts or not same(p, pts[-1]):
            pts.append(p)
    changed = True
    while changed and len(pts) > 2:
        changed = False
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            if (abs(a.x - b.x) <= EPS and abs(b.x - c.x) <= EPS) or (
                abs(a.y - b.y) <= EPS and abs(b.y - c.y) <= EPS
            ):
                del pts[i]
                changed = True
                break
    return tuple(pts)


def elbow(start: Point, end: Point, horizontal_first: bool | None = None) -> list[Point]:
    """Orthogonal path from ``start`` to ``end`` (without ``start``)."""
    if abs(start.x - end.x) <= EPS or abs(start.y - end.y) <= EPS:
        return [end]
    if horizontal_first is None:
        horizontal_first = abs(end.x - start.x) >= abs(end.y - start.y)
    corner = Point(end.x, start.y) if horizontal_first else Point(start.x, end.y)
    return [corner, end]


def segments(points: tuple[Point, ...]) -> list[tuple[Point, Point]]:
    return list(zip(points, points[1:], strict=False))


def _on_segment_interior(p: Point, a: Point, b: Point) -> bool:
    if same(p, a) or same(p, b):
        return False
    if abs(a.x - b.x) <= EPS:
        return abs(p.x - a.x) <= EPS and min(a.y, b.y) - EPS <= p.y <= max(a.y, b.y) + EPS
    if abs(a.y - b.y) <= EPS:
        return abs(p.y - a.y) <= EPS and min(a.x, b.x) - EPS <= p.x <= max(a.x, b.x) + EPS
    # General segment (should not happen for wires).
    cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
    if abs(cross) > EPS * max(1.0, distance(a, b)):
        return False
    dot = (p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)
    return 0 < dot < distance(a, b) ** 2


JUNCTION_MIN_DIAMETER = 1.0  # mm
JUNCTION_WEIGHT_FACTOR = 4.0  # diameter as a multiple of the wire's line width


def junctions(entities: Iterable[Entity]) -> list[tuple[Point, Entity]]:
    """Connection dots with the entity that gives their style.

    Automatic dots: a wire end on the inside of another wire, a wire end on a
    bus bar, or three or more wire ends at one point. Junction marks then
    force (``connected``) or suppress dots at their position.
    """
    entities = list(entities)
    wires = [e for e in entities if isinstance(e, Wire) and len(e.points) >= 2]
    bars = [e for e in entities if isinstance(e, Busbar)]
    marks = [e for e in entities if isinstance(e, JunctionMark)]
    # Index axis-parallel segments by their constant coordinate as (low, high, wire id)
    # of the running coordinate, so one end is checked with plain comparisons.
    vertical: dict[float, list[tuple[float, float, str]]] = {}
    horizontal: dict[float, list[tuple[float, float, str]]] = {}
    other: list[tuple[str, Point, Point]] = []
    ends: dict[tuple[float, float], list[Wire]] = {}
    for w in wires:
        for a, b in segments(w.points):
            if abs(a.x - b.x) <= EPS:
                vertical.setdefault(round(a.x, 6), []).append((min(a.y, b.y), max(a.y, b.y), w.id))
            elif abs(a.y - b.y) <= EPS:
                horizontal.setdefault(round(a.y, 6), []).append(
                    (min(a.x, b.x), max(a.x, b.x), w.id)
                )
            else:
                other.append((w.id, a, b))
        for p in (w.points[0], w.points[-1]):
            ends.setdefault((round(p.x, 6), round(p.y, 6)), []).append(w)

    def inside(runs: list[tuple[float, float, str]], v: float, owner_ids: set[str]) -> bool:
        return any(lo + EPS < v < hi - EPS and wid not in owner_ids for lo, hi, wid in runs)

    dots: dict[tuple[float, float], tuple[Point, Entity]] = {}
    for (x, y), owners in ends.items():
        p = Point(x, y)
        if len(owners) >= 3:
            dots[(x, y)] = (p, owners[0])
            continue
        owner_ids = {w.id for w in owners}
        if (
            inside(vertical.get(x, ()), y, owner_ids)
            or inside(horizontal.get(y, ()), x, owner_ids)
            or any(wid not in owner_ids and _on_segment_interior(p, a, b) for wid, a, b in other)
            or any(on_segment(p, bar.p1, bar.p2) for bar in bars)
        ):
            dots[(x, y)] = (p, owners[0])
    for mark in marks:
        key = (round(mark.position.x, 6), round(mark.position.y, 6))
        dots.pop(key, None)
        if mark.connected:
            dots[key] = (mark.position, mark)
    return list(dots.values())


def on_segment(p: Point, a: Point, b: Point) -> bool:
    """``p`` lies on the segment a-b, end points included."""
    return same(p, a) or same(p, b) or _on_segment_interior(p, a, b)


def entities_at(entities: Iterable[Entity], p: Point) -> list[Entity]:
    """Wires and bus bars passing through ``p``."""
    out: list[Entity] = []
    for e in entities:
        if (
            isinstance(e, Wire)
            and any(on_segment(p, a, b) for a, b in segments(e.points))
            or isinstance(e, Busbar)
            and on_segment(p, e.p1, e.p2)
        ):
            out.append(e)
    return out


def remove_vertex(wire: Wire, index: int) -> Wire | None:
    """Wire without point ``index``; corners are replaced so segments stay orthogonal."""
    pts = list(wire.points)
    if len(pts) <= 2:
        return None
    if index in (0, len(pts) - 1):
        del pts[index]
        return replace(wire, points=simplify(pts))
    prev, removed, nxt = pts[index - 1], pts[index], pts[index + 1]
    corners = [Point(nxt.x, prev.y), Point(prev.x, nxt.y)]
    others = [c for c in corners if not same(c, removed)]
    pts[index] = others[0] if others else corners[0]
    new = simplify(pts)
    return replace(wire, points=new) if len(new) >= 2 else None


def junction_points(entities: Iterable[Entity]) -> list[Point]:
    return [p for p, _ in junctions(entities)]


def junction_diameter(lineweight: float) -> float:
    return max(JUNCTION_MIN_DIAMETER, JUNCTION_WEIGHT_FACTOR * lineweight)


LABEL_POSITIONS = ("auto", "start", "end", "free")


def path_length(points: tuple[Point, ...]) -> float:
    return sum(distance(a, b) for a, b in segments(points))


def point_along(points: tuple[Point, ...], at: float) -> tuple[Point, Point, Point]:
    """Point at path distance ``at`` from the start (clamped) and its segment (a, b)."""
    segs = [(a, b) for a, b in segments(points) if distance(a, b) > EPS]
    if not segs:
        return points[0], points[0], points[-1]
    at = max(0.0, at)
    for a, b in segs:
        length = distance(a, b)
        if at <= length + EPS:
            t = min(at / length, 1.0)
            return Point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t), a, b
        at -= length
    a, b = segs[-1]
    return b, a, b


def project_on_path(points: tuple[Point, ...], p: Point) -> float:
    """Path distance from the start of the point on the wire nearest to ``p``."""
    best, best_at, walked = None, 0.0, 0.0
    for a, b in segments(points):
        length = distance(a, b)
        if length <= EPS:
            continue
        t = ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / length**2
        t = min(max(t, 0.0), 1.0)
        foot = Point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)
        d = distance(foot, p)
        if best is None or d < best - EPS:
            best, best_at = d, walked + t * length
        walked += length
    return best_at


def label_anchor(wire: Wire) -> tuple[Point, Point, Point, str]:
    """Anchor point of the label, its segment (a, b) and the text alignment."""
    align = wire.label_align if wire.label_align in LABEL_ALIGNS else "center"
    if wire.label_pos not in ("start", "end", "free"):
        a, b = max(segments(wire.points), key=lambda s: distance(*s))
        mid = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
        vertical = abs(a.x - b.x) <= EPS
        if vertical:
            bottom, top = max(a.y, b.y), min(a.y, b.y)
            along = {"left": bottom - LABEL_INSET, "center": mid.y, "right": top + LABEL_INSET}
            return Point(mid.x, along[align]), a, b, align
        left, right = min(a.x, b.x), max(a.x, b.x)
        along = {"left": left + LABEL_INSET, "center": mid.x, "right": right - LABEL_INSET}
        return Point(along[align], mid.y), a, b, align
    total = path_length(wire.points)
    if wire.label_pos == "start":
        at = min(LABEL_INSET, total / 2)
    elif wire.label_pos == "end":
        at = max(total - LABEL_INSET, total / 2)
    else:
        at = wire.label_at
    p, a, b = point_along(wire.points, at)
    if wire.label_pos == "free":
        return p, a, b, align
    # Start and end: the text runs from the anchor into the wire.
    vertical = abs(a.x - b.x) <= EPS
    # Reading direction: left to right, vertical texts bottom to top.
    forward_reads = (a.y > b.y) if vertical else (b.x > a.x)
    inward_reads = forward_reads if wire.label_pos == "start" else not forward_reads
    return p, a, b, "left" if inward_reads else "right"


def label_text(wire: Wire) -> Text | None:
    """The wire's label as a text entity beside the wire (see ``label_anchor``)."""
    if not wire.label or len(wire.points) < 2:
        return None
    anchor, a, b, align = label_anchor(wire)
    h = wire.label_height
    if abs(a.x - b.x) <= EPS:
        # Rotation 90 reads bottom to top; the glyphs extend towards -x.
        x = anchor.x - LABEL_GAP if wire.label_side > 0 else anchor.x + LABEL_GAP + h
        position, rotation = Point(x, anchor.y), 90
    else:
        y = anchor.y - LABEL_GAP if wire.label_side > 0 else anchor.y + LABEL_GAP + h
        position, rotation = Point(anchor.x, y), 0
    return Text(
        id=f"{wire.id}:label",
        layer=wire.layer,
        color=wire.color,
        position=position,
        text=wire.label,
        height=h,
        rotation=rotation,
        halign=align,
    )


def move_segment(wire: Wire, index: int, p: Point) -> Wire:
    """Shift segment ``index`` across its direction so it passes through ``p``.

    The neighbours stretch, and the wire's ends stay where they are (connected): an
    end segment gets a short perpendicular piece at the fixed end.
    """
    pts = list(wire.points)
    a, b = pts[index], pts[index + 1]
    if abs(a.y - b.y) <= EPS:  # horizontal: moves up or down
        dx, dy = 0.0, p.y - a.y
    else:  # vertical: moves left or right
        dx, dy = p.x - a.x, 0.0
    if abs(dx) <= EPS and abs(dy) <= EPS:
        return wire
    moved = [a.translated(dx, dy), b.translated(dx, dy)]

    def straight(p: Point, q: Point, r: Point) -> bool:
        return (abs(p.x - q.x) <= EPS and abs(q.x - r.x) <= EPS) or (
            abs(p.y - q.y) <= EPS and abs(q.y - r.y) <= EPS
        )

    # Keep the old corner (a short cross piece) at a fixed end and where the neighbour
    # runs straight on, e.g. after "Add point" split a straight run.
    keep_a = index == 0 or straight(pts[index - 1], a, b)
    keep_b = index + 1 == len(pts) - 1 or straight(a, b, pts[index + 2])
    head = pts[:index] + ([a] if keep_a else [])
    tail = ([b] if keep_b else []) + pts[index + 2 :]
    new_pts = head + moved + tail
    # Tidy up only around the moved piece; other points (added on purpose) stay.
    touched = {id(q) for q in moved} | {id(a), id(b)}
    out: list[Point] = []
    for q in new_pts:
        if out and same(out[-1], q):
            continue
        out.append(q)
    i = 1
    while i < len(out) - 1:
        if (id(out[i]) in touched) and straight(out[i - 1], out[i], out[i + 1]):
            del out[i]
            i = max(1, i - 1)
        else:
            i += 1
    return replace(wire, points=tuple(out))


def segment_grips(wire: Wire, avoid: Point | None = None) -> list[tuple[int, Point]]:
    """(segment index, grip point) for every segment: its middle, or a quarter along it
    when the middle is taken by the label grip ``avoid``."""
    result = []
    for i, (a, b) in enumerate(segments(wire.points)):
        if distance(a, b) <= EPS:
            continue
        mid = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
        if avoid is not None and distance(mid, avoid) < min(5.0, distance(a, b) / 4):
            mid = Point(a.x + (b.x - a.x) / 4, a.y + (b.y - a.y) / 4)
        result.append((i, mid))
    return result


def drag_end(wire: Wire, end: int, p: Point) -> Wire:
    """Move one end (0 = start, -1 = end) keeping all segments orthogonal."""
    pts = list(wire.points)
    if end == 0:
        pts.reverse()
    old = pts[-1]
    if len(pts) == 2:
        start = pts[0]
        horizontal = abs(start.y - old.y) <= EPS and abs(start.x - old.x) > EPS
        pts = [start, *elbow(start, p, horizontal_first=horizontal)]
    else:
        a = pts[-2]
        if abs(a.y - old.y) <= EPS:
            pts[-2] = Point(a.x, p.y)
        elif abs(a.x - old.x) <= EPS:
            pts[-2] = Point(p.x, a.y)
        pts[-1] = p
    if end == 0:
        pts.reverse()
    return replace(wire, points=simplify(pts))


def connection_positions(
    entities: Iterable[Entity], blocks: Mapping[str, BlockDefinition]
) -> dict[tuple[str, str], Point]:
    """World positions of connection points keyed by (entity id, connection name)."""
    result: dict[tuple[str, str], Point] = {}
    for e in entities:
        if isinstance(e, BlockReference):
            for c in world_connections(e, blocks):
                result[(e.id, c.name + "#" + c.id)] = c.position
        elif isinstance(e, ConnectionPoint):
            result[(e.id, "")] = e.position
    return result


def follow_connections(
    all_entities: Iterable[Entity],
    old: Iterable[Entity],
    new: Iterable[Entity],
    blocks: Mapping[str, BlockDefinition],
) -> list[Wire]:
    """Wires (not themselves changed) whose ends sat on moved connection points, updated."""
    old_list, new_list = list(old), list(new)
    changed_ids = {e.id for e in new_list}
    before = connection_positions(old_list, blocks)
    after = connection_positions(new_list, blocks)
    moves = [(before[k], after[k]) for k in before if k in after and not same(before[k], after[k])]
    if not moves:
        return []
    result: list[Wire] = []
    for e in all_entities:
        if not isinstance(e, Wire) or e.id in changed_ids or len(e.points) < 2:
            continue
        targets: dict[int, Point] = {}
        for index in (0, -1):
            for src, dst in moves:
                if same(e.points[index], src):
                    targets[index] = dst
                    break
        if not targets:
            continue
        if len(targets) == 2:
            d0 = (targets[0].x - e.points[0].x, targets[0].y - e.points[0].y)
            d1 = (targets[-1].x - e.points[-1].x, targets[-1].y - e.points[-1].y)
            if math.isclose(d0[0], d1[0], abs_tol=EPS) and math.isclose(d0[1], d1[1], abs_tol=EPS):
                result.append(e.translated(*d0))
                continue
        wire = e
        for index, dst in targets.items():
            wire = drag_end(wire, index, dst)
        result.append(wire)
    return result


def _segments_of(e: Entity) -> list[tuple[Point, Point]]:
    if isinstance(e, Wire):
        return segments(e.points)
    if isinstance(e, Busbar):
        return [(e.p1, e.p2)]
    return []


def _ends_of(e: Entity) -> tuple[Point, Point]:
    return (e.points[0], e.points[-1]) if isinstance(e, Wire) else (e.p1, e.p2)


def _translation(old: Entity, new: Entity) -> tuple[float, float] | None:
    """The common offset if ``new`` is ``old`` just moved, else None."""
    if isinstance(old, Wire) and isinstance(new, Wire):
        if len(old.points) != len(new.points):
            return None
        pairs = list(zip(old.points, new.points, strict=True))
    elif isinstance(old, Busbar) and isinstance(new, Busbar):
        pairs = [(old.p1, new.p1), (old.p2, new.p2)]
    else:
        return None
    dx, dy = pairs[0][1].x - pairs[0][0].x, pairs[0][1].y - pairs[0][0].y
    if all(
        math.isclose(b.x - a.x, dx, abs_tol=EPS) and math.isclose(b.y - a.y, dy, abs_tol=EPS)
        for a, b in pairs
    ):
        return dx, dy
    return None


def _moved_point(old: Entity, new: Entity, p: Point) -> Point | None:
    """Where the point ``p`` of ``old`` is on ``new``; None if it did not move or is gone."""
    offset = _translation(old, new)
    if offset is not None:
        return p.translated(*offset) if offset != (0.0, 0.0) else None
    for o_end, n_end in zip(_ends_of(old), _ends_of(new), strict=True):
        if same(p, o_end):
            return None if same(o_end, n_end) else n_end
    seg = next(((a, b) for a, b in _segments_of(old) if on_segment(p, a, b)), None)
    if seg is None:
        return None
    a, b = seg
    horizontal = abs(a.y - b.y) <= EPS
    candidates = []
    for c, d in _segments_of(new):
        if (
            horizontal
            and abs(c.y - d.y) <= EPS
            and min(c.x, d.x) - EPS <= p.x <= max(c.x, d.x) + EPS
        ):
            candidates.append(Point(p.x, c.y))
        elif (
            not horizontal
            and abs(c.x - d.x) <= EPS
            and min(c.y, d.y) - EPS <= p.y <= max(c.y, d.y) + EPS
        ):
            candidates.append(Point(c.x, p.y))
    if not candidates or any(same(q, p) for q in candidates):
        return None
    return min(candidates, key=lambda q: distance(q, p))


def follow_wires(
    all_entities: Iterable[Entity], old: Iterable[Entity], new: Iterable[Entity]
) -> list[Entity]:
    """Wires attached with an end to a changed wire or bus bar (T branch or end to end),
    moved along with it, plus the junction marks there. Points separated with a
    junction mark (``connected`` False) stay where they are."""
    new_by_id = {e.id: e for e in new}
    changed = [
        (o, new_by_id[o.id])
        for o in old
        if isinstance(o, Wire | Busbar) and o.id in new_by_id and o != new_by_id[o.id]
    ]
    if not changed:
        return []
    entities = list(all_entities)
    separated = [e.position for e in entities if isinstance(e, JunctionMark) and not e.connected]

    def target(p: Point) -> Point | None:
        if any(same(p, q) for q in separated):
            return None
        for o, n in changed:
            if any(on_segment(p, a, b) for a, b in _segments_of(o)):
                return _moved_point(o, n, p)
        return None

    result: list[Entity] = []
    moved_points: list[tuple[Point, Point]] = []
    for e in entities:
        if not isinstance(e, Wire) or e.id in new_by_id or len(e.points) < 2:
            continue
        targets = {i: t for i in (0, -1) if (t := target(e.points[i])) is not None}
        if not targets:
            continue
        moved_points += [(e.points[i], t) for i, t in targets.items()]
        if len(targets) == 2:
            d0 = (targets[0].x - e.points[0].x, targets[0].y - e.points[0].y)
            d1 = (targets[-1].x - e.points[-1].x, targets[-1].y - e.points[-1].y)
            if math.isclose(d0[0], d1[0], abs_tol=EPS) and math.isclose(d0[1], d1[1], abs_tol=EPS):
                result.append(e.translated(*d0))
                continue
        wire = e
        for index, dst in targets.items():
            wire = drag_end(wire, index, dst)
        result.append(wire)
    for e in entities:
        if isinstance(e, JunctionMark) and e.connected and e.id not in new_by_id:
            for src, dst in moved_points:
                if same(e.position, src):
                    result.append(replace(e, position=dst))
                    break
    return result


def insert_point(points: tuple[Point, ...], p: Point) -> tuple[Point, ...] | None:
    """``points`` with ``p`` added inside the segment it lies on, or None."""
    for i, (a, b) in enumerate(segments(points)):
        if _on_segment_interior(p, a, b):
            return (*points[: i + 1], p, *points[i + 1 :])
    return None


def _touches(p: Point, e: Entity) -> bool:
    return any(on_segment(p, a, b) for a, b in _segments_of(e))


def new_contacts(
    entities: Iterable[Entity], changed: Iterable[Entity], follower_ids: set[str]
) -> list[Point]:
    """Points where a wire pulled along (``follower_ids``) now touches another wire or
    bus bar with an end, or is touched by another wire's end, although these two did
    not touch there before. Such chance contacts must not become connections."""
    original = {e.id: e for e in entities}
    final = dict(original)
    final.update({e.id: e for e in changed})
    bodies = [e for e in final.values() if isinstance(e, Wire | Busbar)]
    marked = [e.position for e in final.values() if isinstance(e, JunctionMark)]
    found: list[Point] = []

    def add(p: Point) -> None:
        if not any(same(p, q) for q in marked) and not any(same(p, q) for q in found):
            found.append(p)

    def was_touching(wire_id: str, index: int, body_id: str) -> bool:
        wire, body = original.get(wire_id), original.get(body_id)
        if not isinstance(wire, Wire) or body is None or len(wire.points) < 2:
            return False
        return _touches(wire.points[index], body)

    for fid in follower_ids:
        f = final.get(fid)
        if not isinstance(f, Wire) or len(f.points) < 2:
            continue
        for index in (0, -1):
            p = f.points[index]
            for body in bodies:
                if body.id != fid and _touches(p, body) and not was_touching(fid, index, body.id):
                    add(p)
        for other in bodies:
            if other.id == fid or not isinstance(other, Wire) or len(other.points) < 2:
                continue
            for index in (0, -1):
                q = other.points[index]
                if _touches(q, f) and not was_touching(other.id, index, fid):
                    add(q)
    return found


def _crossing(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    """Crossing point of a horizontal and a vertical segment (either order), or None."""
    if abs(a.y - b.y) <= EPS and abs(c.x - d.x) <= EPS:
        p = Point(c.x, a.y)
    elif abs(a.x - b.x) <= EPS and abs(c.y - d.y) <= EPS:
        p = Point(a.x, c.y)
    else:
        return None
    return p if on_segment(p, a, b) and on_segment(p, c, d) else None


def follow_marks(all_entities: Iterable[Entity], changed: Iterable[Entity]) -> list[JunctionMark]:
    """Connection marks set on a crossing of two wires (or a wire and a bus bar) move to
    where these two still cross after some of them changed, so the connection holds
    like a docked one. Marks that already moved, or whose crossing is gone, stay."""
    entities = list(all_entities)
    changed_list = list(changed)
    new_by_id = {e.id: e for e in changed_list}
    if not any(isinstance(e, Wire | Busbar) for e in changed_list):
        return []
    original = {e.id: e for e in entities}
    final = dict(original)
    final.update(new_by_id)
    result: list[JunctionMark] = []
    for mark in entities:
        if not isinstance(mark, JunctionMark) or not mark.connected or mark.id in new_by_id:
            continue
        p = mark.position
        # The bodies that meet at the mark, as they were.
        bodies = [
            e.id
            for e in entities
            if isinstance(e, Wire | Busbar) and any(on_segment(p, a, b) for a, b in _segments_of(e))
        ]
        if len(bodies) < 2 or not any(i in new_by_id for i in bodies):
            continue
        candidates: list[Point] = []
        for i, first in enumerate(bodies):
            for second in bodies[i + 1 :]:
                for a, b in _segments_of(final[first]):
                    for c, d in _segments_of(final[second]):
                        q = _crossing(a, b, c, d)
                        if q is not None:
                            candidates.append(q)
        if not candidates or any(same(q, p) for q in candidates):
            continue
        target = min(candidates, key=lambda q: distance(q, p))
        result.append(replace(mark, position=target))
    return result
