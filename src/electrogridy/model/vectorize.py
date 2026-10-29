"""Lines from a black-and-white picture of a circuit diagram (an attempt). Pure Python.

The picture comes as one byte per pixel, 1 for ink, row after row. Circuit diagrams
are mostly horizontal and vertical strokes: runs of ink along the rows (and along the
columns) of at least ``min_length`` pixels that continue on the neighbouring rows
form one stroke; a stroke thicker than ``max_thickness`` and not much longer than
thick is a filled area and left out. Pieces of one line (overlapping, broken by small
gaps, or evenly spaced dashes) become one line along their middle; ends close to a
perpendicular line are drawn onto it, so that wires meet. What is left of the ink
falls into connected pieces: a thin, long piece is a sloped line (a switch blade), a
thin ring a circle. Small groups of lines touching nothing else are bits of
lettering and left out, as is everything else (filled symbols); the picture can stay
underneath for reference.
"""

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Stroke:
    """A line in pixel coordinates (x right, y down)."""

    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float
    dashed: bool = False


@dataclass(frozen=True)
class Ring:
    cx: float
    cy: float
    r: float


def _runs(row: bytes, min_length: int) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(rb"\x01{%d,}" % min_length, row)]


def _strokes(lines: list[bytes], min_length: int, max_thickness: int) -> list[tuple]:
    """Runs along each line of pixels merged over neighbouring lines: (first line,
    last line, start, end) in the coordinates of ``lines``."""
    done: list[tuple] = []
    active: list[list] = []  # [first, last, starts, ends]
    for y, row in enumerate(lines):
        runs = _runs(row, min_length)
        continued = []
        used = set()
        for stroke in active:
            s0 = sorted(stroke[2])[len(stroke[2]) // 2]
            e0 = sorted(stroke[3])[len(stroke[3]) // 2]
            tol = max(2, (e0 - s0) // 20)
            match = None
            for i, (s, e) in enumerate(runs):
                if i not in used and abs(s - s0) <= tol and abs(e - e0) <= tol:
                    match = i
                    break
            if match is None:
                done.append(stroke)
                continue
            used.add(match)
            stroke[1] = y
            stroke[2].append(runs[match][0])
            stroke[3].append(runs[match][1])
            continued.append(stroke)
        for i, (s, e) in enumerate(runs):
            if i not in used:
                continued.append([y, y, [s], [e]])
        active = continued
    done += active
    out = []
    for first, last, starts, ends in done:
        thickness = last - first + 1
        starts, ends = sorted(starts), sorted(ends)
        start, end = starts[len(starts) // 2], ends[len(ends) // 2] - 1
        # Thicker than a line and not much longer than thick: a filled area.
        if thickness > max_thickness and end - start + 1 < 4 * thickness:
            continue
        out.append((first, last, start, end))
    return out


def _dashed(spans: list[tuple[float, float]], gaps: list[float]) -> bool:
    """Evenly spaced dashes: at least four, gaps and inner dashes of about one size."""
    if len(gaps) < 3 or min(gaps) < 2 or max(gaps) > 2 * min(gaps) + 2:
        return False
    inner = [b - a for a, b in spans[1:-1]]  # the outer ones may be cut by the region
    return max(inner) <= 2 * min(inner) + 2


def _join(strokes: list[Stroke], horizontal: bool, gap: float) -> list[Stroke]:
    """Pieces of one line become one: overlapping ones (the edges of a blurred line),
    ones interrupted by small gaps (a broken scan) and evenly spaced dashes."""

    def pos(s: Stroke) -> float:
        return s.y1 if horizontal else s.x1

    def span(s: Stroke) -> tuple[float, float]:
        a, b = (s.x1, s.x2) if horizontal else (s.y1, s.y2)
        return min(a, b), max(a, b)

    def made(pieces: list[Stroke], dashed: bool) -> Stroke:
        lengths = [max(1.0, span(p)[1] - span(p)[0]) for p in pieces]
        middle = sum(pos(p) * n for p, n in zip(pieces, lengths, strict=True)) / sum(lengths)
        lo = min(span(p)[0] for p in pieces)
        hi = max(span(p)[1] for p in pieces)
        thickness = max(pos(p) + p.thickness / 2 for p in pieces) - min(
            pos(p) - p.thickness / 2 for p in pieces
        )
        if horizontal:
            return Stroke(lo, middle, hi, middle, thickness, dashed)
        return Stroke(middle, lo, middle, hi, thickness, dashed)

    rows: list[list[Stroke]] = []
    for s in sorted(strokes, key=pos):
        if rows and pos(s) - pos(rows[-1][0]) <= 1.5:
            rows[-1].append(s)
        else:
            rows.append([s])
    out: list[Stroke] = []
    for row in rows:
        # Chains with gaps up to dash spacing; kept whole only if they are dashes.
        chains: list[tuple[list[Stroke], list[float]]] = []
        end = None
        for s in sorted(row, key=lambda s: span(s)[0]):
            a, b = span(s)
            if end is not None and a - end <= 3 * gap:
                chains[-1][0].append(s)
                chains[-1][1].append(a - end)
                end = max(end, b)
            else:
                chains.append(([s], []))
                end = b
        for pieces, gaps in chains:
            if _dashed([span(p) for p in pieces], gaps):
                out.append(made(pieces, True))
                continue
            part = [pieces[0]]
            for p, g in zip(pieces[1:], gaps, strict=True):
                if g > gap:
                    out.append(made(part, False))
                    part = []
                part.append(p)
            out.append(made(part, False))
    return out


def _near(s: Stroke | Ring, t: Stroke | Ring, reach: float) -> bool:
    """Whether two shapes touch, give or take ``reach``."""

    def box(u):
        if isinstance(u, Ring):
            return u.cx - u.r, u.cy - u.r, u.cx + u.r, u.cy + u.r
        return min(u.x1, u.x2), min(u.y1, u.y2), max(u.x1, u.x2), max(u.y1, u.y2)

    a, b = box(s), box(t)
    if a[0] > b[2] + reach or b[0] > a[2] + reach or a[1] > b[3] + reach or b[1] > a[3] + reach:
        return False
    if isinstance(s, Ring) or isinstance(t, Ring):
        return True

    def distance(px, py, u: Stroke) -> float:
        dx, dy = u.x2 - u.x1, u.y2 - u.y1
        n = dx * dx + dy * dy
        f = 0.0 if n == 0 else max(0.0, min(1.0, ((px - u.x1) * dx + (py - u.y1) * dy) / n))
        return math.hypot(px - u.x1 - f * dx, py - u.y1 - f * dy)

    ends = [(s.x1, s.y1, t), (s.x2, s.y2, t), (t.x1, t.y1, s), (t.x2, t.y2, s)]
    return min(distance(x, y, u) for x, y, u in ends) <= reach


def _without_specks(shapes: list, reach: float, size: float) -> list:
    """Without groups of touching lines smaller than ``size`` that touch nothing else:
    bits of lettering."""
    parent = list(range(len(shapes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, s in enumerate(shapes):
        for j in range(i + 1, len(shapes)):
            if _near(s, shapes[j], reach):
                parent[root(i)] = root(j)
    boxes: dict[int, list[float]] = {}
    for i, s in enumerate(shapes):
        if isinstance(s, Ring):
            b = [s.cx - s.r, s.cy - s.r, s.cx + s.r, s.cy + s.r]
        else:
            b = [min(s.x1, s.x2), min(s.y1, s.y2), max(s.x1, s.x2), max(s.y1, s.y2)]
        r = boxes.setdefault(root(i), b)
        r[:] = [min(r[0], b[0]), min(r[1], b[1]), max(r[2], b[2]), max(r[3], b[3])]
    big = {k for k, b in boxes.items() if max(b[2] - b[0], b[3] - b[1]) >= size}
    # Rings are checked closely enough when found (a lone one may be a symbol).
    return [s for i, s in enumerate(shapes) if root(i) in big or isinstance(s, Ring)]


def _merge_parallel(strokes: list[Stroke], horizontal: bool, reach: float) -> list[Stroke]:
    """Strokes side by side along most of their length are one line drawn thick (the
    edge of a blurred line can start a stroke of its own)."""

    def pos(s: Stroke) -> float:
        return s.y1 if horizontal else s.x1

    def span(s: Stroke) -> tuple[float, float]:
        a, b = (s.x1, s.x2) if horizontal else (s.y1, s.y2)
        return min(a, b), max(a, b)

    out: list[Stroke] = []
    for s in sorted(strokes, key=pos):
        a, b = span(s)
        for i, t in enumerate(out):
            c, d = span(t)
            overlap = min(b, d) - max(a, c)
            if abs(pos(t) - pos(s)) <= reach and overlap > 0.5 * min(b - a, d - c):
                weight = s.thickness + t.thickness
                middle = (pos(s) * s.thickness + pos(t) * t.thickness) / weight
                lo, hi = min(a, c), max(b, d)
                out[i] = (
                    Stroke(lo, middle, hi, middle, weight)
                    if horizontal
                    else Stroke(middle, lo, middle, hi, weight)
                )
                break
        else:
            out.append(s)
    return out


def _meet(hs: list[Stroke], vs: list[Stroke], reach: float) -> tuple[list, list]:
    """Line ends close to a perpendicular line are drawn onto it."""

    def snap_h(s: Stroke) -> Stroke:
        x1, x2 = s.x1, s.x2
        for v in vs:
            if v.y1 - reach <= s.y1 <= v.y2 + reach:
                if abs(x1 - v.x1) <= reach:
                    x1 = v.x1
                if abs(x2 - v.x1) <= reach:
                    x2 = v.x1
        return Stroke(x1, s.y1, x2, s.y2, s.thickness, s.dashed)

    def snap_v(s: Stroke) -> Stroke:
        y1, y2 = s.y1, s.y2
        for h in hs:
            if h.x1 - reach <= s.x1 <= h.x2 + reach:
                if abs(y1 - h.y1) <= reach:
                    y1 = h.y1
                if abs(y2 - h.y1) <= reach:
                    y2 = h.y1
        return Stroke(s.x1, y1, s.x2, y2, s.thickness, s.dashed)

    return [snap_h(s) for s in hs], [snap_v(s) for s in vs]


def _pieces(ink: set[int], width: int) -> list[list[int]]:
    """Connected pixels (8 neighbours)."""
    out = []
    left = set(ink)
    while left:
        start = left.pop()
        piece = [start]
        stack = [start]
        while stack:
            i = stack.pop()
            x = i % width
            for d in (-width - 1, -width, -width + 1, -1, 1, width - 1, width, width + 1):
                j = i + d
                if j in left and abs((j % width) - x) <= 1:
                    left.discard(j)
                    piece.append(j)
                    stack.append(j)
        out.append(piece)
    return out


def _shape(piece: list[int], width: int, min_length: int, max_thickness: int):
    """A sloped line or a circle, or None."""
    xs = [i % width for i in piece]
    ys = [i // width for i in piece]
    n = len(piece)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs) / n
    syy = sum((y - my) ** 2 for y in ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / n
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(angle), math.sin(angle)
    along = [(x - mx) * ux + (y - my) * uy for x, y in zip(xs, ys, strict=True)]
    across = [-(x - mx) * uy + (y - my) * ux for x, y in zip(xs, ys, strict=True)]
    length = max(along) - min(along)
    thickness = max(across) - min(across) + 1
    if length >= min_length and thickness <= max_thickness:
        a, b = min(along), max(along)
        return Stroke(mx + a * ux, my + a * uy, mx + b * ux, my + b * uy, thickness)
    w = max(xs) - min(xs) + 1
    h = max(ys) - min(ys) + 1
    if w >= 6 and 0.8 <= w / h <= 1.25:
        radii = [math.hypot(x - mx, y - my) for x, y in zip(xs, ys, strict=True)]
        r = sum(radii) / n
        spread = max(radii) - min(radii)
        # Smaller rings are mostly letters (o, 0, 6, 9).
        if r >= 2 * max_thickness and spread <= max_thickness + 1 and min(radii) > 0.5 * r:
            return Ring(mx, my, r)
    return None


def vectorize(
    width: int,
    height: int,
    ink: bytes,
    min_length: int | None = None,
    max_thickness: int | None = None,
) -> list[Stroke | Ring]:
    """Lines and circles found in the picture (see the module description)."""
    if width <= 0 or height <= 0 or len(ink) < width * height:
        return []
    if min_length is None:
        min_length = max(10, max(width, height) // 120)
    if max_thickness is None:
        max_thickness = max(4, max(width, height) // 150)
    rows = [ink[y * width : (y + 1) * width] for y in range(height)]
    columns = [ink[x : width * height : width] for x in range(width)]
    hs = [
        Stroke(s, (a + b) / 2, e, (a + b) / 2, b - a + 1)
        for a, b, s, e in _strokes(rows, min_length, max_thickness)
    ]
    vs = [
        Stroke((a + b) / 2, s, (a + b) / 2, e, b - a + 1)
        for a, b, s, e in _strokes(columns, min_length, max_thickness)
    ]
    gap = max(4, 2 * max_thickness)
    hs = _join(_merge_parallel(hs, True, max_thickness), True, gap)
    vs = _join(_merge_parallel(vs, False, max_thickness), False, gap)
    reach = max_thickness + 2
    hs, vs = _meet(hs, vs, reach)
    # The rest of the ink: sloped lines and circles.
    rest = bytearray(ink[: width * height])
    margin = 1
    for s in hs:
        y0 = max(0, int(s.y1 - s.thickness / 2) - margin)
        y1 = min(height - 1, int(s.y1 + s.thickness / 2) + margin)
        x0, x1 = max(0, int(min(s.x1, s.x2))), min(width - 1, int(max(s.x1, s.x2)))
        for y in range(y0, y1 + 1):
            rest[y * width + x0 : y * width + x1 + 1] = bytes(x1 - x0 + 1)
    for s in vs:
        x0 = max(0, int(s.x1 - s.thickness / 2) - margin)
        x1 = min(width - 1, int(s.x1 + s.thickness / 2) + margin)
        y0, y1 = max(0, int(min(s.y1, s.y2))), min(height - 1, int(max(s.y1, s.y2)))
        for y in range(y0, y1 + 1):
            rest[y * width + x0 : y * width + x1 + 1] = bytes(x1 - x0 + 1)
    left = set()
    for m in re.finditer(rb"\x01+", bytes(rest)):
        left.update(range(m.start(), m.end()))
    others: list[Stroke | Ring] = []
    for piece in _pieces(left, width):
        if len(piece) < min_length:
            continue
        shape = _shape(piece, width, min_length, max_thickness)
        if shape is not None:
            others.append(shape)
    return _without_specks([*hs, *vs, *others], reach, 4 * min_length)
