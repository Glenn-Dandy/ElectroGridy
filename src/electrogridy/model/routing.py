"""Wiring helpers for circuit diagrams. Pure Python.

- Splitting a wire at a point, and opening a wire where a symbol is placed into it.
- Routing wires automatically from one connection point to another; a click on one pole
  of a multi-pole device wires all its poles to the poles of the other device.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from electrogridy.model.blocks import BlockDefinition, world_connections
from electrogridy.model.entities import (
    BlockReference,
    ConnectionPoint,
    Entity,
    InterruptionPoint,
    Wire,
    new_id,
)
from electrogridy.model.geometry import Point
from electrogridy.model.wires import EPS, path_length, same, segments, simplify

POLE_SPACING = 5.0  # mm between L1, L2, L3, N, PE: the same for every symbol and rail
STUB = 5.0  # mm a routed wire runs straight out of a connection point at least
GRID = 2.5  # routed corners lie on this grid


# -- splitting and opening wires ----------------------------------------------------


def _position(points: tuple[Point, ...], p: Point) -> tuple[int, float] | None:
    """Segment index and distance from its start for a point on the wire."""
    for i, (a, b) in enumerate(segments(points)):
        if abs(a.x - b.x) <= EPS and abs(p.x - a.x) <= EPS:
            lo, hi = sorted((a.y, b.y))
            if lo - EPS <= p.y <= hi + EPS:
                return i, abs(p.y - a.y)
        elif abs(a.y - b.y) <= EPS and abs(p.y - a.y) <= EPS:
            lo, hi = sorted((a.x, b.x))
            if lo - EPS <= p.x <= hi + EPS:
                return i, abs(p.x - a.x)
    return None


def _pieces(wire: Wire, parts: list[tuple[Point, ...]]) -> list[Wire]:
    """Wires for the given point runs; the label stays on the longest piece only."""
    runs = [simplify(run) for run in parts]
    runs = [run for run in runs if len(run) >= 2]
    if not runs:
        return []
    longest = max(range(len(runs)), key=lambda i: path_length(runs[i]))
    return [
        replace(
            wire,
            id=wire.id if i == 0 else new_id(),
            points=run,
            label=wire.label if i == longest else "",
        )
        for i, run in enumerate(runs)
    ]


def split_wire(wire: Wire, p: Point) -> list[Wire] | None:
    """The wire cut in two at ``p`` (not at its ends); None if ``p`` is not inside it."""
    found = _position(wire.points, p)
    if found is None or same(p, wire.points[0]) or same(p, wire.points[-1]):
        return None
    i, _ = found
    first = (*wire.points[: i + 1], p)
    second = (p, *wire.points[i + 1 :])
    return _pieces(wire, [first, second])


def cut_wire(wire: Wire, p: Point, q: Point) -> list[Wire] | None:
    """The wire without its part between ``p`` and ``q`` (both on the same straight
    segment); None if they are not."""
    fp, fq = _position(wire.points, p), _position(wire.points, q)
    if fp is None or fq is None or fp[0] != fq[0]:
        return None
    i = fp[0]
    if fp[1] > fq[1]:
        p, q = q, p
    first = (*wire.points[: i + 1], p)
    second = (q, *wire.points[i + 1 :])
    return _pieces(wire, [first, second])


def _unit(direction: float) -> tuple[float, float]:
    """Direction in degrees (0 right, 90 up on the screen) as a drawing vector."""
    a = math.radians(direction)
    ux, uy = math.cos(a), -math.sin(a)
    return (round(ux), round(uy)) if abs(ux) < EPS or abs(uy) < EPS else (ux, uy)


def open_wires(
    entities: Iterable[Entity], pins: list[ConnectionPoint]
) -> tuple[list[str], list[Wire]]:
    """Where a symbol is placed into wires: (ids of wires to remove, wires to add).

    A wire is opened between two connection points of the symbol that lie on the same
    straight piece of it and point away from each other along it (the two ends of one
    pole), so each pole sits in its conductor. Wires the symbol only touches (a rail
    under all its top terminals) stay as they are.
    """
    removed: list[str] = []
    added: list[Wire] = []
    for e in entities:
        if not isinstance(e, Wire):
            continue
        pending = [e]
        result: list[Wire] = []
        changed = False
        while pending:
            wire = pending.pop()
            cut = _first_cut(wire, pins)
            if cut is None:
                result.append(wire)
                continue
            changed = True
            pending.extend(cut_wire(wire, *cut) or [])
        if changed:
            removed.append(e.id)
            added.extend(result)
    return removed, added


def _first_cut(wire: Wire, pins: list[ConnectionPoint]) -> tuple[Point, Point] | None:
    for a, b in segments(wire.points):
        vertical = abs(a.x - b.x) <= EPS
        axis = (0, 1) if vertical else (1, 0)
        sign = 1 if (b.y - a.y if vertical else b.x - a.x) > 0 else -1
        on = []
        for pin in pins:
            found = _position((a, b), pin.position)
            ux, uy = _unit(pin.direction)
            along = ux * axis[0] + uy * axis[1]
            if found is not None and abs(abs(along) - 1) <= EPS:
                on.append((found[1], along * sign, pin.position))
        on.sort(key=lambda t: t[0])
        for (d1, dir1, p1), (d2, dir2, p2) in zip(on, on[1:], strict=False):
            # First points back towards the segment start, second on towards its end.
            if dir1 < 0 < dir2 and d2 - d1 > EPS:
                return p1, p2
    return None


# -- routing ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pin:
    ref_id: str
    name: str
    position: Point
    direction: float


def pins_of(entities: Iterable[Entity], blocks: Mapping[str, BlockDefinition]) -> list[Pin]:
    out = []
    for e in entities:
        if isinstance(e, BlockReference):
            for c in world_connections(e, blocks):
                out.append(Pin(e.id, c.name, c.position, c.direction % 360))
    return out


def pin_at(pins: Iterable[Pin], p: Point) -> Pin | None:
    return next((pin for pin in pins if same(pin.position, p)), None)


def pole_group(pins: Iterable[Pin], pin: Pin) -> list[Pin]:
    """Connection points of the same symbol pointing the same way and lying in one row
    across that direction, in order along the row (L1, L2, L3 …)."""
    ux, uy = _unit(pin.direction)
    row = [
        q
        for q in pins
        if q.ref_id == pin.ref_id
        and abs(q.direction - pin.direction) <= EPS
        and abs((q.position.x - pin.position.x) * ux + (q.position.y - pin.position.y) * uy) <= EPS
    ]
    # Along the row: x for vertical pins, y for horizontal ones.
    row.sort(key=lambda q: (q.position.x, q.position.y) if abs(ux) < 0.5 else q.position.y)
    return row


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def route(a: Pin, b: Pin, lane: float | None = None) -> tuple[Point, ...]:
    """Orthogonal path from ``a`` to ``b`` leaving and entering along their directions.

    ``lane`` is where the cross run lies (y for vertical pins, x for horizontal ones);
    None takes the middle.
    """
    pa, pb = a.position, b.position
    ax, ay = _unit(a.direction)
    bx, by = _unit(b.direction)
    a_vertical, b_vertical = abs(ax) < 0.5, abs(bx) < 0.5
    if a_vertical and b_vertical:
        if abs(pa.x - pb.x) <= EPS and ay * (pb.y - pa.y) > 0 and by * (pa.y - pb.y) > 0:
            return (pa, pb)  # straight below each other, facing
        facing = ay * (pb.y - pa.y) > 0 and by * (pa.y - pb.y) > 0
        if facing:
            y = _snap((pa.y + pb.y) / 2) if lane is None else lane
        elif ay == by:  # both point the same way: around the far one
            far = max(pa.y, pb.y) if ay > 0 else min(pa.y, pb.y)
            y = far + ay * STUB if lane is None else lane
        else:  # pointing away from each other: out of both and across in between
            y1, y2 = pa.y + ay * STUB, pb.y + by * STUB
            x = _snap((pa.x + pb.x) / 2) if lane is None else lane
            return simplify([pa, Point(pa.x, y1), Point(x, y1), Point(x, y2), Point(pb.x, y2), pb])
        return simplify([pa, Point(pa.x, y), Point(pb.x, y), pb])
    if not a_vertical and not b_vertical:
        facing = ax * (pb.x - pa.x) > 0 and bx * (pa.x - pb.x) > 0
        if facing:
            x = _snap((pa.x + pb.x) / 2) if lane is None else lane
        elif ax == bx:
            far = max(pa.x, pb.x) if ax > 0 else min(pa.x, pb.x)
            x = far + ax * STUB if lane is None else lane
        else:
            x1, x2 = pa.x + ax * STUB, pb.x + bx * STUB
            y = _snap((pa.y + pb.y) / 2) if lane is None else lane
            return simplify([pa, Point(x1, pa.y), Point(x1, y), Point(x2, y), Point(x2, pb.y), pb])
        return simplify([pa, Point(x, pa.y), Point(x, pb.y), pb])
    # One vertical, one horizontal: a single corner.
    corner = Point(pa.x, pb.y) if a_vertical else Point(pb.x, pa.y)
    return simplify([pa, corner, pb])


def connect(pins: list[Pin], start: Pin, end: Pin) -> list[tuple[Point, ...]]:
    """Paths from ``start`` to ``end`` and, for multi-pole devices, from the following
    poles of the start device to the following poles of the end device. Cross runs are
    staggered by the pole spacing so the wires do not cross each other."""
    if start.ref_id == end.ref_id:
        return [route(start, end)]
    group_a, group_b = pole_group(pins, start), pole_group(pins, end)
    ia, ib = group_a.index(start), group_b.index(end)
    n = min(len(group_a) - ia, len(group_b) - ib)
    pairs = [(group_a[ia + k], group_b[ib + k]) for k in range(n)]
    if n == 1:
        return [route(start, end)]
    ax, ay = _unit(start.direction)
    vertical = abs(ax) < 0.5
    out = ay if vertical else ax  # the way the wires leave the start device
    first = route(*pairs[0])
    if len(first) <= 2:  # straight: all poles straight
        return [route(a, b) for a, b in pairs]
    # Lane of the first pair from its default path, then one pole spacing per pair, so
    # that the pole turning first is the one on the side the wires run to.
    lane0 = first[1].y if vertical else first[1].x
    shift = (
        (pairs[0][1].position.x - pairs[0][0].position.x)
        if vertical
        else (pairs[0][1].position.y - pairs[0][0].position.y)
    )
    middle = (n - 1) / 2
    paths = []
    for k, (a, b) in enumerate(pairs):
        offset = ((middle - k) if shift > 0 else (k - middle)) * out
        paths.append(route(a, b, _snap(lane0 + offset * POLE_SPACING)))
    return paths


# -- rails --------------------------------------------------------------------------

RAIL_PRESETS = ("L1, L2, L3, N, PE", "L1, L2, L3, PE", "L1, N, PE", "L+, L-")


def rail_names(text: str) -> list[str]:
    """ "L1, L2 L3;N" -> ["L1", "L2", "L3", "N"]."""
    return text.replace(";", ",").replace(",", " ").split()


def rails(names: list[str], x1: float, x2: float, y: float, layer: str, ends: bool) -> list[Entity]:
    """Horizontal conductors (main circuit) from ``x1`` to ``x2``, the first at ``y``,
    one pole spacing apart; with ``ends`` an interruption point at both ends so each
    rail continues on the neighbouring pages."""
    out: list[Entity] = []
    left, right = min(x1, x2), max(x1, x2)
    for i, name in enumerate(names):
        yi = y + i * POLE_SPACING
        out.append(Wire(id=new_id(), layer=layer, points=(Point(left, yi), Point(right, yi))))
        if ends:
            for x, direction in ((left, 180.0), (right, 0.0)):
                out.append(
                    InterruptionPoint(
                        id=new_id(),
                        layer=layer,
                        position=Point(x, yi),
                        name=name,
                        direction=direction,
                    )
                )
    return out
