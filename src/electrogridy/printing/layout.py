"""Page planning for printing: 1:1, fit to paper and tiling. Pure Python."""

import math
from dataclasses import dataclass, field
from enum import StrEnum

DEFAULT_OVERLAP = 10.0  # mm
QUICK_PRINT_MARGIN = 10.0  # mm around the model extents


class Mode(StrEnum):
    ONE_TO_ONE = "1:1"
    FIT = "fit"
    TILES = "tiles"


@dataclass(frozen=True)
class Page:
    """One printed page.

    The sheet is drawn with ``scale`` and moved so that sheet point
    (``origin_x``, ``origin_y``) lands at the page position (``offset_x``,
    ``offset_y``); all values in mm.
    """

    width: float
    height: float
    scale: float = 1.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    # Tiling extras: (row, column) counted from 1 and cut line positions on the page.
    tile: tuple[int, int] | None = None
    cut_x: list[float] = field(default_factory=list)
    cut_y: list[float] = field(default_factory=list)

    def to_page(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.offset_x + (x - self.origin_x) * self.scale,
            self.offset_y + (y - self.origin_y) * self.scale,
        )


def one_to_one(sheet_w: float, sheet_h: float) -> list[Page]:
    return [Page(sheet_w, sheet_h)]


def fit(sheet_w: float, sheet_h: float, paper_w: float, paper_h: float) -> list[Page]:
    """Scale the sheet onto the paper, turning the paper if that gives a larger scale."""
    if (paper_w > paper_h) != (sheet_w > sheet_h):
        paper_w, paper_h = paper_h, paper_w
    s = min(paper_w / sheet_w, paper_h / sheet_h)
    return [
        Page(
            paper_w,
            paper_h,
            scale=s,
            offset_x=(paper_w - sheet_w * s) / 2,
            offset_y=(paper_h - sheet_h * s) / 2,
        )
    ]


def _count(length: float, paper: float, overlap: float) -> int:
    if length <= paper:
        return 1
    return math.ceil((length - overlap) / (paper - overlap))


def tile_count(
    sheet_w: float, sheet_h: float, paper_w: float, paper_h: float, overlap: float
) -> tuple[int, int]:
    """(rows, columns) needed for the given paper orientation."""
    return _count(sheet_h, paper_h, overlap), _count(sheet_w, paper_w, overlap)


def tiles(
    sheet_w: float,
    sheet_h: float,
    paper_w: float,
    paper_h: float,
    overlap: float = DEFAULT_OVERLAP,
) -> list[Page]:
    """1:1 tiles, row by row, using the paper orientation that needs fewer sheets."""
    if overlap < 0 or overlap >= min(paper_w, paper_h):
        raise ValueError("invalid overlap")
    rows, cols = tile_count(sheet_w, sheet_h, paper_w, paper_h, overlap)
    r2, c2 = tile_count(sheet_w, sheet_h, paper_h, paper_w, overlap)
    if r2 * c2 < rows * cols:
        paper_w, paper_h, rows, cols = paper_h, paper_w, r2, c2
    step_x, step_y = paper_w - overlap, paper_h - overlap
    pages = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * step_x, r * step_y
            # Cut in the middle of each overlap; outer edges are not cut.
            cut_x = [overlap / 2] if c > 0 else []
            cut_x += [paper_w - overlap / 2] if c < cols - 1 else []
            cut_y = [overlap / 2] if r > 0 else []
            cut_y += [paper_h - overlap / 2] if r < rows - 1 else []
            pages.append(
                Page(
                    paper_w,
                    paper_h,
                    origin_x=x0,
                    origin_y=y0,
                    tile=(r + 1, c + 1),
                    cut_x=cut_x,
                    cut_y=cut_y,
                )
            )
    return pages


def fit_rect(
    left: float,
    top: float,
    width: float,
    height: float,
    paper_w: float,
    paper_h: float,
    margin: float = QUICK_PRINT_MARGIN,
) -> Page:
    """Quick print: the model area (left, top, width, height) fitted inside the margins."""
    if (paper_w > paper_h) != (width > height):
        paper_w, paper_h = paper_h, paper_w
    avail_w, avail_h = paper_w - 2 * margin, paper_h - 2 * margin
    s = min(avail_w / max(width, 1e-9), avail_h / max(height, 1e-9))
    return Page(
        paper_w,
        paper_h,
        scale=s,
        origin_x=left,
        origin_y=top,
        offset_x=(paper_w - width * s) / 2,
        offset_y=(paper_h - height * s) / 2,
    )


ISO_FRAME = (20.0, 10.0, 10.0, 10.0)  # left, top, right, bottom margin of the sheet


def frame_clipped(
    page: Page,
    min_margins: tuple[float, float, float, float],
    frame_margins: tuple[float, float, float, float] = ISO_FRAME,
) -> bool:
    """True if the device's unprintable margins (left, top, right, bottom) cut into the
    frame, which is ``frame_margins`` away from the edges of the sheet (to the outer
    edge of its line)."""
    if page.tile is not None:
        return False
    left_f, top_f, right_f, bottom_f = frame_margins
    frame = (left_f * page.scale + page.offset_x, top_f * page.scale + page.offset_y)
    right = right_f * page.scale + page.offset_x
    bottom = bottom_f * page.scale + page.offset_y
    left_m, top_m, right_m, bottom_m = min_margins
    return left_m > frame[0] or top_m > frame[1] or right_m > right or bottom_m > bottom
