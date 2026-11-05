"""Lines and texts of a PDF page drawn by a CAD program, as drawing entities.

Uses pdfminer (python3-pdfminer). Coordinates come in points on the page as it is
shown (pdfminer applies the page rotation), y up; the result is in millimetres with
the top left corner of the chosen region at (0, 0) and y down. Curves are flattened,
four arcs around one centre (or a closed polygon of many points on a circle) become a
circle, closed axis-parallel four-sided paths a rectangle. Lines leaving the region
are cut at its edge; texts are kept when they start inside it. Characters are joined
into texts in drawing order.

Some programs print dashed lines as one filled area per dash, and arrow heads and dots
as filled areas without an outline. A thin straight filled strip becomes the line it
draws, a row of them with gaps one dashed (or, with dots between the dashes,
dash-dotted) line; any other filled area a filled shape with a hair outline. Pale
fills (backgrounds, highlights) are left out, like white strokes.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from electrogridy.model.entities import Circle, Entity, Line, Polyline, Rectangle, Text, new_id
from electrogridy.model.geometry import Point

MM_PER_PT = 25.4 / 72
CAP_HEIGHT = 0.7  # capital height as a share of the font size
LINEWEIGHTS = (0.18, 0.25, 0.35, 0.5, 0.7, 1.0)
BEZIER_STEPS = 8
MIN_VECTOR_OBJECTS = 3  # fewer strokes: the page is a scan (perhaps with OCR text)
AREA_OUTLINE = 0.05  # mm: outline of an area that had none; closes seams between areas
HAIR_STROKE = 0.1 / MM_PER_PT  # pt: a thinner outline around a filled area counts as none
MAX_STRIP = 1.2 / MM_PER_PT  # pt: a filled straight strip up to this wide draws a line
MAX_SOLID_STRIP = 0.5 / MM_PER_PT  # pt: a wider strip on its own stays an area (flat ends)
MAX_DASH = 15.0 / MM_PER_PT  # pt: longer strips are no dashes, they join only when touching
MAX_DASH_GAP = 4.0 / MM_PER_PT  # pt
TOUCH = 0.1  # pt: strips closer than this along their line are one piece
SAME_LINE = 0.2  # pt: strips this close across their direction lie on one line
SAME_ANGLE = 0.01  # rad


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
    """The layout of one page. Older pdfminer (Ubuntu 24.04, so also the Snap) does not
    keep the dash pattern of a path; the reader here notes it on each new curve."""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    class Reader(PDFPageAggregator):
        def paint_path(self, gstate, stroke, fill, evenodd, path):
            before = len(self.cur_item._objs)
            super().paint_path(gstate, stroke, fill, evenodd, path)
            for o in self.cur_item._objs[before:]:
                if not hasattr(o, "dashing_style"):
                    o.dashing_style = gstate.dash

    manager = PDFResourceManager()
    reader = Reader(manager, laparams=None)
    interpreter = PDFPageInterpreter(manager, reader)
    with open(path, "rb") as f:
        for pdf_page in PDFPage.get_pages(f, {page}):
            interpreter.process_page(pdf_page)
            return reader.get_result()
    raise IndexError(f"page {page} not in {path}")


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
    strips: list[_Strip] = []
    for o in _walk(layout):
        if isinstance(o, LTChar):
            chars.append(o)
            continue
        if not isinstance(o, LTCurve):
            continue
        fill = bool(o.fill) and not _pale(o.non_stroking_color)
        stroke = bool(o.stroke) and not _white(o.stroking_color)
        if stroke and fill and o.linewidth < HAIR_STROKE:
            stroke = False  # an area with a hair outline: the area alone
        if stroke:
            style = {"lineweight": _lineweight(o.linewidth * k)}
            linetype = _linetype(getattr(o, "dashing_style", None))
            if linetype:
                style["linetype"] = linetype
            for shape in _shapes(o):
                out += _clipped(shape, box, to_mm, style, fill)
        elif fill:
            for shape in _shapes(o):
                strip = _strip(shape)
                if strip is None:
                    out += _clipped(shape, box, to_mm, {"lineweight": AREA_OUTLINE}, True)
                else:
                    strip.order = len(out)
                    strips.append(strip)
    out = _inserted(out, _strip_lines(strips, box, to_mm, k))
    out += _texts(chars, box, to_mm, k)
    return out


def _inserted(out: list[Entity], extra: list[tuple[int, Entity]]) -> list[Entity]:
    """``out`` with each extra entity put before the entity at its index (drawing
    order: lines made of strips come where their first strip was)."""
    extra = sorted(extra, key=lambda item: item[0])
    merged: list[Entity] = []
    j = 0
    for i, e in enumerate(out):
        while j < len(extra) and extra[j][0] <= i:
            merged.append(extra[j][1])
            j += 1
        merged.append(e)
    merged += [e for _, e in extra[j:]]
    return merged


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


def _rgb(color) -> tuple[float, float, float] | None:
    values = color if isinstance(color, list | tuple) else [color]
    try:
        values = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    if len(values) == 1:
        return values[0], values[0], values[0]
    if len(values) == 3:
        return values[0], values[1], values[2]
    if len(values) == 4:  # CMYK
        c, m, y, black = values
        return (1 - c) * (1 - black), (1 - m) * (1 - black), (1 - y) * (1 - black)
    return None


def _pale(color) -> bool:
    """Light and hardly coloured (white, light grey, pastel): a background or a
    highlight, which would cover the drawing when filled in the layer colour. So is a
    pattern instead of a colour. None is the default black."""
    if color is None:
        return False
    rgb = _rgb(color)
    if rgb is None:
        return True
    high, low = max(rgb), min(rgb)
    return high >= 0.7 and (high - low) <= 0.45 * high


def _linetype(dashing) -> str | None:
    """Line type of a PDF dash pattern (lengths on, off, on, off …): dashes of one
    length are dashed, long and short dashes dash-dotted."""
    if not dashing:
        return None
    try:
        values = [float(v) for v in dashing[0]]
    except (TypeError, ValueError, IndexError):
        return None
    if len(values) % 2:
        values *= 2  # an odd pattern repeats with on and off swapped
    if not values or max(values) <= 0:
        return None
    ons = values[0::2]
    return "dashdot" if min(ons) < 0.5 * max(ons) else "dashed"


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
    ring = [p for i, p in enumerate(pts) if i == 0 or math.dist(p, pts[i - 1]) >= 1e-6]
    if len(ring) > 1 and math.dist(ring[0], ring[-1]) < 1e-6:
        ring.pop()
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


def _circle(shape: _Shape, filled: bool = False) -> tuple[tuple[float, float], float] | None:
    """Centre and radius if the shape is a circle drawn with Bezier arcs. A filled one
    may start at its centre (a pie from the centre all the way round)."""
    if shape.curves < 4:
        return None
    pts = shape.points
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    rough = (max(xs) - min(xs) + max(ys) - min(ys)) / 4
    if filled:
        pts = [p for p in pts if math.hypot(p[0] - cx, p[1] - cy) > 0.5 * rough]
        if len(pts) < 4:
            return None
    radii = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
    r = sum(radii) / len(radii)
    closed = filled or shape.closed or math.dist(pts[0], pts[-1]) < 0.02 * r + 1e-6
    if r <= 0 or not closed or max(abs(x - r) for x in radii) > 0.03 * r:
        return None
    return (cx, cy), r


def _ring(points) -> list[tuple[float, float]]:
    """The corners of a closed path: repeated points and the closing point left out."""
    ring = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 1e-6]
    while len(ring) > 1 and math.dist(ring[0], ring[-1]) <= 1e-6:
        ring.pop()
    return ring


def _round(shape: _Shape, filled: bool = False) -> tuple[tuple[float, float], float] | None:
    """Centre and radius if the shape is a closed polygon of many points on a circle
    (how some programs print a dot, sometimes as steps on the printer's raster)."""
    closed = filled or shape.closed or math.dist(shape.points[0], shape.points[-1]) < 1e-6
    pts = _ring(shape.points)
    if not closed or len(pts) < 12:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if abs(w - h) > 0.05 * max(w, h):
        return None
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    radii = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
    r = sum(radii) / len(radii)
    if r <= 0 or max(abs(x - r) for x in radii) > max(0.04 * r, 0.12):
        return None
    angles = sorted(math.atan2(p[1] - cy, p[0] - cx) for p in pts)
    gaps = [b - a for a, b in zip(angles, angles[1:], strict=False)]
    gaps.append(angles[0] + 2 * math.pi - angles[-1])
    return ((cx, cy), r) if max(gaps) <= math.radians(50) else None


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


def _clipped(shape: _Shape, box, to_mm, style, filled: bool = False) -> list[Entity]:
    """Entities for ``shape`` inside ``box``; ``filled``: the shape is filled (a filled
    path counts as closed)."""
    circle = _circle(shape, filled) or _round(shape, filled)
    if circle is not None:
        (cx, cy), r = circle
        if _inside((cx, cy), box):
            return [
                Circle(
                    id=new_id(),
                    center=to_mm(cx, cy),
                    radius=r * _scale(to_mm),
                    filled=filled,
                    **style,
                )
            ]
        return []
    pts = list(shape.points)
    if (shape.closed or filled) and pts[0] != pts[-1]:
        pts.append(pts[0])
    if filled and not all(_inside(p, box) for p in pts):
        part = _clip_polygon(_ring(pts), box)
        if len(part) < 3:
            return []
        pts = [*part, part[0]]
    if all(_inside(p, box) for p in pts):
        rect = _rectangle(pts)
        if rect is not None:
            a, b = rect
            return [Rectangle(id=new_id(), p1=to_mm(*a), p2=to_mm(*b), filled=filled, **style)]
        return [_entity([to_mm(*p) for p in pts], style, filled)]
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


def _clip_polygon(pts, box) -> list[tuple[float, float]]:
    """Sutherland-Hodgman: the part of a closed polygon inside the box."""

    def cut(points, inside, crossing):
        out = []
        for i, b in enumerate(points):
            a = points[i - 1]
            if inside(b):
                if not inside(a):
                    out.append(crossing(a, b))
                out.append(b)
            elif inside(a):
                out.append(crossing(a, b))
        return out

    def at_x(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def at_y(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    x0, y0, x1, y1 = box
    for inside, crossing in (
        (lambda p: p[0] >= x0, at_x(x0)),
        (lambda p: p[0] <= x1, at_x(x1)),
        (lambda p: p[1] >= y0, at_y(y0)),
        (lambda p: p[1] <= y1, at_y(y1)),
    ):
        pts = cut(pts, inside, crossing)
        if not pts:
            break
    return pts


def _entity(points: list[Point], style, filled: bool = False) -> Entity:
    unique = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    if len(unique) == 2:
        return Line(id=new_id(), p1=unique[0], p2=unique[1], **style)
    closed = len(unique) > 3 and unique[0] == unique[-1]
    return Polyline(
        id=new_id(),
        points=tuple(unique[:-1] if closed else unique),
        closed=closed,
        filled=filled and closed,
        **style,
    )


# -- filled strips (dashes printed as areas) ---------------------------------------


@dataclass
class _Strip:
    """A thin straight filled area: the stroke it draws, in points. ``a`` and ``b``
    are the ends of its full width part (round or pointed caps left out)."""

    a: tuple[float, float]
    b: tuple[float, float]
    width: float
    dot: bool  # about as long as wide: its direction comes from its neighbours
    shape: _Shape
    order: int = 0


def _signed_area(pts) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, [*pts[1:], pts[0]], strict=True)) / 2


def _hull(pts) -> list[tuple[float, float]]:
    """Convex hull (monotone chain), counter-clockwise."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(points):
        out: list[tuple[float, float]] = []
        for p in points:
            while len(out) >= 2:
                (ax, ay), (bx, by) = out[-2], out[-1]
                if (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax) > 1e-12:
                    break
                out.pop()
            out.append(p)
        return out[:-1]

    return half(pts) + half(pts[::-1])


def _strip(shape: _Shape) -> _Strip | None:
    """The stroke a filled shape draws, if it is a thin straight strip: its narrowest
    direction across (rotating calipers on the hull) is at most ``MAX_STRIP`` and it
    fills the box of that direction (a triangle or a disc does not)."""
    pts = _ring(shape.points)
    hull = _hull(pts)
    area = abs(_signed_area(pts)) if len(pts) >= 3 else 0.0
    if area <= 0 or len(hull) < 3:
        return None
    best = None
    for (x0, y0), (x1, y1) in zip(hull, [*hull[1:], hull[0]], strict=True):
        d = math.hypot(x1 - x0, y1 - y0)
        if d < 1e-9:
            continue
        ux, uy = (x1 - x0) / d, (y1 - y0) / d
        across = [(y - y0) * ux - (x - x0) * uy for x, y in hull]
        width = max(across) - min(across)
        if best is None or width < best[0]:
            best = (width, ux, uy)
    if best is None:
        return None
    width, ux, uy = best
    along = [x * ux + y * uy for x, y in pts]
    length = max(along) - min(along)
    if width > MAX_STRIP or area < 0.8 * length * width:
        return None
    nx, ny = -uy, ux
    across = [x * nx + y * ny for x, y in pts]
    mid = (max(across) + min(across)) / 2
    body = [t for t, c in zip(along, across, strict=True) if abs(c - mid) >= 0.35 * width]
    t0, t1 = min(body), max(body)
    return _Strip(
        (ux * t0 + nx * mid, uy * t0 + ny * mid),
        (ux * t1 + nx * mid, uy * t1 + ny * mid),
        width,
        length < 1.6 * width,
        shape,
    )


@dataclass
class _Run:
    """Strips on one line: dashes of one dashed line, or a single stroke."""

    a: tuple[float, float]
    b: tuple[float, float]
    width: float
    linetype: str | None
    order: int
    lone: _Strip | None = None  # a run of one strip


def _split(items: list, key, close) -> list[list]:
    """``items`` sorted by ``key`` and cut where neighbours are not ``close``."""
    items = sorted(items, key=key)
    groups: list[list] = []
    for item in items:
        if groups and close(key(groups[-1][-1]), key(item)):
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _runs(strips: list[_Strip]) -> list[_Run]:
    """Strips grouped into lines: same direction, same line across, similar width; dots
    join the line they sit on. Along a line, pieces up to ``MAX_DASH`` long with gaps up
    to 1.25 times the longer neighbour (at least 4 widths, at most ``MAX_DASH_GAP``) are
    dashes of one line, a gap far wider than the others parts two lines."""
    lines = [s for s in strips if not s.dot]
    dots = [s for s in strips if s.dot]

    def angle(s: _Strip) -> float:
        a = math.atan2(s.b[1] - s.a[1], s.b[0] - s.a[0]) % math.pi
        return a - math.pi if a > math.pi - SAME_ANGLE else a

    groups = []  # (direction, across, members)
    for same_angle in _split(lines, angle, lambda x, y: y - x <= SAME_ANGLE):
        theta = sum(angle(s) for s in same_angle) / len(same_angle)
        ux, uy = math.cos(theta), math.sin(theta)

        def across(s: _Strip, ux=ux, uy=uy) -> float:
            return -uy * (s.a[0] + s.b[0]) / 2 + ux * (s.a[1] + s.b[1]) / 2

        for line in _split(same_angle, across, lambda x, y: y - x <= SAME_LINE):
            for members in _split(line, lambda s: s.width, lambda x, y: y <= 1.35 * x):
                rho = sum(across(s) for s in members) / len(members)
                groups.append(((ux, uy), rho, members))

    def extent(s: _Strip, ux: float, uy: float) -> tuple[float, float]:
        along = [x * ux + y * uy for x, y in s.shape.points]
        return min(along), max(along)

    # Dots (of dash-dotted lines) go to the line through them.
    cell = 20.0
    grid: dict[tuple[int, int], list[int]] = {}
    spans = []
    for g, ((ux, uy), _, members) in enumerate(groups):
        along = [x * ux + y * uy for s in members for x, y in (s.a, s.b)]
        spans.append((min(along) - MAX_DASH_GAP, max(along) + MAX_DASH_GAP))
        xs = [x for s in members for x in (s.a[0], s.b[0])]
        ys = [y for s in members for y in (s.a[1], s.b[1])]
        pad = MAX_DASH_GAP
        for gx in range(int((min(xs) - pad) // cell), int((max(xs) + pad) // cell) + 1):
            for gy in range(int((min(ys) - pad) // cell), int((max(ys) + pad) // cell) + 1):
                grid.setdefault((gx, gy), []).append(g)
    lone = []
    for d in dots:
        cx, cy = (d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2
        best = None
        for g in grid.get((int(cx // cell), int(cy // cell)), []):
            (ux, uy), rho, members = groups[g]
            off = abs(-uy * cx + ux * cy - rho)
            ratio = members[0].width / d.width
            lo, hi = spans[g]
            if off > SAME_LINE + d.width / 2 or not 0.6 <= ratio <= 1.7:
                continue
            if lo <= cx * ux + cy * uy <= hi and (best is None or off < best[0]):
                best = (off, g)
        if best is None:
            lone.append(d)
        else:
            groups[best[1]][2].append(d)

    runs: list[_Run] = []
    for (ux, uy), rho, members in groups:
        width = sorted(s.width for s in members)[len(members) // 2]
        # Pieces along the line: overlapping or touching strips are one piece.
        pieces: list[list] = []  # [start, end, order, strips]
        for s in sorted(members, key=lambda s: extent(s, ux, uy)[0]):
            t0, t1 = (
                extent(s, ux, uy)
                if s.dot
                else sorted((s.a[0] * ux + s.a[1] * uy, s.b[0] * ux + s.b[1] * uy))
            )
            if pieces and t0 <= pieces[-1][1] + TOUCH:
                last = pieces[-1]
                last[1] = max(last[1], t1)
                last[2] = min(last[2], s.order)
                last[3].append(s)
            else:
                pieces.append([t0, t1, s.order, [s]])
        chains: list[list] = []
        for piece in pieces:
            if chains:
                prev = chains[-1][-1]
                gap = piece[0] - prev[1]
                longer = max(prev[1] - prev[0], piece[1] - piece[0])
                reach = min(MAX_DASH_GAP, max(1.25 * longer, 4 * width))
                if gap <= reach and longer <= MAX_DASH:
                    chains[-1].append(piece)
                    continue
            chains.append([piece])
        for chain in chains:
            for part in _parted(chain):
                runs.append(_run(part, (ux, uy), rho, width))
    for d in lone:
        runs.append(_Run(d.a, d.b, d.width, None, d.order, d))
    return runs


def _parted(chain: list[list]) -> list[list[list]]:
    """A chain of dashes cut at gaps far wider than the usual one (two dashed lines in
    a row, or a dashed line behind a symbol)."""
    gaps = [b[0] - a[1] for a, b in zip(chain, chain[1:], strict=False)]
    if len(gaps) < 3:
        return [chain]
    usual = sorted(gaps)[len(gaps) // 2]
    parts = [[chain[0]]]
    for piece, gap in zip(chain[1:], gaps, strict=True):
        if gap > 2.5 * usual + TOUCH:
            parts.append([piece])
        else:
            parts[-1].append(piece)
    return parts


def _run(chain: list[list], u, rho: float, width: float) -> _Run:
    (ux, uy), (nx, ny) = u, (-u[1], u[0])
    t0, t1 = chain[0][0], chain[-1][1]
    order = min(piece[2] for piece in chain)
    strips = [s for piece in chain for s in piece[3]]
    linetype = None
    if len(chain) > 1:
        lengths = [b - a for a, b, _, _ in chain]
        # The pattern cuts the dash at the end of the line short; which end that is
        # depends on the drawing direction.
        core = lengths
        if len(lengths) > 2:
            core = lengths[1:] if lengths[0] < lengths[-1] else lengths[:-1]
        linetype = "dashdot" if _dotted(core) else "dashed"
    return _Run(
        (ux * t0 + nx * rho, uy * t0 + ny * rho),
        (ux * t1 + nx * rho, uy * t1 + ny * rho),
        width,
        linetype,
        order,
        strips[0] if len(strips) == 1 else None,
    )


def _dotted(lengths: list[float]) -> bool:
    """Dashes and dots: the lengths fall into a short and a long group (at least 2.5
    times apart), the short ones at least a quarter of all. Overlapping dashes of two
    lines on top of each other give a few longer pieces, which do not count."""
    ordered = sorted(lengths)
    if len(ordered) < 2:
        return False
    ratio, cut = max(
        (b / a if a > 0 else math.inf, i + 1)
        for i, (a, b) in enumerate(zip(ordered, ordered[1:], strict=False))
    )
    return ratio >= 2.5 and cut >= 0.25 * len(ordered)


def _strip_lines(strips: list[_Strip], box, to_mm, k: float) -> list[tuple[int, Entity]]:
    """Lines drawn by filled strips, each with the drawing position of its first strip.
    A single dot or a single wide strip stays the filled area it is."""
    out: list[tuple[int, Entity]] = []
    for run in _runs(strips):
        if run.lone is not None and (run.lone.dot or run.width > MAX_SOLID_STRIP):
            shape = run.lone.shape
            entities = _clipped(shape, box, to_mm, {"lineweight": AREA_OUTLINE}, True)
        else:
            style: dict = {"lineweight": _lineweight(run.width * k)}
            if run.linetype:
                style["linetype"] = run.linetype
            entities = _clipped(_Shape([run.a, run.b], False, 0), box, to_mm, style)
        out += [(run.order, e) for e in entities]
    return out


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
