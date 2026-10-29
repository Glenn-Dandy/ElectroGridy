"""Typed values next to the cursor while a command asks for a point. Pure Python.

Before the first point the fields are X and Y; with a base point they are the
length and angle of the line from it (angles counter-clockwise, 0° to the right);
for rectangles they are width and height. A typed value stays fixed, the mouse
only decides the remaining ones; Tab moves to the next field, Enter takes the point.
"""

import math
from dataclasses import dataclass, field

from electrogridy.model.geometry import Point

XY, POLAR, SIZE, FACTOR = "xy", "polar", "size", "factor"
# Scaling before the base point: the factor first (scaled around the selection's upper
# left corner), Tab to X/Y for a base point.
SCALE_START = "scale_start"
FIELDS: dict[str, tuple[str, ...]] = {
    XY: ("x", "y"),
    POLAR: ("length", "angle"),
    SIZE: ("width", "height"),
    FACTOR: ("factor",),  # a plain number for the tool (scaling), not a point
    SCALE_START: ("factor", "x", "y"),
}
INPUT_CHARS = "0123456789.,-"


def parse_number(text: str) -> float | None:
    """A typed number, with decimal comma or point; None while incomplete."""
    text = text.strip().replace(",", ".")
    if text in ("", "-", ".", "-."):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def format_number(value: float, decimal_comma: bool = True, digits: int = 2) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", ",") if decimal_comma else text


def angle_of(anchor: Point, p: Point) -> float:
    """Direction from ``anchor`` to ``p`` in degrees, counter-clockwise (Y points down)."""
    return math.degrees(math.atan2(-(p.y - anchor.y), p.x - anchor.x)) % 360


@dataclass
class DynamicInput:
    mode: str = XY
    texts: dict[str, str] = field(default_factory=dict)
    active: int = 0
    # Paper mm per real mm of the page (0.2 at 1:5): lengths are typed and shown real.
    scale: float = 1.0

    # -- editing ------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Switch fields (e.g. after the first point); typed values are dropped."""
        if mode != self.mode:
            self.mode = mode
            self.clear()

    def clear(self) -> None:
        self.texts = {}
        self.active = 0

    @property
    def names(self) -> tuple[str, ...]:
        return FIELDS[self.mode]

    @property
    def active_name(self) -> str:
        return self.names[self.active]

    def has_input(self) -> bool:
        return any(t for t in self.texts.values())

    def has_point(self) -> bool:
        """Whether X or Y was typed."""
        return bool(self.texts.get("x") or self.texts.get("y"))

    def type(self, char: str) -> bool:
        """Add a typed character to the active field; False if it is not part of a number."""
        if char not in INPUT_CHARS:
            return False
        self.texts[self.active_name] = self.texts.get(self.active_name, "") + char
        return True

    def backspace(self) -> None:
        self.texts[self.active_name] = self.texts.get(self.active_name, "")[:-1]

    def next_field(self) -> None:
        self.active = (self.active + 1) % len(self.names)

    def value(self, name: str) -> float | None:
        return parse_number(self.texts.get(name, ""))

    # -- geometry -----------------------------------------------------------

    def constrain(self, anchor: Point | None, cursor: Point) -> Point:
        """The point the fields and the mouse together describe."""
        if self.mode == FACTOR:
            return cursor
        if self.mode in (XY, SCALE_START) or anchor is None:
            x, y = self.value("x"), self.value("y")
            return Point(cursor.x if x is None else x, cursor.y if y is None else y)
        if self.mode == SIZE:
            w, h = self.value("width"), self.value("height")
            w = None if w is None else w * self.scale
            h = None if h is None else h * self.scale
            sx = -1.0 if cursor.x < anchor.x else 1.0
            sy = -1.0 if cursor.y < anchor.y else 1.0
            x = cursor.x if w is None else anchor.x + sx * abs(w)
            y = cursor.y if h is None else anchor.y + sy * abs(h)
            return Point(x, y)
        length, angle = self.value("length"), self.value("angle")
        if length is None and angle is None:
            return cursor
        if length is not None:
            length *= self.scale
        if length is None:
            # Fixed direction: the mouse decides how far along it.
            a = math.radians(angle)
            ux, uy = math.cos(a), -math.sin(a)
            length = max(0.0, (cursor.x - anchor.x) * ux + (cursor.y - anchor.y) * uy)
        if angle is None:
            angle = angle_of(anchor, cursor) if cursor != anchor else 0.0
        a = math.radians(angle)
        return Point(
            round(anchor.x + length * math.cos(a), 9),
            round(anchor.y - length * math.sin(a), 9),
        )

    def shown(self, anchor: Point | None, point: Point, decimal_comma: bool) -> dict[str, str]:
        """Text of every field: what was typed, or the value at ``point``."""
        if self.mode == FACTOR:
            typed = self.texts.get("factor", "")
            return {"factor": (typed.replace(".", ",") if decimal_comma else typed) or "1"}
        if self.mode == SCALE_START:
            values = {"factor": 1.0, "x": point.x, "y": point.y}
        elif self.mode == XY or anchor is None:
            values = {"x": point.x, "y": point.y}
        elif self.mode == SIZE:
            values = {
                "width": abs(point.x - anchor.x) / self.scale,
                "height": abs(point.y - anchor.y) / self.scale,
            }
        else:
            values = {
                "length": math.hypot(point.x - anchor.x, point.y - anchor.y) / self.scale,
                "angle": angle_of(anchor, point) if point != anchor else 0.0,
            }
        result = {}
        for name in self.names:
            typed = self.texts.get(name, "")
            if typed:
                result[name] = typed.replace(".", ",") if decimal_comma else typed
            else:
                result[name] = format_number(values[name], decimal_comma)
            if name == "angle":
                result[name] += "°"
        return result
