"""Lines and texts of a PDF page drawn by a CAD program, as drawing entities.

Uses pdfminer (python3-pdfminer). Coordinates come in points on the page as it is
shown (pdfminer applies the page rotation), y up; the result is in millimetres with
the top left corner of the chosen region at (0, 0) and y down. Curves are flattened,
four arcs around one centre become a circle, closed axis-parallel four-sided paths a
rectangle. Lines leaving the region are cut at its edge; texts are kept when they
start inside it. Characters are joined into texts in drawing order.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sldgridy.model.entities import Circle, Entity, Line, Polyline, Rectangle, Text, new_id
from sldgridy.model.geometry import Point

MM_PER_PT = 25.4 / 72
CAP_HEIGHT = 0.7  # capital height as a share of the font size
LINEWEIGHTS = (0.18, 0.25, 0.35, 0.5, 0.7, 1.0)
BEZIER_STEPS = 8
MIN_VECTOR_OBJECTS = 3  # fewer strokes: the page is a scan (perhaps with OCR text)


@dataclass(frozen=True)
class Region:
    """Part of the page in points, left/top measured from the top left corner."""

    left: float
    top: float
    right: float
    bottom: float


def available() -> bool:
    try:
        import pdfminer.high_level  # noqa: F401
    except ImportError:
        return False
    return True


def _layout(path: Path, page: int):
    from pdfminer.high_level import extract_pages

    return next(iter(extract_pages(str(path), page_numbers=[page], laparams=None)))


def _walk(objects) -> Iterable:
    from pdfminer.layout import LTContainer

    for o in objects:
        if isinstance(o, LTContainer) and not _is_text_char(o):
            yield o
            yield from _walk(o)
        else:
            yield o


def _is_text_char(o) -> bool:
    from pdfminer.layout import LTChar

    return isinstance(o, LTChar)


def vector_count(path: Path, page: int) -> int:
    """Strokes on the page: a CAD drawing has many, a scan none (an OCR text layer
    brings characters, but no strokes)."""
    from pdfminer.layout import LTCurve

    return sum(1 for o in _walk(_layout(path, page)) if isinstance(o, LTCurve))


def page_entities(path: Path, page: int, region: Region, scale: float = 1.0) -> list[Entity]:
    """Lines, polylines, rectangles, circles and texts of ``page`` (0-based) inside
    ``region``, in mm (``scale`` times the size on paper)."""
    from pdfminer.layout import LTChar, LTCurve

    layout = _layout(path, page)
    height = layout.height
    k = MM_PER_PT * scale

    def to_mm(x: float, y: float) -> Point:
        return Point((x - region.left) * k, (height - y - region.top) * k)

    box = (region.left, height - region.bottom, region.right, height - region.top)
    out: list[Entity] = []
    chars = []
    for o in _walk(layout):
        if isinstance(o, LTChar):
            chars.append(o)
        elif isinstance(o, LTCurve) and o.stroke and not _white(o.stroking_color):
            weight = _lineweight(o.linewidth * k)
            for shape in _shapes(o):
                out += _clipped(shape, box, to_mm, weight)
    out += _texts(chars, box, to_mm, k)
    return out


def _white(color) -> bool:
    if color is None:
        return False
    values = color if isinstance(color, list | tuple) else [color]
    try:
        values = [float(v) for v in values]
    except (TypeError, ValueError):
        return False
    if len(values) == 4:  # CMYK
        return all(v <= 0.02 for v in values)
    return bool(values) and all(v >= 0.98 for v in values)


def _lineweight(mm: float) -> float | None:
    if mm <= 0:
        return None
    return min(LINEWEIGHTS, key=lambda w: abs(w - mm))


# -- paths --------------------------------------------------------------------------


def _bezier(p0, p1, p2, p3) -> list[tuple[float, float]]:
    out = []
    for i in range(1, BEZIER_STEPS + 1):
        t = i / BEZIER_STEPS
        u = 1 - t
        out.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return out


@dataclass
class _Shape:
    points: list[tuple[float, float]]
    closed: bool
    curves: int  # Bezier pieces in it


def _shapes(curve) -> list[_Shape]:
    """Subpaths of a pdfminer curve with Bezier pieces flattened."""
    from pdfminer.layout import LTRect

    path = getattr(curve, "original_path", None)
    if not path:
        return [_bare_shape(curve, isinstance(curve, LTRect))]
    shapes: list[_Shape] = []
    current: _Shape | None = None
    for op, *args in path:
        if op == "m":
            current = _Shape([tuple(args[0])], False, 0)
            shapes.append(current)
            continue
        if current is None:
            continue
        last = current.points[-1]
        if op == "l":
            current.points.append(tuple(args[0]))
        elif op == "c":
            current.points += _bezier(last, args[0], args[1], args[2])
            current.curves += 1
        elif op == "v":
            current.points += _bezier(last, last, args[0], args[1])
            current.curves += 1
        elif op == "y":
            current.points += _bezier(last, args[0], args[1], args[1])
            current.curves += 1
        elif op == "h":
            current.closed = True
    return [s for s in shapes if len(s.points) >= 2]


def _bare_shape(curve, rectangle: bool) -> _Shape:
    """Older pdfminer (Ubuntu 24.04) keeps only the end points of a path. A closed
    path through the four quarter points of its box is taken as a circle."""
    pts = [tuple(p) for p in curve.pts]
    closed = rectangle or (len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-6)
    ring = pts[:-1] if len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-6 else pts
    if not rectangle and len(ring) == 4:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        r = (max(xs) - min(xs)) / 2
        quarters = {(round(cx + r, 3), round(cy, 3)), (round(cx - r, 3), round(cy, 3))}
        quarters |= {(round(cx, 3), round(cy + r, 3)), (round(cx, 3), round(cy - r, 3))}
        if r > 0 and {(round(x, 3), round(y, 3)) for x, y in ring} == quarters:
            circle = [
                (cx + r * math.cos(t * math.pi / 16), cy + r * math.sin(t * math.pi / 16))
                for t in range(33)
            ]
            return _Shape(circle, True, 4)
    return _Shape(pts, closed, 0)


def _circle(shape: _Shape) -> tuple[tuple[float, float], float] | None:
    """Centre and radius if the shape is a circle drawn with Bezier arcs."""
    if shape.curves < 4:
        return None
    pts = shape.points
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    radii = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
    r = sum(radii) / len(radii)
    closed = shape.closed or math.dist(pts[0], pts[-1]) < 0.02 * r + 1e-6
    if r <= 0 or not closed or max(abs(x - r) for x in radii) > 0.03 * r:
        return None
    return (cx, cy), r


def _inside(p, box) -> bool:
    return box[0] - 1e-6 <= p[0] <= box[2] + 1e-6 and box[1] - 1e-6 <= p[1] <= box[3] + 1e-6


def _clip(a, b, box):
    """Liang-Barsky: the part of segment a-b inside the box, or None."""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in (
        (-dx, a[0] - box[0]),
        (dx, box[2] - a[0]),
        (-dy, a[1] - box[1]),
        (dy, box[3] - a[1]),
    ):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def _clipped(shape: _Shape, box, to_mm, weight) -> list[Entity]:
    style = {"lineweight": weight}
    circle = _circle(shape)
    if circle is not None:
        (cx, cy), r = circle
        if _inside((cx, cy), box):
            return [Circle(id=new_id(), center=to_mm(cx, cy), radius=r * _scale(to_mm), **style)]
        return []
    pts = list(shape.points)
    if shape.closed and pts[0] != pts[-1]:
        pts.append(pts[0])
    if all(_inside(p, box) for p in pts):
        rect = _rectangle(pts)
        if rect is not None:
            a, b = rect
            return [Rectangle(id=new_id(), p1=to_mm(*a), p2=to_mm(*b), **style)]
        return [_entity([to_mm(*p) for p in pts], style)]
    # Cut at the region: consecutive pieces inside form one entity each.
    out: list[Entity] = []
    run: list[Point] = []
    for a, b in zip(pts, pts[1:], strict=False):
        part = _clip(a, b, box)
        if part is None:
            if len(run) >= 2:
                out.append(_entity(run, style))
            run = []
            continue
        start, end = to_mm(*part[0]), to_mm(*part[1])
        if run and math.dist((run[-1].x, run[-1].y), (start.x, start.y)) < 1e-6:
            run.append(end)
        else:
            if len(run) >= 2:
                out.append(_entity(run, style))
            run = [start, end]
    if len(run) >= 2:
        out.append(_entity(run, style))
    return out


def _scale(to_mm) -> float:
    a, b = to_mm(0, 0), to_mm(1, 0)
    return b.x - a.x


def _rectangle(pts) -> tuple | None:
    """Corners of a closed axis-parallel four-sided path."""
    if len(pts) != 5 or pts[0] != pts[-1]:
        return None
    for a, b in zip(pts, pts[1:], strict=False):
        if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
            return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if max(xs) - min(xs) < 1e-6 or max(ys) - min(ys) < 1e-6:
        return None
    return (min(xs), max(ys)), (max(xs), min(ys))


def _entity(points: list[Point], style) -> Entity:
    unique = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    if len(unique) == 2:
        return Line(id=new_id(), p1=unique[0], p2=unique[1], **style)
    closed = len(unique) > 3 and unique[0] == unique[-1]
    return Polyline(
        id=new_id(),
        points=tuple(unique[:-1] if closed else unique),
        closed=closed,
        **style,
    )


# -- texts --------------------------------------------------------------------------


def _angle(char) -> float:
    a, b = char.matrix[0], char.matrix[1]
    return math.degrees(math.atan2(b, a)) % 360


def _size(char, ux: float, uy: float) -> float:
    """Font size: the character box across the baseline (pdfminer's own size is the
    box height, wrong for turned text)."""
    x0, y0, x1, y1 = char.bbox
    values = [-x * uy + y * ux for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    return max(values) - min(values)


@dataclass
class _Glyph:
    char: object
    text: str
    x: float
    y: float
    ux: float
    uy: float
    angle: float
    size: float
    end: tuple[float, float]  # where the next character of the string starts


def _texts(chars, box, to_mm, k: float) -> list[Entity]:
    """Characters joined into texts: neighbours in the file where the next character
    starts where the previous one ends (a small gap is a space). Some programs write
    turned texts backwards, so the order in the file may run either way."""
    glyphs = []
    for c in chars:
        angle = _angle(c)
        ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        a, b = c.matrix[0], c.matrix[1]
        x, y = c.matrix[4], c.matrix[5]
        glyphs.append(
            _Glyph(
                c,
                c.get_text(),
                x,
                y,
                ux,
                uy,
                angle,
                _size(c, ux, uy),
                (x + c.adv * a, y + c.adv * b),
            )
        )
    cell = 20.0
    grid: dict[tuple[int, int], list[int]] = {}
    for i, g in enumerate(glyphs):
        grid.setdefault((int(g.x // cell), int(g.y // cell)), []).append(i)
    successor: dict[int, tuple[int, bool]] = {}
    taken: set[int] = set()
    for i, g in enumerate(glyphs):
        best = None
        cx, cy = int(g.end[0] // cell), int(g.end[1] // cell)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for j in grid.get((gx, gy), []):
                    h = glyphs[j]
                    # Neighbours in the file, in either direction.
                    if abs(j - i) != 1 or abs((h.angle - g.angle + 180) % 360 - 180) > 1.0:
                        continue
                    if abs(h.size - g.size) > 0.1 * g.size:
                        continue
                    dx, dy = h.x - g.end[0], h.y - g.end[1]
                    along = dx * g.ux + dy * g.uy
                    across = abs(-dx * g.uy + dy * g.ux)
                    if across > 0.2 * g.size or not -0.2 * g.size <= along <= 0.6 * g.size:
                        continue
                    if best is None or abs(along) < abs(best[1]):
                        best = (j, along)
        if best is not None and best[0] not in taken:
            successor[i] = (best[0], best[1] > 0.2 * g.size)
            taken.add(best[0])
    out: list[Entity] = []
    seen: set[int] = set()
    for i in range(len(glyphs)):
        if i in taken or i in seen:
            continue
        chain, spaces = [i], [False]
        while chain[-1] in successor and successor[chain[-1]][0] not in seen:
            j, gap = successor[chain[-1]]
            if j in chain:
                break
            chain.append(j)
            spaces.append(gap)
        seen.update(chain)
        text = "".join(
            (" " if gap else "") + glyphs[j].text for j, gap in zip(chain, spaces, strict=True)
        )
        lead = len(text) - len(text.lstrip())
        text = text.strip()
        if not text:
            continue
        first = glyphs[chain[min(lead, len(chain) - 1)]]
        if _inside((first.x, first.y), box):
            out.append(
                Text(
                    id=new_id(),
                    position=to_mm(first.x, first.y),
                    text=" ".join(text.split()),
                    height=round(first.size * CAP_HEIGHT * k, 2),
                    rotation=round(first.angle, 2) % 360,
                )
            )
    return out
