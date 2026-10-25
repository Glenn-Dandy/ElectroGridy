"""Grip points of entities and how dragging a grip changes the entity."""

from dataclasses import replace

from sldgridy.model.entities import (
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
from sldgridy.model.geometry import Point, angle_deg
from sldgridy.model.primitives import arc_endpoints, rect_corners


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
        case Polyline():
            return list(e.points)
        case Rectangle() | Viewport() | RasterImage():
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
    return ["point"] * len(grip_points(e))


def _wire_grips(w: Wire) -> list[tuple[tuple[str, int], Point]]:
    """Grips of a wire: both ends, the label point (if labelled), the segment middles."""
    from sldgridy.model.wires import label_anchor, segment_grips

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
            from sldgridy.model.wires import drag_end, project_on_path

            kind, data = _wire_grips(e)[index][0]
            if kind == "label":
                at = round(project_on_path(e.points, p), 3)
                return replace(e, label_pos="free", label_at=at)
            if kind == "segment":
                from sldgridy.model.wires import move_segment

                new = move_segment(e, data, p)
                return new if len(new.points) >= 2 else None
            new = drag_end(e, 0 if index == 0 else -1, p)
            return new if len(new.points) >= 2 else None
        case Dimension():
            # The measured points, or (third grip) the position of the dimension line.
            field = ("p1", "p2", "position", "vertex")[index]
            return replace(e, **{field: p})
        case Polyline():
            pts = list(e.points)
            pts[index] = p
            return replace(e, points=tuple(pts))
        case Rectangle() | Viewport() | RasterImage():
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
