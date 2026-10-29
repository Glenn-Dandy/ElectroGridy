"""ISO 216 paper formats. All sizes in millimetres."""

from enum import StrEnum


class Orientation(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


# Portrait (width, height) in mm.
PAPER_FORMATS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}

DEFAULT_FORMAT = "A0"
DEFAULT_ORIENTATION = Orientation.LANDSCAPE


def paper_of(width: float, height: float, tolerance: float = 3.0) -> tuple[str, Orientation] | None:
    """The ISO format of a page ``width`` × ``height`` mm (a PDF page), None for others."""
    short, long = sorted((width, height))
    for name, (w, h) in PAPER_FORMATS.items():
        if abs(short - w) <= tolerance and abs(long - h) <= tolerance:
            landscape = width > height
            return name, Orientation.LANDSCAPE if landscape else Orientation.PORTRAIT
    return None


def sheet_size(paper: str, orientation: Orientation) -> tuple[float, float]:
    """Return (width, height) in mm of a sheet in the given orientation."""
    try:
        short, long = PAPER_FORMATS[paper]
    except KeyError:
        raise ValueError(f"unknown paper format: {paper!r}") from None
    if orientation is Orientation.LANDSCAPE:
        return long, short
    return short, long
