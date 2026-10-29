"""Parsing of typed coordinates. Pure Python."""

import math

from electrogridy.model.geometry import Point


class CoordinateError(ValueError):
    pass


def _number(text: str) -> float:
    try:
        value = float(text.strip())
    except ValueError:
        raise CoordinateError(text) from None
    if not math.isfinite(value):
        raise CoordinateError(text)
    return value


def _pair(text: str) -> tuple[float, float]:
    # "10.5,20" or, with German decimal commas, "10,5;20".
    if ";" in text:
        parts = text.replace(",", ".").split(";")
    else:
        parts = text.split(",")
    if len(parts) != 2:
        raise CoordinateError(text)
    return _number(parts[0]), _number(parts[1])


def parse_coordinate(
    text: str,
    reference: Point | None,
    direction: tuple[float, float] | None,
    scale: float = 1.0,
) -> Point:
    """Evaluate a typed point.

    ``x,y`` absolute, ``@dx,dy`` relative to ``reference``, a single number
    is a length from ``reference`` along ``direction`` (a unit vector, given
    only while ortho mode is active). Relative values and lengths are real millimetres
    on a page drawn at ``scale`` (paper mm per real mm); absolute ones are on the page.
    """
    text = text.strip()
    if not text:
        raise CoordinateError(text)
    if text.startswith("@"):
        if reference is None:
            raise CoordinateError("no reference point")
        dx, dy = _pair(text[1:])
        return Point(reference.x + dx * scale, reference.y + dy * scale)
    if "," in text or ";" in text:
        x, y = _pair(text)
        return Point(x, y)
    if reference is None or direction is None:
        raise CoordinateError("length needs a reference point and ortho mode")
    length = _number(text.replace(",", ".")) * scale
    return Point(reference.x + direction[0] * length, reference.y + direction[1] * length)
