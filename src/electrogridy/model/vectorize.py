"""Lines and circles of a straightened picture of a circuit diagram. Pure Python.

The picture comes as one byte per pixel, 1 for ink, row after row. Sizes follow the
drawing, not the picture: the width of its strokes and the height of its letters.
Horizontal and vertical strokes are runs of ink along the rows (and along the
columns) that continue on the neighbouring rows; pieces of one line, broken or
dashed with even gaps, are joined, and ends close to a line across are drawn onto
it. Circles are rings once the long strokes are taken away (a wire through a
terminal leaves its ring in two halves, joined again by their centre). What is left
in thin pieces is a sloped line (switch blades, the diagonals of T branches, arrow
heads); a piece that is more than one line gives its lines one by one. The drawing
frame (the outermost long lines that are drawn, not the edge of the sheet) tells
what lies outside the drawing.
"""

import math
import random
import re
from collections import Counter
from dataclasses import dataclass

from electrogridy.model.text_layout import components


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


def stroke_width(width: int, height: int, ink: bytes) -> float:
    """Usual width of the strokes: the most common length of vertical runs that
    cross long horizontal runs."""
    counts = Counter()
    long_run = re.compile(rb"\x01{40,}")
    step = max(1, height // 400)
    for y in range(0, height, step):
        row = ink[y * width : (y + 1) * width]
        for m in long_run.finditer(row):
            x = (m.start() + m.end()) // 2
            # length of the vertical run through (x, y)
            y0 = y
            while y0 > 0 and ink[(y0 - 1) * width + x]:
                y0 -= 1
            y1 = y
            while y1 + 1 < height and ink[(y1 + 1) * width + x]:
                y1 += 1
            n = y1 - y0 + 1
            if n <= 12:
                counts[n] += 1
    if not counts:
        return 2.0
    return float(max(counts, key=lambda v: counts[v]))


def _join(
    strokes: list[Stroke], horizontal: bool, small_gap: float, dash_gap: float, dash_len: float
) -> list[Stroke]:
    """Pieces on one line joined: across small gaps always, across bigger ones when
    they repeat evenly (a dashed line)."""

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
        thickness = sorted(p.thickness for p in pieces)[len(pieces) // 2]
        if horizontal:
            return Stroke(lo, middle, hi, middle, thickness, dashed)
        return Stroke(middle, lo, middle, hi, thickness, dashed)

    rows: list[list[Stroke]] = []
    for s in sorted(strokes, key=pos):
        if rows and pos(s) - pos(rows[-1][-1]) <= 1.6:
            rows[-1].append(s)
        else:
            rows.append([s])
    out: list[Stroke] = []
    for row in rows:
        pieces = sorted(row, key=lambda s: span(s)[0])
        # solid: pieces closer than small_gap
        solid: list[list[Stroke]] = []
        end = None
        for s in pieces:
            a, b = span(s)
            if end is not None and a - end <= small_gap:
                solid[-1].append(s)
                end = max(end, b)
            else:
                solid.append([s])
                end = b
        joined = [made(g, False) for g in solid]
        # dashed: runs of short pieces with even gaps
        i = 0
        while i < len(joined):
            j = i
            while (
                j + 1 < len(joined)
                and span(joined[j + 1])[0] - span(joined[j])[1] <= dash_gap
                and span(joined[j])[1] - span(joined[j])[0] <= dash_len
                and span(joined[j + 1])[1] - span(joined[j + 1])[0] <= dash_len
            ):
                j += 1
            if j - i >= 2:  # three dashes or more
                gaps = [span(joined[k + 1])[0] - span(joined[k])[1] for k in range(i, j)]
                lens = [span(joined[k])[1] - span(joined[k])[0] for k in range(i, j + 1)]
                if (
                    max(gaps) <= 2.2 * min(gaps) + 3
                    and max(lens[1:-1] or lens) <= 2.5 * min(lens[1:-1] or lens) + 3
                ):
                    out.append(made(joined[i : j + 1], True))
                    i = j + 1
                    continue
            out.append(joined[i])
            i += 1
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


def _fit_circle(points: list[tuple[int, int]]):
    """Least squares circle (Kasa) through pixel points: (cx, cy, r, rms)."""
    n = len(points)
    sx = sum(p[0] for p in points) / n
    sy = sum(p[1] for p in points) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for x, y in points:
        u, v = x - sx, y - sy
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    a, b, c, d = suu, suv, suv, svv
    e = 0.5 * (suuu + suvv)
    f = 0.5 * (svvv + svuu)
    det = a * d - b * c
    if abs(det) < 1e-9:
        return None
    uc = (e * d - b * f) / det
    vc = (a * f - c * e) / det
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    cx, cy = sx + uc, sy + vc
    rms = math.sqrt(sum((math.hypot(x - cx, y - cy) - r) ** 2 for x, y in points) / n)
    return cx, cy, r, rms


def circles(width: int, height: int, ink: bytes, w: float, cap: float) -> list[Ring]:
    """Rings once long strokes are taken away (a wire through a terminal leaves its
    ring in two halves, joined again by their common centre)."""
    length = max(8, round(3.2 * cap))
    out = bytearray(ink)
    pattern = re.compile(rb"\x01{%d,}" % length)
    for y in range(height):
        for m in pattern.finditer(ink[y * width : (y + 1) * width]):
            out[y * width + m.start() : y * width + m.end()] = bytes(m.end() - m.start())
    for x in range(width):
        for m in pattern.finditer(ink[x::width]):
            for y in range(m.start(), m.end()):
                out[y * width + x] = 0
    found = []
    smallest = max(2.5, 1.4 * w)
    largest = 4.0 * cap
    for b in components(width, height, bytes(out)):
        side = max(b.w, b.h)
        if side < 2 * smallest or side > 2.4 * largest:
            continue
        pts = [(x, y) for y in range(b.y0, b.y1) for x in range(b.x0, b.x1) if out[y * width + x]]
        if len(pts) < 8:
            continue
        fit = _fit_circle(pts)
        if fit is None:
            continue
        cx, cy, r, rms = fit
        if not (smallest <= r <= largest) or rms > max(0.9, 0.45 * w):
            continue
        # most directions around the centre have ink (an arc of at least 150 degrees)
        sectors = set()
        for x, y in pts:
            sectors.add(int((math.atan2(y - cy, x - cx) + math.pi) / (2 * math.pi) * 24) % 24)
        # inside a ring there is no ink (a filled dot or a letter like e, a, 8 has)
        inner = sum(1 for x, y in pts if math.hypot(x - cx, y - cy) < 0.45 * r)
        if inner > 0.05 * len(pts):
            continue
        found.append((cx, cy, r, len(sectors), b))
    # halves of one ring
    merged = []
    for cx, cy, r, sec, b in sorted(found, key=lambda t: -t[3]):
        for m in merged:
            if math.hypot(m[0] - cx, m[1] - cy) <= 0.35 * r and abs(m[2] - r) <= 0.3 * r:
                m[3] += sec
                m[4].append(b)
                break
        else:
            merged.append([cx, cy, r, sec, [b]])
    # nearly closed (a u, n or c is open by a quarter or more)
    return [Ring(cx, cy, r) for cx, cy, r, sec, _boxes in merged if sec >= 20]


def without_rings(width: int, height: int, ink: bytes, rings: list[Ring], w: float) -> bytes:
    """The ink with the rings painted out (a band of the stroke width around each);
    a wire running through a ring keeps its pixels there."""
    out = bytearray(ink)
    run = re.compile(rb"\x01+")
    for ring in rings:
        band = 0.5 * w + 1.5
        x0, x1 = (
            max(0, int(ring.cx - ring.r - band)),
            min(width - 1, int(ring.cx + ring.r + band) + 1),
        )
        y0, y1 = (
            max(0, int(ring.cy - ring.r - band)),
            min(height - 1, int(ring.cy + ring.r + band) + 1),
        )
        through = 2 * (ring.r + band) + 2
        keep = set()
        for y in range(y0, y1 + 1):
            for m in run.finditer(ink, y * width + max(0, x0 - width), (y + 1) * width):
                if m.end() - m.start() >= through:
                    keep.update(range(m.start(), m.end()))
        for x in range(x0, x1 + 1):
            column = ink[x::width]
            for m in run.finditer(column, max(0, y0 - height), min(height, y1 + height)):
                if m.end() - m.start() >= through:
                    keep.update(
                        yy * width + x for yy in range(max(y0, m.start()), min(y1 + 1, m.end()))
                    )
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                i = y * width + x
                if i not in keep and abs(math.hypot(x - ring.cx, y - ring.cy) - ring.r) <= band:
                    out[i] = 0
    return bytes(out)


def _sloped(
    width: int, height: int, ink: bytes, hs, vs, w: float, min_len: float, max_thick: float
) -> list[Stroke]:
    """Thin pieces of what is left once horizontal and vertical strokes are taken
    away: switch blades, diagonals of T branches, arrow heads."""
    rest = bytearray(ink)
    m = max(1, round(w / 2))
    for s in hs:
        y0 = max(0, int(s.y1 - s.thickness / 2) - m)
        y1 = min(height - 1, int(s.y1 + s.thickness / 2) + m)
        x0, x1 = max(0, int(min(s.x1, s.x2)) - m), min(width - 1, int(max(s.x1, s.x2)) + m)
        for y in range(y0, y1 + 1):
            rest[y * width + x0 : y * width + x1 + 1] = bytes(x1 - x0 + 1)
    for s in vs:
        x0 = max(0, int(s.x1 - s.thickness / 2) - m)
        x1 = min(width - 1, int(s.x1 + s.thickness / 2) + m)
        y0, y1 = max(0, int(min(s.y1, s.y2)) - m), min(height - 1, int(max(s.y1, s.y2)) + m)
        for y in range(y0, y1 + 1):
            rest[y * width + x0 : y * width + x1 + 1] = bytes(x1 - x0 + 1)
    out = []
    for b in components(width, height, bytes(rest)):
        if max(b.w, b.h) < min_len:
            continue
        pts = [(x, y) for y in range(b.y0, b.y1) for x in range(b.x0, b.x1) if rest[y * width + x]]
        n = len(pts)
        if n < min_len:
            continue
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts) / n
        syy = sum((p[1] - my) ** 2 for p in pts) / n
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
        angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
        ux, uy = math.cos(angle), math.sin(angle)
        along = [(p[0] - mx) * ux + (p[1] - my) * uy for p in pts]
        across = [-(p[0] - mx) * uy + (p[1] - my) * ux for p in pts]
        length = max(along) - min(along)
        thick = max(across) - min(across) + 1
        if length >= min_len and thick <= max_thick and length >= 2.5 * thick:
            a, c = min(along), max(along)
            out.append(Stroke(mx + a * ux, my + a * uy, mx + c * ux, my + c * uy, thick))
        elif length >= min_len:
            out += _lines_in(pts, w, min_len, max_thick)
    return out


def _lines_in(pts, w: float, min_len: float, max_thick: float, most: int = 3) -> list[Stroke]:
    """Straight pieces inside a piece of ink that is more than one line (a diagonal
    touching a letter, two diagonals side by side): the line through most points,
    taken out, then the next."""
    rng = random.Random(len(pts))
    tol = 0.5 * w + 1.0
    left = list(pts)
    out = []
    for _ in range(most):
        if len(left) < min_len:
            break
        sample = left if len(left) <= 400 else rng.sample(left, 400)
        best = None
        for _it in range(80):
            a, b = rng.sample(sample, 2)
            dx, dy = b[0] - a[0], b[1] - a[1]
            d = math.hypot(dx, dy)
            if d < 0.5 * min_len:
                continue
            ux, uy = dx / d, dy / d
            count = sum(1 for p in sample if abs(-(p[0] - a[0]) * uy + (p[1] - a[1]) * ux) <= tol)
            if best is None or count > best[0]:
                best = (count, a, ux, uy)
        if best is None:
            break
        _, a, ux, uy = best
        inl = [p for p in left if abs(-(p[0] - a[0]) * uy + (p[1] - a[1]) * ux) <= tol]
        proj = sorted(((p[0] - a[0]) * ux + (p[1] - a[1]) * uy, p) for p in inl)
        # the longest stretch without a gap
        runs, cur = [], [proj[0]] if proj else []
        for item in proj[1:]:
            if item[0] - cur[-1][0] > 2 * w + 1:
                runs.append(cur)
                cur = []
            cur.append(item)
        if cur:
            runs.append(cur)
        run = max(runs, key=lambda r: r[-1][0] - r[0][0]) if runs else []
        if not run or run[-1][0] - run[0][0] < min_len or len(run) < 0.8 * (run[-1][0] - run[0][0]):
            break
        rp = [p for _, p in run]
        n = len(rp)
        mx, my = sum(p[0] for p in rp) / n, sum(p[1] for p in rp) / n
        sxx = sum((p[0] - mx) ** 2 for p in rp) / n
        syy = sum((p[1] - my) ** 2 for p in rp) / n
        sxy = sum((p[0] - mx) * (p[1] - my) for p in rp) / n
        ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
        vx, vy = math.cos(ang), math.sin(ang)
        al = [(p[0] - mx) * vx + (p[1] - my) * vy for p in rp]
        ac = [-(p[0] - mx) * vy + (p[1] - my) * vx for p in rp]
        thick = max(ac) - min(ac) + 1
        if thick <= max_thick:
            out.append(
                Stroke(
                    mx + min(al) * vx,
                    my + min(al) * vy,
                    mx + max(al) * vx,
                    my + max(al) * vy,
                    thick,
                )
            )
        taken = set(rp)
        left = [p for p in left if p not in taken]
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


def _box(u: Stroke | Ring) -> tuple[float, float, float, float]:
    if isinstance(u, Ring):
        return u.cx - u.r, u.cy - u.r, u.cx + u.r, u.cy + u.r
    return min(u.x1, u.x2), min(u.y1, u.y2), max(u.x1, u.x2), max(u.y1, u.y2)


def _without_specks(shapes: list, reach: float, size: float) -> list:
    """Without groups of two or more touching lines smaller than ``size`` that touch
    nothing else: bits of lettering."""
    parent = list(range(len(shapes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = max(8.0, 4 * reach)
    grid: dict[tuple[int, int], list[int]] = {}
    boxes = [_box(s) for s in shapes]
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        for gx in range(int((x0 - reach) // cell), int((x1 + reach) // cell) + 1):
            for gy in range(int((y0 - reach) // cell), int((y1 + reach) // cell) + 1):
                for j in grid.get((gx, gy), ()):
                    if root(i) != root(j) and _near(shapes[i], shapes[j], reach):
                        parent[root(i)] = root(j)
                grid.setdefault((gx, gy), []).append(i)
    extent: dict[int, list[float]] = {}
    members: dict[int, int] = {}
    for i, b in enumerate(boxes):
        r = extent.setdefault(root(i), list(b))
        r[:] = [min(r[0], b[0]), min(r[1], b[1]), max(r[2], b[2]), max(r[3], b[3])]
        members[root(i)] = members.get(root(i), 0) + 1
    # a single stroke stays: it may be what is left of a dashed line
    keep = {
        k for k, b in extent.items() if max(b[2] - b[0], b[3] - b[1]) >= size or members[k] == 1
    }
    return [s for i, s in enumerate(shapes) if root(i) in keep]


def vectorize(
    width: int,
    height: int,
    ink: bytes,
    cap: float,
    rings: list[Ring] | None = None,
    stroke: float | None = None,
) -> list[Stroke | Ring]:
    """Lines and circles found in the picture (see the module description); ``cap`` is
    the height of the usual capitals in pixels, ``rings`` the circles if they were
    found before (their ink then does not count for lines), ``stroke`` the width of the
    strokes (measured if not given)."""
    if width <= 0 or height <= 0 or len(ink) < width * height:
        return []
    w = stroke if stroke is not None else stroke_width(width, height, ink)
    if rings is None:
        rings = circles(width, height, ink, w, cap)
    ink = without_rings(width, height, ink, rings, w)
    min_len = max(5, round(2.5 * w))
    max_thick = max(3, round(2.6 * w))
    rows = [ink[y * width : (y + 1) * width] for y in range(height)]
    cols = [ink[x::width] for x in range(width)]
    hs = [
        Stroke(s, (a + b) / 2, e, (a + b) / 2, b - a + 1)
        for a, b, s, e in _strokes(rows, min_len, max_thick)
    ]
    vs = [
        Stroke((a + b) / 2, s, (a + b) / 2, e, b - a + 1)
        for a, b, s, e in _strokes(cols, min_len, max_thick)
    ]
    # only the two edges of one blurred line, not two lines side by side
    hs = _merge_parallel(hs, True, max(1.5, 0.5 * w))
    vs = _merge_parallel(vs, False, max(1.5, 0.5 * w))
    small_gap = max(3, 1.5 * w)
    dash_gap = max(6, 0.9 * cap)
    dash_len = max(10, 2.5 * cap)
    hs = _join(hs, True, small_gap, dash_gap, dash_len)
    vs = _join(vs, False, small_gap, dash_gap, dash_len)
    hs, vs = _meet(hs, vs, max_thick + 1)
    sloped = _sloped(width, height, ink, hs, vs, w, max(min_len, 0.5 * cap), max_thick)
    # small groups of strokes touching nothing else: letters that were not read
    lines = _without_specks([*hs, *vs, *sloped], max_thick + 1, 1.6 * cap)
    return [*lines, *rings]


def printed(s: Stroke, width: int, height: int, gray: bytes, horizontal: bool) -> bool:
    """A drawn line is darker than the paper on both sides of it; the edge of the
    sheet (or of a thumb) is a step: on one side it is about as dark as the "line"."""
    off = s.thickness / 2 + 3
    a, b = (min(s.x1, s.x2), max(s.x1, s.x2)) if horizontal else (min(s.y1, s.y2), max(s.y1, s.y2))
    lows, sides = [], []

    def at(t: float, d: float) -> int | None:
        x, y = (t, s.y1 + d) if horizontal else (s.x1 + d, t)
        xi, yi = round(x), round(y)
        if 0 <= xi < width and 0 <= yi < height:
            return gray[yi * width + xi]
        return None

    for k in range(80):
        t = a + (b - a) * (k + 0.5) / 80
        centre = [v for v in (at(t, d) for d in (-1, 0, 1)) if v is not None]
        left = [v for v in (at(t, -off - d) for d in range(4)) if v is not None]
        right = [v for v in (at(t, off + d) for d in range(4)) if v is not None]
        if centre and left and right:
            lows.append(min(centre))
            sides.append((sorted(left)[len(left) // 2], sorted(right)[len(right) // 2]))
    if len(lows) < 20:
        return False
    contrast = sorted(min(left, right) - c for c, (left, right) in zip(lows, sides, strict=True))
    paper = sorted(max(left, right) for left, right in sides)[len(sides) // 2]
    # the darker side must still be clearly lighter than the line, along most of it
    return contrast[len(contrast) // 3] >= 0.12 * max(40, paper)


def frame_box(shapes, width: int, height: int, gray: bytes, share: float = 0.25):
    """The drawing frame: on each side the outermost long drawn line, or None."""
    hs = [
        s
        for s in shapes
        if isinstance(s, Stroke) and abs(s.y1 - s.y2) < 1 and abs(s.x2 - s.x1) >= share * width
    ]
    vs = [
        s
        for s in shapes
        if isinstance(s, Stroke) and abs(s.x1 - s.x2) < 1 and abs(s.y2 - s.y1) >= share * height
    ]
    hs = [s for s in hs if printed(s, width, height, gray, True)]
    vs = [s for s in vs if printed(s, width, height, gray, False)]
    if not hs or not vs:
        return None
    x0, x1 = min(s.x1 for s in vs), max(s.x1 for s in vs)
    y0, y1 = min(s.y1 for s in hs), max(s.y1 for s in hs)
    # A frame holds the drawing and fills most of the picture: a box in a drawing
    # cut out by hand is none. Drawn lines may hardly lie outside it (the edge of
    # the sheet and a thumb are no drawn lines).
    if x1 - x0 < 0.55 * width or y1 - y0 < 0.55 * height:
        return None
    inner = outer = 0.0
    for s in shapes:
        if not isinstance(s, Stroke):
            continue
        across = abs(s.y1 - s.y2) < 1
        upright = abs(s.x1 - s.x2) < 1
        length = abs(s.x2 - s.x1) if across else abs(s.y2 - s.y1)
        if not (across or upright) or length < 0.1 * (width if across else height):
            continue
        mx, my = (s.x1 + s.x2) / 2, (s.y1 + s.y2) / 2
        if x0 - 2 <= mx <= x1 + 2 and y0 - 2 <= my <= y1 + 2:
            inner += length
        elif printed(s, width, height, gray, across):
            outer += length
    if outer > 0.1 * inner:
        return None
    return x0, y0, x1, y1


def inside(shapes, box, margin: float):
    """The shapes within the frame (lines cut at its edge)."""
    x0, y0, x1, y1 = box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin
    out = []
    for s in shapes:
        if isinstance(s, Ring):
            if x0 <= s.cx <= x1 and y0 <= s.cy <= y1:
                out.append(s)
            continue
        ax, ay, bx, by = s.x1, s.y1, s.x2, s.y2
        # Liang-Barsky clipping
        t0, t1 = 0.0, 1.0
        dx, dy = bx - ax, by - ay
        ok = True
        for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
            if p == 0:
                if q < 0:
                    ok = False
                    break
            else:
                r = q / p
                if p < 0:
                    t0 = max(t0, r)
                else:
                    t1 = min(t1, r)
        if ok and t0 < t1:
            out.append(
                Stroke(
                    ax + t0 * dx, ay + t0 * dy, ax + t1 * dx, ay + t1 * dy, s.thickness, s.dashed
                )
            )
    return out
