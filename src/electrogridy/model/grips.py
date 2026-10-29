"""Grip points of entities and how dragging a grip changes the entity."""

import math
from dataclasses import replace

from electrogridy.model.entities import (
    Arc,
    AttributeDefinition,
    BlockReference,
    Busbar,
    CableMark,
    Circle,
    ConnectionPoint,
    Dimension,
    Entity,
    InterruptionPoint,
    JunctionMark,
    Line,
    Polyline,
    RasterImage,
    Rectangle,
    Text,
    Viewport,
    Wire,
)
from electrogridy.model.geometry import Point, angle_deg
from electrogridy.model.primitives import arc_endpoints, rect_corners


def grip_points(e: Entity) -> list[Point]:
    match e:
        case Line() | Busbar() | CableMark():
            return [e.p1, e.p2]
        case Wire():
            return [p for _, p in _wire_grips(e)]
        case Dimension():
            extra = [e.vertex] if e.vertex is not None else []
            return [e.p1, e.p2, e.position, *extra]
        case BlockReference():
            return [e.insert]
        case AttributeDefinition() | ConnectionPoint() | JunctionMark() | InterruptionPoint():
            return [e.position]
        case Polyline() | Rectangle():
            return [p for _, p in _outline_grips(e)]
        case Viewport() | RasterImage():
            return rect_corners(e)
        case Circle():
            return [e.center]
        case Arc():
            return [*arc_endpoints(e), e.center]
        case Text():
            return [e.position]
    return []


def grip_kinds(e: Entity) -> list[str]:
    """How each grip of ``grip_points`` is drawn: "point", "segment" or "label"."""
    if isinstance(e, Wire):
        return ["point" if kind == "end" else kind for (kind, _), _ in _wire_grips(e)]
    if isinstance(e, Polyline | Rectangle):
        return [kind for (kind, _), _ in _outline_grips(e)]
    return ["point"] * len(grip_points(e))


def _outline_grips(e: Polyline | Rectangle) -> list[tuple[tuple[str, int], Point]]:
    """Grips of a polyline or rectangle: the corners, then the middle of every side,
    which shifts that side parallel."""
    corners = list(e.points) if isinstance(e, Polyline) else rect_corners(e)
    grips = [(("point", i), p) for i, p in enumerate(corners)]
    closed = isinstance(e, Rectangle) or (e.closed and len(corners) > 2)
    for i, (a, b) in enumerate(_sides(corners, closed)):
        if a != b:
            grips.append((("segment", i), Point((a.x + b.x) / 2, (a.y + b.y) / 2)))
    return grips


def _sides(corners: list[Point], closed: bool) -> list[tuple[Point, Point]]:
    ends = corners[1:] + corners[:1] if closed else corners[1:]
    return list(zip(corners, ends, strict=False))


def _shift_side(e: Polyline | Rectangle, side: int, p: Point) -> Entity | None:
    """Side ``side`` moved across its direction so that it passes through ``p``; the
    neighbouring sides stretch."""
    if isinstance(e, Rectangle):
        # Sides: top (p1.y), right (p2.x), bottom (p2.y), left (p1.x).
        field, axis = (("p1", "y"), ("p2", "x"), ("p2", "y"), ("p1", "x"))[side]
        corner = getattr(e, field)
        new = replace(e, **{field: replace(corner, **{axis: getattr(p, axis)})})
        return new if new.p1.x != new.p2.x and new.p1.y != new.p2.y else None
    pts = list(e.points)
    j = (side + 1) % len(pts)
    a, b = pts[side], pts[j]
    length = math.hypot(b.x - a.x, b.y - a.y)
    nx, ny = -(b.y - a.y) / length, (b.x - a.x) / length
    d = (p.x - a.x) * nx + (p.y - a.y) * ny
    pts[side], pts[j] = a.translated(d * nx, d * ny), b.translated(d * nx, d * ny)
    return replace(e, points=tuple(pts))


def _wire_grips(w: Wire) -> list[tuple[tuple[str, int], Point]]:
    """Grips of a wire: both ends, the label point (if labelled), the segment middles."""
    from electrogridy.model.wires import label_anchor, segment_grips

    if len(w.points) < 2:
        return [(("end", 0), p) for p in w.points]
    grips = [(("end", 0), w.points[0]), (("end", -1), w.points[-1])]
    label = label_anchor(w)[0] if w.label else None
    if label is not None:
        grips.append((("label", 0), label))
    grips += [(("segment", i), p) for i, p in segment_grips(w, label)]
    return grips


def move_grip(e: Entity, index: int, p: Point) -> Entity | None:
    """Entity with grip ``index`` moved to ``p``, or None if the result is degenerate."""
    match e:
        case Line() | Busbar():
            new = replace(e, p1=p) if index == 0 else replace(e, p2=p)
            return new if new.p1 != new.p2 else None
        case CableMark():
            # Stays across the conductors: only along its own direction.
            other = e.p2 if index == 0 else e.p1
            horizontal = abs(e.p2.x - e.p1.x) >= abs(e.p2.y - e.p1.y)
            q = Point(p.x, other.y) if horizontal else Point(other.x, p.y)
            new = replace(e, p1=q) if index == 0 else replace(e, p2=q)
            return new if new.p1 != new.p2 else None
        case Wire():
            from electrogridy.model.wires import drag_end, project_on_path

            kind, data = _wire_grips(e)[index][0]
            if kind == "label":
                at = round(project_on_path(e.points, p), 3)
                return replace(e, label_pos="free", label_at=at)
            if kind == "segment":
                from electrogridy.model.wires import move_segment

                new = move_segment(e, data, p)
                return new if len(new.points) >= 2 else None
            new = drag_end(e, 0 if index == 0 else -1, p)
            return new if len(new.points) >= 2 else None
        case Dimension():
            # The measured points, or (third grip) the position of the dimension line.
            field = ("p1", "p2", "position", "vertex")[index]
            return replace(e, **{field: p})
        case Polyline() | Rectangle():
            kind, i = _outline_grips(e)[index][0]
            if kind == "segment":
                return _shift_side(e, i, p)
            if isinstance(e, Polyline):
                pts = list(e.points)
                pts[i] = p
                return replace(e, points=tuple(pts))
            opposite = rect_corners(e)[(i + 2) % 4]
            if p.x == opposite.x or p.y == opposite.y:
                return None
            return replace(e, p1=opposite, p2=p)
        case Viewport() | RasterImage():
            opposite = rect_corners(e)[(index + 2) % 4]
            if p.x == opposite.x or p.y == opposite.y:
                return None
            return replace(e, p1=opposite, p2=p)
        case Arc():
            if index == 2:
                return e.translated(p.x - e.center.x, p.y - e.center.y)
            if p == e.center:
                return None
            a = angle_deg(e.center, p)
            new = replace(e, start_angle=a) if index == 0 else replace(e, end_angle=a)
            return new if abs(new.end_angle - new.start_angle) > 1e-9 else None
    # Circle, Text, references, attributes and connections: the grip moves the entity.
    ref = grip_points(e)[index]
    return e.translated(p.x - ref.x, p.y - ref.y)
