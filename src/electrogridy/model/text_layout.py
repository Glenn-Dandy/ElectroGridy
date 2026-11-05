"""Where the texts of a straightened circuit diagram are. Pure Python.

Letters are connected pieces of ink (8 neighbours), found from the runs of each row;
letters touching a wire or a frame come free when the long strokes of such big
pieces are taken out. Letters beside each other of about one size make a line, across
or upright (read from bottom to top or from top to bottom); which way a letter goes
decides its shape (letters standing are higher than wide, turned a quarter wider
than high) and its company. Lines are cut at the walls between the cells of a
terminal strip (|1|2|3|), which are strokes joining two lines across them.
"""

import bisect
import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Box:
    x0: int
    y0: int
    x1: int  # exclusive
    y1: int
    count: int = 0  # pixels of ink

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0


def components(width: int, height: int, ink: bytes) -> list[Box]:
    """Connected pieces of ink (8 neighbours), from the runs of each row."""
    run = re.compile(rb"\x01+")
    runs: list[tuple[int, int, int]] = []
    starts = []
    for y in range(height):
        starts.append(len(runs))
        row = ink[y * width : (y + 1) * width]
        runs.extend((y, m.start(), m.end()) for m in run.finditer(row))
    starts.append(len(runs))
    parent = list(range(len(runs)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(1, height):
        j0 = starts[y - 1]
        stop = starts[y]
        for i in range(starts[y], starts[y + 1]):
            _, x1, x2 = runs[i]
            for j in range(j0, stop):
                _, a1, a2 = runs[j]
                if a2 < x1:  # ends left of this run (touching diagonally counts)
                    j0 = j + 1
                    continue
                if a1 > x2:
                    break
                ri, rj = root(i), root(j)
                if ri != rj:
                    parent[ri] = rj
    boxes: dict[int, Box] = {}
    for i, (y, x1, x2) in enumerate(runs):
        r = root(i)
        b = boxes.get(r)
        if b is None:
            boxes[r] = Box(x1, y, x2, y + 1, x2 - x1)
        else:
            if x1 < b.x0:
                b.x0 = x1
            if x2 > b.x1:
                b.x1 = x2
            if y + 1 > b.y1:
                b.y1 = y + 1
            b.count += x2 - x1
    return list(boxes.values())


def runs_of(w: int, h: int, ink: bytes):
    run = re.compile(rb"\x01+")
    runs, starts = [], []
    for y in range(h):
        starts.append(len(runs))
        runs.extend((y, m.start(), m.end()) for m in run.finditer(ink[y * w : (y + 1) * w]))
    starts.append(len(runs))
    return runs, starts


def labelled(w: int, h: int, ink: bytes):
    """Runs, row starts, the root of each run and the boxes of the roots."""
    runs, starts = runs_of(w, h, ink)
    parent = list(range(len(runs)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(1, h):
        j0, stop = starts[y - 1], starts[y]
        for i in range(starts[y], starts[y + 1]):
            _, x1, x2 = runs[i]
            for j in range(j0, stop):
                _, a1, a2 = runs[j]
                if a2 < x1:
                    j0 = j + 1
                    continue
                if a1 > x2:
                    break
                ri, rj = root(i), root(j)
                if ri != rj:
                    parent[ri] = rj
    roots = [root(i) for i in range(len(runs))]
    boxes: dict[int, Box] = {}
    for (y, x1, x2), r in zip(runs, roots, strict=True):
        b = boxes.get(r)
        if b is None:
            boxes[r] = Box(x1, y, x2, y + 1, x2 - x1)
        else:
            b.x0 = min(b.x0, x1)
            b.x1 = max(b.x1, x2)
            b.y1 = y + 1
            b.count += x2 - x1
    return runs, starts, roots, boxes


def estimate_cap(boxes) -> float:
    """Height of the usual capitals: heights of pieces that have a neighbour of about
    their height beside them (letters of a word), the most common one."""
    cands = [b for b in boxes if 7 <= b.h <= 150 and 0.12 <= b.w / b.h <= 1.5]
    cands.sort(key=lambda b: b.x0)
    xs = [b.x0 for b in cands]
    counts = Counter()
    for b in cands:
        reach = 1.2 * b.h
        lo = bisect.bisect_left(xs, b.x1 - 1)
        hi = bisect.bisect_right(xs, b.x1 + reach)
        for c in cands[lo:hi]:
            if c is b:
                continue
            if 0.7 <= c.h / b.h <= 1.4 and min(b.y1, c.y1) - max(b.y0, c.y0) >= 0.6 * min(b.h, c.h):
                counts[b.h] += 1
                break
    if not counts:
        return 20.0
    return float(
        max(counts, key=lambda v: counts[v] + 0.6 * (counts.get(v - 1, 0) + counts.get(v + 1, 0)))
    )


def letters_apart(w: int, h: int, ink: bytes, cap: float) -> tuple[bytes, list[Box]]:
    """Ink with the long strokes of big pieces (wires, frames) taken out, so letters
    touching them come free, and the pieces of that ink."""
    runs, starts, roots, boxes = labelled(w, h, ink)
    big = {r for r, b in boxes.items() if max(b.w, b.h) > 4 * cap}
    length = max(10, round(2.2 * cap))
    out = bytearray(ink)
    for (y, x1, x2), r in zip(runs, roots, strict=True):
        if x2 - x1 >= length and r in big:
            out[y * w + x1 : y * w + x2] = bytes(x2 - x1)
    pattern = re.compile(rb"\x01{%d,}" % length)
    for x in range(w):
        for m in pattern.finditer(ink[x::w]):
            y = m.start()
            row = runs[starts[y] : starts[y + 1]]
            k = bisect.bisect_right([r[1] for r in row], x) - 1
            if k < 0 or roots[starts[y] + k] not in big:
                continue
            for yy in range(m.start(), m.end()):
                out[yy * w + x] = 0
    pieces = components(w, h, bytes(out))
    return bytes(out), pieces


@dataclass
class TextLine:
    boxes: list[Box] = field(default_factory=list)
    upright: bool = False  # letters stacked from bottom to top (or top to bottom)
    walled: bool = False  # cut out of a longer line at the walls of cells

    @property
    def x0(self) -> int:
        return min(b.x0 for b in self.boxes)

    @property
    def y0(self) -> int:
        return min(b.y0 for b in self.boxes)

    @property
    def x1(self) -> int:
        return max(b.x1 for b in self.boxes)

    @property
    def y1(self) -> int:
        return max(b.y1 for b in self.boxes)

    @property
    def size(self) -> float:
        """Height of the letters (across the line)."""
        sizes = sorted((b.w if self.upright else b.h) for b in self.boxes)
        return sizes[len(sizes) * 3 // 4] if sizes else 0


def letter_like(b: Box, smallest: int, largest: int) -> bool:
    """Whether a piece may be a letter: between ``smallest`` and ``largest`` (about a
    quarter and three and a half capitals) and not filled (a filled box is none; thin
    straight letters such as i, l and 1 count only beside others, see ``thin_letter``)."""
    side = max(b.w, b.h)
    if side < smallest or side > largest:
        return False
    fill = b.count / max(1, b.w * b.h)
    return fill < 0.85 or side <= smallest * 2


def thin_letter(b: Box, cap: float) -> bool:
    """A thin straight piece of letter size (i, l, 1, I, a dash)."""
    side = max(b.w, b.h)
    return min(b.w, b.h) <= 0.35 * side and 0.25 * cap <= side <= 1.3 * cap


def _chains(boxes: list[Box], upright: bool, gap: float = 1.1) -> list[list[int]]:
    """Indices of the boxes that sit next to each other along a line: overlapping
    across the line, about the same size, closer than ``gap`` letter heights."""

    def across(b: Box) -> tuple[int, int]:
        return (b.x0, b.x1) if upright else (b.y0, b.y1)

    def along(b: Box) -> tuple[int, int]:
        return (b.y0, b.y1) if upright else (b.x0, b.x1)

    order = sorted(range(len(boxes)), key=lambda i: along(boxes[i])[0])
    parent = list(range(len(boxes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Sweep along the lines: candidates whose start lies within reach.
    active: list[int] = []
    for i in order:
        a0, a1 = along(boxes[i])
        c0, c1 = across(boxes[i])
        size_i = c1 - c0
        keep = []
        best = None
        for j in active:
            b0, b1 = along(boxes[j])
            d0, d1 = across(boxes[j])
            size_j = d1 - d0
            reach = gap * max(size_i, size_j)
            if b1 + reach < a0:
                continue
            keep.append(j)
            overlap = min(c1, d1) - max(c0, d0)
            small, big = min(size_i, size_j), max(size_i, size_j)
            if overlap <= 0.5 * small:
                continue
            # Small ones (dots, dashes) only inside the band of the big one.
            if small < 0.45 * big and not (c0 >= d0 - 0.15 * big and c1 <= d1 + 0.15 * big):
                continue
            if big > 2.6 * small and small >= 0.45 * big:
                continue
            dist = a0 - b1
            if best is None or dist < best[0]:
                best = (dist, j)
        if best is not None:
            ri, rj = root(i), root(best[1])
            if ri != rj:
                parent[ri] = rj
        keep.append(i)
        active = keep
    groups: dict[int, list[int]] = {}
    for i in range(len(boxes)):
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def text_lines(boxes: list[Box]) -> list[TextLine]:
    """Lines of letters; each letter goes to the reading direction in which it has
    more company (single letters stay across)."""
    across = _chains(boxes, False)
    upright = _chains(boxes, True)
    member_across = {}
    for g in across:
        for i in g:
            member_across[i] = len(g)
    member_up = {}
    for g in upright:
        for i in g:
            member_up[i] = len(g)

    # Letters standing upright are mostly higher than wide; turned a quarter, wider
    # than high: the chains whose letters do not fit their direction lose.
    def fits(g, up: bool) -> float:
        ratios = sorted((boxes[i].w / max(1, boxes[i].h)) for i in g)
        r = ratios[len(ratios) // 2]
        return (r >= 1.0) if up else (r <= 1.0)

    score_across, score_up = {}, {}
    for g in across:
        f = 1.0 if (len(g) < 2 or fits(g, False)) else 0.3
        for i in g:
            score_across[i] = len(g) * f
    for g in upright:
        f = 1.0 if fits(g, True) else 0.3
        for i in g:
            score_up[i] = len(g) * f if len(g) >= 2 else 0
    lines = []
    for g in across:
        kept = [i for i in g if score_across[i] >= score_up.get(i, 0)]
        if kept:
            lines.append(TextLine([boxes[i] for i in kept], False))
    for g in upright:
        kept = [i for i in g if score_up[i] > score_across.get(i, 0) and len(g) >= 2]
        if kept:
            lines.append(TextLine([boxes[i] for i in kept], True))
    return lines


def split_at_walls(lines: list[TextLine]) -> list[TextLine]:
    """Lines cut where a thin stroke higher than the letters stands between them: the
    walls of a terminal strip (|1|2|3|), which are no letters."""
    out = []
    for line in lines:
        if len(line.boxes) < 2:
            out.append(line)
            continue
        if line.upright:

            def across(b):
                return b.w

            def thin(b):
                return b.h

            key = lambda b: b.y0  # noqa: E731
        else:

            def across(b):
                return b.h

            def thin(b):
                return b.w

            key = lambda b: b.x0  # noqa: E731
        boxes = sorted(line.boxes, key=key)
        heights = sorted(across(b) for b in boxes)
        usual = heights[len(heights) // 2]
        walls = [
            b for b in boxes if thin(b) <= max(2, 0.3 * across(b)) and across(b) >= 1.12 * usual
        ]
        if not walls or len(walls) == len(boxes):
            out.append(line)
            continue
        part: list[Box] = []
        for b in boxes:
            if b in walls:
                if part:
                    out.append(TextLine(part, line.upright))
                part = []
            else:
                part.append(b)
        if part:
            out.append(TextLine(part, line.upright))
    return out


def walls_of(strokes, reach: float = 3.0):
    """Short strokes joining two lines across them (the walls between the cells of a
    terminal strip): vertical ones as (x, y0, y1), horizontal ones as (y, x0, x1)."""
    hs = [s for s in strokes if abs(s.y1 - s.y2) < 1e-6 and abs(s.x2 - s.x1) > 0]
    vs = [s for s in strokes if abs(s.x1 - s.x2) < 1e-6 and abs(s.y2 - s.y1) > 0]

    def touches_h(x, y):
        return any(
            abs(h.y1 - y) <= reach and min(h.x1, h.x2) - reach <= x <= max(h.x1, h.x2) + reach
            for h in hs
        )

    def touches_v(x, y):
        return any(
            abs(v.x1 - x) <= reach and min(v.y1, v.y2) - reach <= y <= max(v.y1, v.y2) + reach
            for v in vs
        )

    upright_walls = []
    for v in vs:
        y0, y1 = sorted((v.y1, v.y2))
        if touches_h(v.x1, y0) and touches_h(v.x1, y1):
            upright_walls.append((v.x1, y0, y1))
    across_walls = []
    for h in hs:
        x0, x1 = sorted((h.x1, h.x2))
        if touches_v(x0, h.y1) and touches_v(x1, h.y1):
            across_walls.append((h.y1, x0, x1))
    return upright_walls, across_walls


def _cuts(line: TextLine, vwalls, hwalls) -> list[float]:
    """Where walls of cells cross the line, along it."""
    if line.upright:
        return sorted(
            y
            for y, x0, x1 in hwalls
            if x0 <= line.x0 + 2 and x1 >= line.x1 - 2 and line.y0 < y < line.y1
        )
    return sorted(
        x
        for x, y0, y1 in vwalls
        if y0 <= line.y0 + 2 and y1 >= line.y1 - 2 and line.x0 < x < line.x1
    )


def _is_wall(b: Box, cuts: list[float], upright: bool) -> bool:
    if upright:
        return any(b.y0 - 2 <= c <= b.y1 + 2 and b.h <= 0.5 * b.w + 3 for c in cuts)
    return any(b.x0 - 2 <= c <= b.x1 + 2 and b.w <= 0.5 * b.h + 3 for c in cuts)


def split_by_walls(lines: list[TextLine], strokes) -> list[TextLine]:
    """Lines cut at the walls of cells standing between their letters; boxes that are
    a wall themselves leave the line. The pieces know they were cut (``walled``)."""
    vwalls, hwalls = walls_of(strokes)
    out = []
    for line in lines:
        cuts = _cuts(line, vwalls, hwalls)
        if not cuts:
            out.append(line)
            continue
        parts: dict[int, list[Box]] = {}
        for b in line.boxes:
            if _is_wall(b, cuts, line.upright):
                continue
            c = (b.y0 + b.y1) / 2 if line.upright else (b.x0 + b.x1) / 2
            parts.setdefault(sum(1 for x in cuts if x < c), []).append(b)
        for idx in sorted(parts):
            out.append(TextLine(parts[idx], line.upright, walled=True))
    return out


def ring_like(b: Box, rings) -> bool:
    """Whether the piece ``b`` is one of the rings (a terminal, not a letter)."""
    for ring in rings:
        if (
            abs((b.x0 + b.x1) / 2 - ring.cx) <= 0.4 * ring.r
            and abs((b.y0 + b.y1) / 2 - ring.cy) <= 0.4 * ring.r
            and abs(max(b.w, b.h) - 2 * ring.r) <= 0.6 * ring.r + 3
        ):
            return True
    return False


def letter_rings(rings, boxes: list[Box], cap: float) -> list:
    """The rings that are letters (O, 0, o): of letter size with another piece of
    letter size beside them, across or upright."""
    out = []
    for ring in rings:
        d = 2 * ring.r
        if not 0.5 * cap <= d <= 1.5 * cap:
            continue
        for b in boxes:
            if not 0.5 * cap <= b.h <= 1.6 * cap or b.w > 1.5 * cap:
                continue
            bx, by = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
            if abs(bx - ring.cx) < 0.4 * d and abs(by - ring.cy) < 0.4 * d:
                continue  # the ring itself
            # small letters sit lower than capitals: some room across the line
            room = 0.35 * cap + 0.2 * d
            across = abs(by - ring.cy) <= room and abs(bx - ring.cx) <= 0.6 * d + 0.9 * cap
            upright = abs(bx - ring.cx) <= room and abs(by - ring.cy) <= 0.6 * d + 0.9 * cap
            if across or upright:
                out.append(ring)
                break
    return out
