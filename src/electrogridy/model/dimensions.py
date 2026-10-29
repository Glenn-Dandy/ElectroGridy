"""Geometry of linear dimensions: extension lines, dimension line, arrows and value.

Pure Python. Proportions follow DIN 406 in spirit: extension lines start a little
off the object and run a little past the dimension line, the value sits above the
dimension line and reads from below or from the right.
"""

import math

from electrogridy.model.entities import Arc, Dimension, Entity, Line, Text
from electrogridy.model.geometry import Point

GAP = 0.4  # × text height: space between object and extension line
OVERSHOOT = 0.8  # × text height: extension line past the dimension line
ARROW = 1.0  # × text height: arrow length
ARROW_ANGLE = 15.0  # degrees, half opening
TEXT_GAP = 0.4  # × text height: value above the dimension line
EPS = 1e-9


def _direction(d: Dimension) -> tuple[float, float] | None:
    if d.orientation == "horizontal":
        return 1.0, 0.0
    if d.orientation == "vertical":
        return 0.0, 1.0
    dx, dy = d.p2.x - d.p1.x, d.p2.y - d.p1.y
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > EPS else None


def measured(d: Dimension) -> float:
    """Length in mm, or for an angular dimension the angle in degrees."""
    if d.orientation == "angular":
        sector = angular_sector(d)
        return sector[1] if sector is not None else 0.0
    u = _direction(d)
    if u is None:
        return 0.0
    return abs((d.p2.x - d.p1.x) * u[0] + (d.p2.y - d.p1.y) * u[1])


def format_value(value: float, decimal_comma: bool = True) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if decimal_comma else text


def measured_text(d: Dimension, decimal_comma: bool = True) -> str:
    if d.orientation == "angular":
        return format_value(measured(d), decimal_comma) + "°"
    return format_value(measured(d) * d.factor, decimal_comma)


def _angle(center: Point, p: Point) -> float | None:
    """Direction from ``center`` to ``p``, degrees counter-clockwise on screen."""
    dx, dy = p.x - center.x, p.y - center.y
    if math.hypot(dx, dy) <= EPS:
        return None
    return math.degrees(math.atan2(-dy, dx)) % 360


def _at(center: Point, angle: float, radius: float) -> Point:
    a = math.radians(angle)
    return Point(center.x + radius * math.cos(a), center.y - radius * math.sin(a))


def angular_sector(d: Dimension) -> tuple[float, float, float] | None:
    """Start angle, span (degrees, counter-clockwise) and radius of the arc.

    The two legs are lines through the vertex; of the four sectors between them the
    one containing ``position`` is measured (dragging across the vertex gives the
    angle between the extended legs)."""
    v = d.vertex
    if v is None:
        return None
    a1, a2, phi = _angle(v, d.p1), _angle(v, d.p2), _angle(v, d.position)
    if a1 is None or a2 is None or phi is None:
        return None
    bounds: list[float] = []
    for b in (a1, a2, (a1 + 180) % 360, (a2 + 180) % 360):
        if all(abs((b - c + 180) % 360 - 180) > 1e-9 for c in bounds):
            bounds.append(b)
    bounds.sort()
    for i, start in enumerate(bounds):
        end = bounds[(i + 1) % len(bounds)]
        span = (end - start) % 360 or 360.0
        if (phi - start) % 360 <= span:
            radius = math.hypot(d.position.x - v.x, d.position.y - v.y)
            return start, span, radius
    return None


def _leg_length(d: Dimension, angle: float) -> float:
    """How far the drawn leg reaches along ``angle``: 0 for an extended leg."""
    assert d.vertex is not None
    best = 0.0
    for p in (d.p1, d.p2):
        a = _angle(d.vertex, p)
        if a is not None and abs((a - angle + 180) % 360 - 180) < 1e-6:
            best = max(best, math.hypot(p.x - d.vertex.x, p.y - d.vertex.y))
    return best


def _readable(angle: float) -> float:
    angle = (angle + 180) % 360 - 180  # -180 < angle <= 180
    if angle > 90 + 1e-6:
        angle -= 180
    elif angle <= -90 + 1e-6:
        angle += 180  # vertical reads from the right: 90°
    return angle


def angular_geometry(d: Dimension, decimal_comma: bool = True) -> list[Entity]:
    sector = angular_sector(d)
    if sector is None or d.vertex is None:
        return []
    start, span, radius = sector
    v, h = d.vertex, d.height
    style = {"layer": d.layer, "color": d.color, "lineweight": d.lineweight}
    parts: list[Entity] = []
    # Extension lines where the arc lies beyond a leg (or on its extension).
    for i, angle in enumerate((start, (start + span) % 360)):
        reach = _leg_length(d, angle)
        if radius > reach + GAP * h:
            parts.append(
                Line(
                    id=f"{d.id}:ext{i}",
                    p1=_at(v, angle, reach + (GAP * h if reach > EPS else 0.0)),
                    p2=_at(v, angle, radius + OVERSHOOT * h),
                    linetype=None,
                    **style,
                )
            )
    parts.append(
        Arc(
            id=f"{d.id}:line",
            center=v,
            radius=radius,
            start_angle=round(start, 9),
            end_angle=round((start + span) % 360, 9),
            linetype=None,
            **style,
        )
    )
    # Arrows at both arc ends, pointing outwards along the arc.
    if radius > EPS:
        for k, (angle, sign) in enumerate(((start, 1.0), ((start + span) % 360, -1.0))):
            tip = _at(v, angle, radius)
            a = math.radians(angle)
            tx, ty = -math.sin(a) * sign, -math.cos(a) * sign  # into the arc
            for j, turn in enumerate((ARROW_ANGLE, -ARROW_ANGLE)):
                r = math.radians(turn)
                wx = tx * math.cos(r) - ty * math.sin(r)
                wy = tx * math.sin(r) + ty * math.cos(r)
                wing = Point(tip.x + wx * ARROW * h, tip.y + wy * ARROW * h)
                parts.append(
                    Line(id=f"{d.id}:arrow{k}{j}", p1=tip, p2=wing, linetype=None, **style)
                )
    # Value outside the arc at its middle, tangential and readable.
    mid = start + span / 2
    rotation = _readable(mid - 90)
    outward_up = abs(((rotation + 90) - mid + 180) % 360 - 180) < 1e-6
    offset = TEXT_GAP * h if outward_up else TEXT_GAP * h + h
    parts.append(
        Text(
            id=f"{d.id}:text",
            position=_at(v, mid, radius + offset),
            text=d.text or measured_text(d, decimal_comma),
            height=h,
            rotation=round(rotation, 6),
            halign="center",
            **style,
        )
    )
    return parts


