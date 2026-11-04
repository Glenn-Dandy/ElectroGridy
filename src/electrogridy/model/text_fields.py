"""The field a text sits in: the nearest edges left, right, above and below a point,
as in a table or a title block. Pure Python."""

from collections.abc import Iterable

from electrogridy.model.entities import Entity, Line, Polyline, Rectangle
from electrogridy.model.geometry import Point
from electrogridy.model.wires import EPS, segments

Segment = tuple[Point, Point]


def edges(entities: Iterable[Entity]) -> list[Segment]:
    """Straight edges of lines, polylines and rectangles (wires do not make fields)."""
    out: list[Segment] = []
    for e in entities:
        if isinstance(e, Line):
            out.append((e.p1, e.p2))
        elif isinstance(e, Polyline):
            out += segments(e.points)
            if e.closed and len(e.points) > 2:
                out.append((e.points[-1], e.points[0]))
        elif isinstance(e, Rectangle):
            a, c = e.p1, e.p2
            b, d = Point(c.x, a.y), Point(a.x, c.y)
            out += [(a, b), (b, c), (c, d), (d, a)]
    return out


def field_around(p: Point, entities: Iterable[Entity]) -> tuple[Point, Point] | None:
    """Top left and bottom right corner of the smallest box of horizontal and vertical
    edges around ``p``; None if it is open on a side."""
    left = right = top = bottom = None
    for a, b in edges(entities):
        if abs(a.x - b.x) <= EPS and min(a.y, b.y) - EPS <= p.y <= max(a.y, b.y) + EPS:
            x = a.x
            if x < p.x - EPS and (left is None or x > left):
                left = x
            elif x > p.x + EPS and (right is None or x < right):
                right = x
        elif abs(a.y - b.y) <= EPS and min(a.x, b.x) - EPS <= p.x <= max(a.x, b.x) + EPS:
            y = a.y
            if y < p.y - EPS and (top is None or y > top):
                top = y
            elif y > p.y + EPS and (bottom is None or y < bottom):
                bottom = y
    if None in (left, right, top, bottom):
        return None
    return Point(left, top), Point(right, bottom)


def field_center(p: Point, entities: Iterable[Entity]) -> Point | None:
    box = field_around(p, entities)
    if box is None:
        return None
    a, b = box
    return Point((a.x + b.x) / 2, (a.y + b.y) / 2)
