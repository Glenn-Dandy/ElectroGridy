"""Cable shields: a long oval around the conductors of a cable, the long sides dash-dot,
with a connection point at either end for the wire to the shield terminal. Pure Python.
"""

from collections.abc import Iterable
from dataclasses import replace

from electrogridy.model.entities import (
    Arc,
    CableShield,
    ConnectionPoint,
    Entity,
    Line,
    Polyline,
    Wire,
)
from electrogridy.model.geometry import Point

RADIUS = 1.25  # mm, half the height of the oval
# The straight sides reach this far beyond the outer conductors; with the rounded ends
# the connection points lie 2.5 mm beyond them, in the grid.
OVERHANG = 1.25
SIDE_LINETYPE = "dashdot_short"
EPS = 1e-6  # as in model.wires, which imports this module


def fitted_shield(shield: CableShield, entities: Iterable[Entity]) -> CableShield:
    """Exactly ``OVERHANG`` beyond the outer conductors it crosses, wherever the clicks
    were: so the connection points come to lie in the grid."""
    found = conductors_crossed(shield, entities)
    if not found:
        return shield
    a = _span(shield)[0]
    if is_horizontal(shield):
        xs = [p.x for p in found]
        return replace(shield, p1=Point(min(xs) - OVERHANG, a.y), p2=Point(max(xs) + OVERHANG, a.y))
    ys = [p.y for p in found]
    return replace(shield, p1=Point(a.x, min(ys) - OVERHANG), p2=Point(a.x, max(ys) + OVERHANG))


def is_horizontal(shield: CableShield) -> bool:
    return abs(shield.p2.x - shield.p1.x) >= abs(shield.p2.y - shield.p1.y)


def _span(shield: CableShield) -> tuple[Point, Point]:
    """Both ends of the middle line, the left (upper) one first."""
    a, b = shield.p1, shield.p2
    key = (lambda p: p.x) if is_horizontal(shield) else (lambda p: p.y)
    return (a, b) if key(a) <= key(b) else (b, a)


def conductors_crossed(shield: CableShield, entities: Iterable[Entity]) -> list[Point]:
    """Where the middle line crosses wires or plain straight lines: an imported plan
    has its conductors as lines (Florian 2026-11-04)."""
    a, b = _span(shield)
    horizontal = is_horizontal(shield)
    found = []
    for e in entities:
        if isinstance(e, Wire | Polyline):
            edges = list(zip(e.points, e.points[1:], strict=False))
        elif isinstance(e, Line):
            edges = [(e.p1, e.p2)]
        else:
            continue
        for s, t in edges:
            if horizontal:
                across = abs(s.x - t.x) <= EPS and a.x - EPS <= s.x <= b.x + EPS
                if across and min(s.y, t.y) - EPS <= a.y <= max(s.y, t.y) + EPS:
                    found.append(Point(s.x, a.y))
            else:
                across = abs(s.y - t.y) <= EPS and a.y - EPS <= s.y <= b.y + EPS
                if across and min(s.x, t.x) - EPS <= a.x <= max(s.x, t.x) + EPS:
                    found.append(Point(a.x, s.y))
    return found


def shield_connections(shield: CableShield) -> list[ConnectionPoint]:
    """Both ends: "1" left (upper), "2" right (lower), pointing outwards."""
    a, b = _span(shield)
    r = RADIUS
    if is_horizontal(shield):
        ends = ((Point(a.x - r, a.y), 180.0), (Point(b.x + r, b.y), 0.0))
    else:
        ends = ((Point(a.x, a.y - r), 90.0), (Point(b.x, b.y + r), 270.0))
    return [
        ConnectionPoint(
            id=f"{shield.id}:c{i}", layer=shield.layer, name=str(i + 1), position=p, direction=d
        )
        for i, (p, d) in enumerate(ends)
    ]


def shield_geometry(shield: CableShield) -> list[Entity]:
    """Long sides and rounded ends. The connection points are not drawn, not even as
    helper markers (Florian 2026-11-04); they snap all the same."""
    a, b = _span(shield)
    r = RADIUS
    style = {"layer": shield.layer, "color": shield.color, "lineweight": shield.lineweight}
    side = {**style, "linetype": SIDE_LINETYPE}
    i = shield.id
    if is_horizontal(shield):
        y = a.y
        parts: list[Entity] = [
            Line(id=f"{i}:top", p1=Point(a.x, y - r), p2=Point(b.x, y - r), **side),
            Line(id=f"{i}:bottom", p1=Point(a.x, y + r), p2=Point(b.x, y + r), **side),
            # Angles count counter-clockwise on the screen, 90 is up.
            Arc(id=f"{i}:end1", center=a, radius=r, start_angle=90, end_angle=270, **style),
            Arc(id=f"{i}:end2", center=b, radius=r, start_angle=270, end_angle=90, **style),
        ]
    else:
        x = a.x
        parts = [
            Line(id=f"{i}:left", p1=Point(x - r, a.y), p2=Point(x - r, b.y), **side),
            Line(id=f"{i}:right", p1=Point(x + r, a.y), p2=Point(x + r, b.y), **side),
            Arc(id=f"{i}:end1", center=a, radius=r, start_angle=0, end_angle=180, **style),
            Arc(id=f"{i}:end2", center=b, radius=r, start_angle=180, end_angle=360, **style),
        ]
    return parts
