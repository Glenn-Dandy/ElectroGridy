"""Plain lines turned into wires (imported plans consist of lines only).

Horizontal and vertical pieces become wires; pieces meeting end to end at a point
nothing else touches are joined into one wire. A short diagonal from a branch end
to a crossing conductor is the T branch of an imported plan: the branch is
lengthened to the conductor, so it really connects, and the diagonal goes (the
project draws it again in the T-branch style). A diagonal pointing left or up keeps
that side with a junction mark. Other slanted pieces stay lines.
"""

from dataclasses import dataclass, field

from electrogridy.model.entities import Busbar, Entity, JunctionMark, Line, Polyline, Wire, new_id
from electrogridy.model.geometry import Point, distance
from electrogridy.model.wires import EPS, same, segments, simplify

TEE_DIAGONAL_MAX = 5.0  # mm: longer diagonals are drawn lines, not T branches
TEE_SLOPE = (0.5, 2.0)  # |dy/dx| of a T diagonal: about 45°


def convertible(e: Entity) -> bool:
    return isinstance(e, Line) or isinstance(e, Polyline) and not e.closed


@dataclass
class Conversion:
    added: list[Entity] = field(default_factory=list)  # wires, marks, remaining lines
    removed: list[str] = field(default_factory=list)  # ids of the converted lines
    wires: int = 0
    tees: int = 0


@dataclass
class _Piece:
    a: Point
    b: Point
    source: Entity


def _axis_of(a: Point, b: Point) -> str | None:
    if abs(a.y - b.y) <= EPS and abs(a.x - b.x) > EPS:
        return "h"
    if abs(a.x - b.x) <= EPS and abs(a.y - b.y) > EPS:
        return "v"
    return None


def _on(p: Point, a: Point, b: Point, tol: float = EPS) -> bool:
    """``p`` on the axis-parallel segment a-b, ends included."""
    if abs(a.x - b.x) <= EPS:
        return abs(p.x - a.x) <= tol and min(a.y, b.y) - tol <= p.y <= max(a.y, b.y) + tol
    return abs(p.y - a.y) <= tol and min(a.x, b.x) - tol <= p.x <= max(a.x, b.x) + tol


def _inside(p: Point, a: Point, b: Point) -> bool:
    return _on(p, a, b) and not same(p, a) and not same(p, b)


def lines_to_wires(lines: list[Entity], others: list[Entity]) -> Conversion:
    """Convert ``lines`` (Line and open Polyline); ``others`` are the remaining
    entities of the area, whose wires and bus bars may carry T branches and keep
    pieces from being joined at points they touch."""
    straight: list[_Piece] = []
    slanted: list[_Piece] = []
    result = Conversion()
    for e in lines:
        if not convertible(e):
            continue
        points = (e.p1, e.p2) if isinstance(e, Line) else e.points
        for a, b in segments(points):
            if distance(a, b) <= EPS:
                continue
            (straight if _axis_of(a, b) else slanted).append(_Piece(a, b, e))
        result.removed.append(e.id)
    if not straight:
        return Conversion()

    conductors = [(p.a, p.b) for p in straight]
    for o in others:
        if isinstance(o, Wire):
            conductors += [(a, b) for a, b in segments(o.points) if _axis_of(a, b)]
        elif isinstance(o, Busbar) and _axis_of(o.p1, o.p2):
            conductors.append((o.p1, o.p2))

    kept: list[_Piece] = []
    for d in slanted:
        tee = _tee(d, straight, conductors)
        if tee is None:
            kept.append(d)
            continue
        piece, at_a, junction, side = tee
        if at_a:
            piece.a = junction
        else:
            piece.b = junction
        result.tees += 1
        if side < 0:
            result.added.append(
                JunctionMark(id=new_id(), layer=piece.source.layer, position=junction, side=-1)
            )

    for chain in _chains(straight, others):
        first = chain[0].source
        result.added.append(
            Wire(
                id=new_id(),
                layer=first.layer,
                color=first.color,
                lineweight=first.lineweight,
                linetype=first.linetype,
                points=simplify(_walk(chain)),
            )
        )
        result.wires += 1
    for d in kept:
        result.added.append(_line(d))
    return result


def _line(d: _Piece) -> Line:
    s = d.source
    return Line(
        id=new_id(),
        layer=s.layer,
        color=s.color,
        lineweight=s.lineweight,
        linetype=s.linetype,
        p1=d.a,
        p2=d.b,
    )


