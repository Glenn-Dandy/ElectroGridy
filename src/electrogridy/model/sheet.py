"""Frame geometry after DIN EN ISO 5457 and helpers for sheets."""

from electrogridy.model.entities import (
    BlockReference,
    Entity,
    Line,
    Rectangle,
    Text,
    Viewport,
    new_id,
)
from electrogridy.model.geometry import Point

MARGIN_LEFT = 20.0
MARGIN = 10.0
FRAME_WEIGHT = 0.7
CENTER_MARK = 5.0  # length of the centring marks beyond the frame
COLUMN_STRIP = 5.0  # height of the numbered column strip at the top of a page
COLUMN_TEXT = 2.5
DESIGNATION_TEXT = 3.5


def frame_corners(width: float, height: float) -> tuple[Point, Point]:
    return Point(MARGIN_LEFT, MARGIN), Point(width - MARGIN, height - MARGIN)


def frame_entities(width: float, height: float) -> list[Entity]:
    """Frame line and centring marks of a sheet."""
    a, b = frame_corners(width, height)
    cx, cy = width / 2, height / 2
    marks = [
        ((cx, a.y - CENTER_MARK), (cx, a.y)),
        ((cx, b.y), (cx, b.y + CENTER_MARK)),
        ((a.x - CENTER_MARK, cy), (a.x, cy)),
        ((b.x, cy), (b.x + CENTER_MARK, cy)),
    ]
    out: list[Entity] = [Rectangle(id="frame", p1=a, p2=b, lineweight=FRAME_WEIGHT)]
    for i, (p, q) in enumerate(marks):
        out.append(Line(id=f"mark{i}", p1=Point(*p), p2=Point(*q), lineweight=FRAME_WEIGHT))
    return out


def title_block_insert(width: float, height: float) -> Point:
    return frame_corners(width, height)[1]


def default_viewport(width: float, height: float) -> Viewport:
    """Viewport filling the drawing area; model (0, 0) at the frame's top left corner."""
    a, b = frame_corners(width, height)
    w, h = b.x - a.x, b.y - a.y
    return Viewport(id=new_id(), p1=a, p2=b, center=Point(w / 2, h / 2), scale=1.0)


def title_block_reference(
    name: str, width: float, height: float, values: dict[str, str]
) -> BlockReference:
    return BlockReference(
        id="title_block",
        name=name,
        insert=title_block_insert(width, height),
        attributes=tuple(sorted(values.items())),
    )


# -- circuit diagram frame (Florian's template) ----------------------------------------
# Margins left, right and bottom 5 mm, top 20 mm (filing) on the printed A4 sheet, a
# 3.5 mm band all round with the column numbers 0 … n-1 (top and bottom) and row letters
# A … (left and right). References read "/page.column".

# Top 15 mm until 1.3.3.dev1: punched holes (ISO 838: 6 mm, centre 12 mm from the
# edge) reached the frame (Florian 2026-10-29).
SCHEMATIC_TOP = 20.0
SCHEMATIC_SIDE = 5.0
PRINT_SHORT_SIDE = 210.0  # A4: what the pages are printed on
# The numbered band: 5 mm until 1.3.2.dev5, 4 mm until dev12; made narrower from the
# inside, the outer line stays (Florian 2026-10-29).
BAND = 3.5
ROW_HEIGHT = 44.5  # A3 landscape: six rows A … F, A4 landscape: four
BAND_TEXT = 2.0
# Frame lines. The margins reach to the outer edge of the outer line: printers that
# cannot print the outermost 4.9 mm cut off half of a line centred at 5 mm, so left,
# right and bottom came out thinner than the top (Florian 2026-10-29).
FRAME_WEIGHT = 0.5


def schematic_margins(width: float, height: float) -> tuple[float, float]:
    """(left, right and bottom margin; top margin) of the frame. Larger sheets than A4
    have them enlarged in proportion, so that the sheet fitted onto A4 paper prints with
    exactly 5 and 20 mm (A3: 7.1 and 28.3 mm)."""
    k = max(1.0, min(width, height) / PRINT_SHORT_SIDE)
    return round(SCHEMATIC_SIDE * k, 1), round(SCHEMATIC_TOP * k, 1)


