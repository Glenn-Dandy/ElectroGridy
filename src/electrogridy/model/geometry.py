"""Basic 2D geometry in millimetres. Y points down, angles are visually counter-clockwise."""

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x - other.x, self.y - other.y)

    def translated(self, dx: float, dy: float) -> "Point":
        return Point(self.x + dx, self.y + dy)


def distance(a: Point, b: Point) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def rotate_quarter(p: Point, center: Point, quarters: int) -> Point:
    """Rotate ``p`` about ``center`` by ``quarters`` * 90 degrees counter-clockwise on screen."""
    dx, dy = p.x - center.x, p.y - center.y
    for _ in range(quarters % 4):
        # With Y down, (1, 0) must go to (0, -1).
        dx, dy = dy, -dx
    return Point(center.x + dx, center.y + dy)


def angle_deg(center: Point, p: Point) -> float:
    """Screen angle of ``p`` seen from ``center`` in [0, 360), counter-clockwise from +X."""
    a = math.degrees(math.atan2(-(p.y - center.y), p.x - center.x))
    return a % 360.0


def point_at_angle(center: Point, radius: float, angle: float) -> Point:
    rad = math.radians(angle)
    return Point(center.x + radius * math.cos(rad), center.y - radius * math.sin(rad))


def snap_to_grid(p: Point, spacing: float) -> Point:
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    # floor(v + 0.5) instead of round(): exact midpoints always go up, never to even.
    return Point(
        math.floor(p.x / spacing + 0.5) * spacing, math.floor(p.y / spacing + 0.5) * spacing
    )


def ortho(base: Point, p: Point) -> Point:
    """Constrain ``p`` to the horizontal or vertical through ``base``, whichever is closer."""
    if abs(p.x - base.x) >= abs(p.y - base.y):
        return Point(p.x, base.y)
    return Point(base.x, p.y)


def quarters_towards(center: Point, p: Point) -> int:
    """Number of 90 degree steps (0..3) closest to the direction from ``center`` to ``p``."""
    return round(angle_deg(center, p) / 90.0) % 4


def mirror_point(p: Point, axis: Point, horizontal: bool) -> Point:
    """Mirror at the horizontal (``horizontal``) or vertical line through ``axis``."""
    if horizontal:
        return Point(p.x, 2 * axis.y - p.y)
    return Point(2 * axis.x - p.x, p.y)


def midpoint(a: Point, b: Point) -> Point:
    return Point((a.x + b.x) / 2, (a.y + b.y) / 2)