def _tee(d: _Piece, straight: list[_Piece], conductors) -> tuple | None:
    """The branch piece a T diagonal ``d`` hangs on, whether its end ``a`` is meant,
    the junction on the crossing conductor and the side of the diagonal (+1 right or
    down along the conductor, -1 left or up)."""
    dx, dy = abs(d.b.x - d.a.x), abs(d.b.y - d.a.y)
    if distance(d.a, d.b) > TEE_DIAGONAL_MAX or dx <= EPS:
        return None
    if not TEE_SLOPE[0] <= dy / dx <= TEE_SLOPE[1]:
        return None
    for end, tip in ((d.a, d.b), (d.b, d.a)):
        for piece in straight:
            for at_a, here, other in ((True, piece.a, piece.b), (False, piece.b, piece.a)):
                if not same(here, end):
                    continue
                vertical = _axis_of(here, other) == "v"
                # The branch runs on beyond its end up to the conductor through ``tip``.
                junction = Point(here.x, tip.y) if vertical else Point(tip.x, here.y)
                away = (
                    (junction.y - here.y) * (here.y - other.y)
                    if vertical
                    else (junction.x - here.x) * (here.x - other.x)
                )
                if away <= 0:
                    continue  # the conductor would lie on the branch's own side
                for a, b in conductors:
                    if (a, b) == (piece.a, piece.b) or _axis_of(a, b) == _axis_of(here, other):
                        continue
                    if _on(tip, a, b, 0.05) and _on(junction, a, b, 0.05):
                        along = tip.x - junction.x if vertical else tip.y - junction.y
                        return piece, at_a, junction, 1 if along > 0 else -1
    return None


def _chains(pieces: list[_Piece], others: list[Entity]) -> list[list[_Piece]]:
    """Pieces joined end to end where exactly two of them end and nothing else is."""

    def key(p: Point) -> tuple[float, float]:
        return (round(p.x, 6), round(p.y, 6))

    ends: dict[tuple[float, float], list[int]] = {}
    for i, piece in enumerate(pieces):
        for p in (piece.a, piece.b):
            ends.setdefault(key(p), []).append(i)
    touched: set[tuple[float, float]] = set()
    for o in others:
        runs = (
            segments(o.points)
            if isinstance(o, Wire)
            else [(o.p1, o.p2)]
            if isinstance(o, Busbar)
            else []
        )
        for k in ends:
            p = Point(*k)
            if any(_on(p, a, b) for a, b in runs if _axis_of(a, b)):
                touched.add(k)
    for k in ends:
        p = Point(*k)
        if any(_inside(p, q.a, q.b) for q in pieces):
            touched.add(k)

    def joinable(k) -> bool:
        return len(ends[k]) == 2 and k not in touched

    used: set[int] = set()
    chains: list[list[_Piece]] = []
    # Start at pieces with an end that is not joined, then the closed loops left.
    order = sorted(
        range(len(pieces)),
        key=lambda i: joinable(key(pieces[i].a)) and joinable(key(pieces[i].b)),
    )
    for start in order:
        if start in used:
            continue
        used.add(start)
        chain = [pieces[start]]
        # Grow at both ends.
        for forward in (True, False):
            while True:
                free = _free_end(chain, forward)
                k = key(free)
                if not joinable(k):
                    break
                nxt = next((i for i in ends[k] if i not in used), None)
                if nxt is None:
                    break
                used.add(nxt)
                if forward:
                    chain.append(pieces[nxt])
                else:
                    chain.insert(0, pieces[nxt])
        chains.append(chain)
    return chains


def _free_end(chain: list[_Piece], forward: bool) -> Point:
    """The open end of the chain at its last (``forward``) or first piece."""
    if len(chain) == 1:
        return chain[0].b if forward else chain[0].a
    if forward:
        last, before = chain[-1], chain[-2]
        return last.a if not (same(last.a, before.a) or same(last.a, before.b)) else last.b
    first, after = chain[0], chain[1]
    return first.a if not (same(first.a, after.a) or same(first.a, after.b)) else first.b


def _walk(chain: list[_Piece]) -> list[Point]:
    if len(chain) == 1:
        return [chain[0].a, chain[0].b]
    start = _free_end(chain, False)
    points = [start]
    for piece in chain:
        points.append(piece.b if same(piece.a, points[-1]) else piece.a)
    return points