def schematic_outer(width: float, height: float) -> tuple[Point, Point]:
    """Middle of the outer frame line."""
    side, top = schematic_margins(width, height)
    side, top = side + FRAME_WEIGHT / 2, top + FRAME_WEIGHT / 2
    return Point(side, top), Point(width - side, height - side)


def schematic_inner(width: float, height: float) -> tuple[Point, Point]:
    """Drawing area inside the numbered band."""
    a, b = schematic_outer(width, height)
    return Point(a.x + BAND, a.y + BAND), Point(b.x - BAND, b.y - BAND)


def row_count(width: float, height: float) -> int:
    a, b = schematic_inner(width, height)
    return max(1, round((b.y - a.y) / ROW_HEIGHT))


def column_edges(width: float, height: float, columns: int) -> list[float]:
    """X positions of the column borders, ``columns + 1`` of them."""
    a, b = schematic_inner(width, height)
    step = (b.x - a.x) / columns
    return [a.x + i * step for i in range(columns + 1)]


def column_at(width: float, height: float, columns: int, x: float) -> int | None:
    """Column (0 … columns-1) a point at ``x`` lies in, the nearest outside the frame;
    None without a column grid."""
    if columns <= 0:
        return None
    edges = column_edges(width, height, columns)
    for i in range(columns):
        if x < edges[i + 1]:
            return i
    return columns - 1


def schematic_frame_entities(width: float, height: float, columns: int) -> list[Entity]:
    """Outer and inner frame line, the band with column numbers and row letters."""
    a, b = schematic_outer(width, height)
    ia, ib = schematic_inner(width, height)
    out: list[Entity] = [
        Rectangle(id="outer", p1=a, p2=b, lineweight=FRAME_WEIGHT),
        Rectangle(id="inner", p1=ia, p2=ib, lineweight=FRAME_WEIGHT),
    ]
    edges = column_edges(width, height, max(columns, 1))
    n = max(columns, 1)
    for i in range(n):
        if i:
            for y0, y1 in ((a.y, ia.y), (ib.y, b.y)):
                out.append(Line(id=f"c{i}_{y0}", p1=Point(edges[i], y0), p2=Point(edges[i], y1)))
        cx = (edges[i] + edges[i + 1]) / 2
        for y in (a.y + BAND / 2, ib.y + BAND / 2):
            out.append(
                Text(
                    id=f"cn{i}_{y}",
                    position=Point(cx, y + BAND_TEXT / 2),
                    text=str(i),
                    height=BAND_TEXT,
                    halign="center",
                )
            )
    rows = row_count(width, height)
    step = (ib.y - ia.y) / rows
    for j in range(rows):
        top = ia.y + j * step
        if j:
            for x0, x1 in ((a.x, ia.x), (ib.x, b.x)):
                out.append(Line(id=f"r{j}_{x0}", p1=Point(x0, top), p2=Point(x1, top)))
        letter = chr(ord("A") + j) if j < 26 else str(j)
        for x in (a.x + BAND / 2, ib.x + BAND / 2):
            out.append(
                Text(
                    id=f"rn{j}_{x}",
                    position=Point(x, top + step / 2 + BAND_TEXT / 2),
                    text=letter,
                    height=BAND_TEXT,
                    halign="center",
                )
            )
    return out


def schematic_title_insert(width: float, height: float) -> Point:
    """Bottom right corner of the drawing area: base point of the title block."""
    return schematic_inner(width, height)[1]


def schematic_title_width(width: float, height: float) -> float:
    a, b = schematic_inner(width, height)
    return round(b.x - a.x, 3)


def schematic_viewport(width: float, height: float) -> Viewport:
    """Viewport over the drawing area of the circuit diagram frame, above the title
    block; model (0, 0) at its top left corner."""
    from electrogridy.model.title_block import SCHEMATIC_TITLE_HEIGHT

    a, b = schematic_inner(width, height)
    b = Point(b.x, b.y - SCHEMATIC_TITLE_HEIGHT)
    w, h = b.x - a.x, b.y - a.y
    return Viewport(id=new_id(), p1=a, p2=b, center=Point(w / 2, h / 2), scale=1.0)
