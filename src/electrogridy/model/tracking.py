"""Object snap tracking: alignment with previously acquired points. Pure Python."""

import math
from dataclasses import dataclass

from electrogridy.model.geometry import Point

MAX_ACQUIRED = 3


@dataclass(frozen=True)
class TrackLine:
    """Alignment line through ``origin``: vertical (x = origin.x) or horizontal."""

    origin: Point
    vertical: bool


@dataclass(frozen=True)
class TrackResult:
    point: Point
    lines: tuple[TrackLine, ...]


def _grid(value: float, spacing: float | None) -> float:
    """Same rounding as grid snap: midpoints always go up."""
    if not spacing or spacing <= 0:
        return value
    return math.floor(value / spacing + 0.5) * spacing


def _nearest(points: list[Point], value: float, axis: str, tolerance: float) -> Point | None:
    close = [p for p in points if abs(getattr(p, axis) - value) <= tolerance]
    return min(close, key=lambda p: abs(getattr(p, axis) - value)) if close else None


def track(
    raw: Point,
    acquired: list[Point],
    tolerance: float,
    grid: float | None = None,
    ortho_base: Point | None = None,
) -> TrackResult | None:
    """Align ``raw`` with acquired points, or None if it is not close to any alignment.

    The coordinate along the tracking line stays on the grid (``grid`` spacing).
    With ``ortho_base`` the result also lies on the ortho line through that base.
    """
    if not acquired:
        return None
    v = _nearest(acquired, raw.x, "x", tolerance)  # vertical line x = v.x
    h = _nearest(acquired, raw.y, "y", tolerance)  # horizontal line y = h.y
    if ortho_base is not None:
        horizontal_move = abs(raw.x - ortho_base.x) >= abs(raw.y - ortho_base.y)
        if horizontal_move and v is not None:
            return TrackResult(Point(v.x, ortho_base.y), (TrackLine(v, True),))
        if not horizontal_move and h is not None:
            return TrackResult(Point(ortho_base.x, h.y), (TrackLine(h, False),))
        return None
    if v is not None and h is not None and v != h:
        return TrackResult(Point(v.x, h.y), (TrackLine(v, True), TrackLine(h, False)))
    if v is not None:
        return TrackResult(Point(v.x, _grid(raw.y, grid)), (TrackLine(v, True),))
    if h is not None:
        return TrackResult(Point(_grid(raw.x, grid), h.y), (TrackLine(h, False),))
    return None


def toggle_acquired(acquired: list[Point], p: Point) -> list[Point]:
    """Add ``p`` (newest first, at most MAX_ACQUIRED) or remove it if already acquired."""
    if p in acquired:
        return [q for q in acquired if q != p]
    return [p, *acquired][:MAX_ACQUIRED]
