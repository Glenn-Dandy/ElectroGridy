"""Grid helpers that do not depend on Qt."""

import math

# Multipliers tried in order when the grid gets too dense on screen.
_STEP_MULTIPLIERS = (1, 2, 5)


def visible_grid_step(base: float, px_per_unit: float, min_px: float) -> float:
    """Smallest multiple of ``base`` (1-2-5 sequence) that is at least ``min_px`` apart.

    ``base`` is the configured grid spacing in mm, ``px_per_unit`` the current
    number of screen pixels per mm.
    """
    if base <= 0 or px_per_unit <= 0:
        raise ValueError("base and px_per_unit must be positive")
    if base * px_per_unit >= min_px:
        return base
    decade = 1.0
    while True:
        for m in _STEP_MULTIPLIERS:
            step = base * m * decade
            if step * px_per_unit >= min_px:
                return step
        decade *= 10.0


def grid_lines(start: float, end: float, step: float) -> list[float]:
    """Positions of grid lines ``k * step`` within [start, end]."""
    first = math.ceil(start / step)
    last = math.floor(end / step)
    return [k * step for k in range(first, last + 1)]
