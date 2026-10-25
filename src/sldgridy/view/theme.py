"""Colours of the drawing area on screen: light (paper look) or dark, easier on the eyes
in the evening.

Only the screen follows the theme. Printing and export paint with ``helpers=False`` and
keep the drawing's own colours on white paper.

Dark theme: black and grey lines (the usual drawing colour) become light grey, white
becomes dark; coloured lines keep their hue and are lightened where they would be too dark
on the dark background.
"""

from dataclasses import dataclass

from PyQt6.QtGui import QColor

LIGHT, DARK = "light", "dark"
CHOICES = (LIGHT, DARK)
SETTINGS_KEY = "view/canvas_theme"

GREY_SATURATION = 0.2  # below this a colour counts as black, grey or white
MIN_COLOUR_LIGHTNESS = 0.62  # coloured lines on the dark background


@dataclass(frozen=True)
class Palette:
    dark: bool
    background: QColor  # model and block editor
    sheet_background: QColor  # around the paper
    paper: QColor
    paper_edge: QColor
    shadow: QColor
    grid_minor: QColor
    grid_major: QColor
    origin_box: QColor
    crosshair: QColor
    preview: QColor
    rubber_line: QColor
    field: QColor  # input fields at the crosshair
    field_typed: QColor
    field_text: QColor


LIGHT_PALETTE = Palette(
    dark=False,
    background=QColor("#ffffff"),
    sheet_background=QColor("#c8c8c8"),
    paper=QColor("#ffffff"),
    paper_edge=QColor("#606060"),
    shadow=QColor(0, 0, 0, 60),
    grid_minor=QColor("#e6e6e6"),
    grid_major=QColor("#c8c8c8"),
    origin_box=QColor("#404040"),
    crosshair=QColor("#303030"),
    # Translucent, so points and lines under a preview (a block being placed) stay visible.
    preview=QColor(110, 110, 110, 150),
    rubber_line=QColor("#9e9e9e"),
    field=QColor("#ffffff"),
    field_typed=QColor("#fff3c4"),
    field_text=QColor("#202020"),
)

DARK_PALETTE = Palette(
    dark=True,
    background=QColor("#1e2126"),
    sheet_background=QColor("#121417"),
    paper=QColor("#24272d"),
    paper_edge=QColor("#5a6068"),
    shadow=QColor(0, 0, 0, 140),
    grid_minor=QColor("#2b2f35"),
    grid_major=QColor("#3b4048"),
    origin_box=QColor("#b0b4ba"),
    crosshair=QColor("#d0d3d8"),
    preview=QColor(170, 170, 170, 150),
    rubber_line=QColor("#7d838b"),
    field=QColor("#2d3138"),
    field_typed=QColor("#5c4b12"),
    field_text=QColor("#e6e8eb"),
)

current = LIGHT_PALETTE


def set_dark(dark: bool) -> None:
    global current
    current = DARK_PALETTE if dark else LIGHT_PALETTE


def is_dark() -> bool:
    return current.dark


def ink(color: QColor) -> QColor:
    """Screen colour of a line, text or fill of the drawing."""
    if not current.dark:
        return color
    h, s, lightness, a = color.getHslF()
    if s < GREY_SATURATION or h < 0:
        # Black is the usual drawing colour: it becomes light grey, white becomes dark.
        lightness = 0.9 - 0.75 * lightness
    else:
        lightness = max(lightness, MIN_COLOUR_LIGHTNESS)
    out = QColor()
    out.setHslF(max(h, 0.0), s, lightness, a)
    return out


def surface(color: QColor) -> QColor:
    """Screen colour of a background the canvas was given (model or sheet)."""
    if not current.dark:
        return color
    if color == LIGHT_PALETTE.sheet_background:
        return current.sheet_background
    if color == LIGHT_PALETTE.background:
        return current.background
    return ink(color)