def auto_orientation(p1: Point, p2: Point, cursor: Point) -> str:
    """Horizontal or vertical, depending on where the dimension line is dragged."""
    if abs(p1.y - p2.y) <= EPS:
        return "horizontal"
    if abs(p1.x - p2.x) <= EPS:
        return "vertical"
    beside = cursor.x < min(p1.x, p2.x) or cursor.x > max(p1.x, p2.x)
    above_or_below = cursor.y < min(p1.y, p2.y) or cursor.y > max(p1.y, p2.y)
    return "vertical" if beside and not above_or_below else "horizontal"


def dimension_geometry(d: Dimension, decimal_comma: bool = True) -> list[Entity]:
    """Lines and the value text that draw ``d`` (in the dimension's own style)."""
    if d.orientation == "angular":
        return angular_geometry(d, decimal_comma)
    u = _direction(d)
    if u is None:
        return []
    n = (-u[1], u[0])
    h = d.height
    style = {
        "layer": d.layer,
        "color": d.color,
        "lineweight": d.lineweight,
        "linetype": None,
    }

    def foot(p: Point) -> Point:
        s = (d.position.x - p.x) * n[0] + (d.position.y - p.y) * n[1]
        return Point(p.x + n[0] * s, p.y + n[1] * s)

    a, b = foot(d.p1), foot(d.p2)
    parts: list[Entity] = []
    for i, (p, q) in enumerate(((d.p1, a), (d.p2, b))):
        dx, dy = q.x - p.x, q.y - p.y
        length = math.hypot(dx, dy)
        if length <= EPS:
            continue
        ex, ey = dx / length, dy / length
        start = Point(p.x + ex * GAP * h, p.y + ey * GAP * h)
        end = Point(q.x + ex * OVERSHOOT * h, q.y + ey * OVERSHOOT * h)
        if length > GAP * h:
            parts.append(Line(id=f"{d.id}:ext{i}", p1=start, p2=end, **style))
    parts.append(Line(id=f"{d.id}:line", p1=a, p2=b, **style))
    # Arrows point outwards at both ends of the dimension line.
    span = math.hypot(b.x - a.x, b.y - a.y)
    if span > EPS:
        tx, ty = (b.x - a.x) / span, (b.y - a.y) / span
        for k, (tip, sign) in enumerate(((a, 1.0), (b, -1.0))):
            for j, turn in enumerate((ARROW_ANGLE, -ARROW_ANGLE)):
                r = math.radians(turn)
                wx = sign * (tx * math.cos(r) - ty * math.sin(r))
                wy = sign * (tx * math.sin(r) + ty * math.cos(r))
                wing = Point(tip.x + wx * ARROW * h, tip.y + wy * ARROW * h)
                parts.append(Line(id=f"{d.id}:arrow{k}{j}", p1=tip, p2=wing, **style))
    # Value: readable from below or from the right, above the dimension line.
    angle = math.degrees(math.atan2(-(b.y - a.y), b.x - a.x)) if span > EPS else 0.0
    angle = _readable(angle)
    r = math.radians(angle)
    up = (-math.sin(r), -math.cos(r))
    mid = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
    value = d.text or measured_text(d, decimal_comma)  # real length on scaled pages
    parts.append(
        Text(
            id=f"{d.id}:text",
            position=Point(mid.x + up[0] * TEXT_GAP * h, mid.y + up[1] * TEXT_GAP * h),
            text=value,
            height=h,
            rotation=round(angle, 6),
            halign="center",
            **{k: v for k, v in style.items() if k != "linetype"},
        )
    )
    return parts


PAPER_TEXT_HEIGHT = 2.5  # mm on paper


def scale_at(sheets, p: Point) -> float:
    """Scale (paper mm per model mm) of the first viewport that shows ``p``, else 1."""
    for sheet in sheets:
        for vp in sheet.viewports():
            a, b = vp.model_rect()
            if a.x <= p.x <= b.x and a.y <= p.y <= b.y:
                return vp.scale
    return 1.0


def default_height(sheets, p: Point) -> float:
    """Model height of a dimension value that is 2.5 mm high on the sheet showing ``p``."""
    return round(PAPER_TEXT_HEIGHT / scale_at(sheets, p), 6)
