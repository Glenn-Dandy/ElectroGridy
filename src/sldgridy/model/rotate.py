"""Rotation by any angle. Pure Python.

Angles are degrees, counter-clockwise on screen (Y points down). Quarter turns use
the entities' own exact rotation. Other angles work for free geometry; rectangles
become closed polylines. Block references, wires, bus bars and viewports only turn
in quarter steps (they are kept axis-parallel), for them ``rotate_entity`` gives None.
"""

import math
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

EPS = 1e-9
QUARTER_ONLY = (BlockReference, Wire, Busbar, Viewport, RasterImage, CableMark)


def rotate_point(p: Point, center: Point, degrees: float) -> Point:
    a = math.radians(degrees)
    dx, dy = p.x - center.x, p.y - center.y
    x = center.x + dx * math.cos(a) + dy * math.sin(a)
    y = center.y - dx * math.sin(a) + dy * math.cos(a)
    return Point(round(x, 9), round(y, 9))


def quarter_turns(degrees: float) -> int | None:
    """Number of quarter turns if ``degrees`` is a multiple of 90, else None."""
    q = degrees / 90.0
    return round(q) % 4 if abs(q - round(q)) < 1e-9 else None


def rotate_entity(e: Entity, center: Point, degrees: float) -> Entity | None:
    """``e`` turned around ``center``; None if this kind cannot take that angle."""
    quarters = quarter_turns(degrees)
    if quarters is not None:
        return e.rotated(center, quarters) if quarters else e
    if isinstance(e, QUARTER_ONLY):
        return None

    def rot(p: Point) -> Point:
        return rotate_point(p, center, degrees)

    match e:
        case Line():
            return replace(e, p1=rot(e.p1), p2=rot(e.p2))
        case Polyline():
            return replace(e, points=tuple(rot(p) for p in e.points))
        case Rectangle():
            corners = (
                e.p1,
                Point(e.p2.x, e.p1.y),
                e.p2,
                Point(e.p1.x, e.p2.y),
            )
            return Polyline(
                id=e.id,
                layer=e.layer,
                color=e.color,
                lineweight=e.lineweight,
                linetype=e.linetype,
                points=tuple(rot(p) for p in corners),
                closed=True,
            )
        case Circle():
            return replace(e, center=rot(e.center))
        case Arc():
            return replace(
                e,
                center=rot(e.center),
                start_angle=(e.start_angle + degrees) % 360,
                end_angle=(e.end_angle + degrees) % 360,
            )
        case Text():
            return replace(e, position=rot(e.position), rotation=(e.rotation + degrees) % 360)
        case AttributeDefinition():
            return replace(e, position=rot(e.position), rotation=(e.rotation + degrees) % 360)
        case ConnectionPoint():
            return replace(e, position=rot(e.position), direction=(e.direction + degrees) % 360)
        case JunctionMark():
            return replace(e, position=rot(e.position))
        case InterruptionPoint():
            return replace(e, position=rot(e.position), direction=(e.direction + degrees) % 360)
        case Dimension() if e.orientation == "angular" and e.vertex is not None:
            return replace(
                e, p1=rot(e.p1), p2=rot(e.p2), position=rot(e.position), vertex=rot(e.vertex)
            )
        case Dimension():
            # Turned off the axes, a horizontal or vertical dimension measures along its
            # turned points: it becomes an aligned one.
            return replace(
                e,
                p1=rot(e.p1),
                p2=rot(e.p2),
                position=rot(e.position),
                orientation="aligned",
            )
    return None
