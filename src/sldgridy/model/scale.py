"""Uniform scaling around a base point. Pure Python.

Lengths, radii, text heights and dimension heights grow with the factor; block
references keep their definition and get a larger ``scale``. Angles stay.
"""

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
from sldgridy.model.geometry import Point


def scale_point(p: Point, center: Point, factor: float) -> Point:
    return Point(
        round(center.x + (p.x - center.x) * factor, 9),
        round(center.y + (p.y - center.y) * factor, 9),
    )


def scale_entity(e: Entity, center: Point, factor: float) -> Entity:
    """``e`` scaled by ``factor`` (> 0) around ``center``."""
    if factor <= 0:
        raise ValueError("scale factor must be positive")

    def s(p: Point) -> Point:
        return scale_point(p, center, factor)

    match e:
        case Line() | Busbar() | Rectangle() | RasterImage():
            return replace(e, p1=s(e.p1), p2=s(e.p2))
        case Viewport():
            # The frame on the sheet grows; what it shows of the model stays.
            return replace(e, p1=s(e.p1), p2=s(e.p2))
        case Polyline():
            return replace(e, points=tuple(s(p) for p in e.points))
        case CableMark():
            return replace(e, p1=s(e.p1), p2=s(e.p2), height=e.height * factor)
        case Wire():
            return replace(
                e,
                points=tuple(s(p) for p in e.points),
                label_height=e.label_height * factor,
                label_at=e.label_at * factor,
            )
        case Circle() | Arc():
            return replace(e, center=s(e.center), radius=e.radius * factor)
        case Text() | AttributeDefinition():
            return replace(e, position=s(e.position), height=e.height * factor)
        case ConnectionPoint() | JunctionMark():
            return replace(e, position=s(e.position))
        case InterruptionPoint():
            return replace(e, position=s(e.position), height=e.height * factor)
        case Dimension():
            return replace(
                e,
                p1=s(e.p1),
                p2=s(e.p2),
                position=s(e.position),
                vertex=s(e.vertex) if e.vertex is not None else None,
                height=e.height * factor,
            )
        case BlockReference():
            return replace(e, insert=s(e.insert), scale=e.scale * factor)
    return e
