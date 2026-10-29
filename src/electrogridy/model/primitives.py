"""Decomposition of entities into segments and arcs for snapping and intersections."""

import math
from dataclasses import dataclass

from electrogridy.model.entities import (
    Arc,
    Busbar,
    Circle,
    Entity,
    Line,
    Polyline,
    RasterImage,
    Rectangle,
    Viewport,
    Wire,
)
from electrogridy.model.geometry import Point, angle_deg, midpoint, point_at_angle

EPS = 1e-9


@dataclass(frozen=True)
class Segment:
    a: Point
    b: Point


@dataclass(frozen=True)
class ArcPrim:
    """Arc or full circle (sweep 360)."""

    center: Point
    radius: float
    start: float
    sweep: float

    def contains_angle(self, angle: float) -> bool:
        if self.sweep >= 360:
            return True
        return (angle - self.start) % 360 <= self.sweep + 1e-7


Primitive = Segment | ArcPrim


def rect_corners(r: Rectangle | Viewport | RasterImage) -> list[Point]:
    return [r.p1, Point(r.p2.x, r.p1.y), r.p2, Point(r.p1.x, r.p2.y)]


def primitives(e: Entity) -> list[Primitive]:
    match e:
        case Line() | Busbar():
            return [Segment(e.p1, e.p2)]
        case Wire():
            return [Segment(a, b) for a, b in zip(e.points, e.points[1:], strict=False)]
        case Polyline():
            pts = list(e.points)
            if e.closed:
                pts.append(pts[0])
            return [Segment(a, b) for a, b in zip(pts, pts[1:], strict=False)]
        case Rectangle() | Viewport():
            c = rect_corners(e)
            return [Segment(c[i], c[(i + 1) % 4]) for i in range(4)]
        case Circle():
            return [ArcPrim(e.center, e.radius, 0.0, 360.0)]
        case Arc():
            return [ArcPrim(e.center, e.radius, e.start_angle, e.sweep)]
    return []


def arc_endpoints(a: Arc) -> tuple[Point, Point]:
    return point_at_angle(a.center, a.radius, a.start_angle), point_at_angle(
        a.center, a.radius, a.end_angle
    )


def arc_midpoint(a: Arc) -> Point:
    return point_at_angle(a.center, a.radius, a.start_angle + a.sweep / 2)


# -- intersections ----------------------------------------------------------


def _seg_seg(s: Segment, t: Segment) -> list[Point]:
    d1x, d1y = s.b.x - s.a.x, s.b.y - s.a.y
    d2x, d2y = t.b.x - t.a.x, t.b.y - t.a.y
    den = d1x * d2y - d1y * d2x
    if abs(den) < EPS:
        return []
    ex, ey = t.a.x - s.a.x, t.a.y - s.a.y
    u = (ex * d2y - ey * d2x) / den
    v = (ex * d1y - ey * d1x) / den
    if -EPS <= u <= 1 + EPS and -EPS <= v <= 1 + EPS:
        return [Point(s.a.x + u * d1x, s.a.y + u * d1y)]
    return []


def _seg_arc(s: Segment, c: ArcPrim) -> list[Point]:
    dx, dy = s.b.x - s.a.x, s.b.y - s.a.y
    fx, fy = s.a.x - c.center.x, s.a.y - c.center.y
    a = dx * dx + dy * dy
    if a < EPS:
        return []
    b = 2 * (fx * dx + fy * dy)
    cc = fx * fx + fy * fy - c.radius * c.radius
    disc = b * b - 4 * a * cc
    if disc < -EPS:
        return []
    root = math.sqrt(max(disc, 0.0))
    ts = {(-b - root) / (2 * a), (-b + root) / (2 * a)}
    out = []
    for t in sorted(ts):
        if -EPS <= t <= 1 + EPS:
            p = Point(s.a.x + t * dx, s.a.y + t * dy)
            if c.contains_angle(angle_deg(c.center, p)):
                out.append(p)
    return out


def _arc_arc(c1: ArcPrim, c2: ArcPrim) -> list[Point]:
    dx, dy = c2.center.x - c1.center.x, c2.center.y - c1.center.y
    d = math.hypot(dx, dy)
    if d < EPS or d > c1.radius + c2.radius + EPS or d < abs(c1.radius - c2.radius) - EPS:
        return []
    a = (c1.radius**2 - c2.radius**2 + d * d) / (2 * d)
    h = math.sqrt(max(c1.radius**2 - a * a, 0.0))
    mx, my = c1.center.x + a * dx / d, c1.center.y + a * dy / d
    candidates = {(mx + h * dy / d, my - h * dx / d), (mx - h * dy / d, my + h * dx / d)}
    out = []
    for x, y in sorted(candidates):
        p = Point(x, y)
        if c1.contains_angle(angle_deg(c1.center, p)) and c2.contains_angle(
            angle_deg(c2.center, p)
        ):
            out.append(p)
    return out


def intersect(p: Primitive, q: Primitive) -> list[Point]:
    if isinstance(p, Segment) and isinstance(q, Segment):
        return _seg_seg(p, q)
    if isinstance(p, Segment):
        return _seg_arc(p, q)
    if isinstance(q, Segment):
        return _seg_arc(q, p)
    return _arc_arc(p, q)


def segment_midpoint(s: Segment) -> Point:
    return midpoint(s.a, s.b)
