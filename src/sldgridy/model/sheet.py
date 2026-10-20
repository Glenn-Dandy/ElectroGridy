"""Frame geometry after DIN EN ISO 5457 and helpers for sheets."""

from sldgridy.model.entities import (
    BlockReference,
    Entity,
    Line,
    Rectangle,
    Text,
    Viewport,
    new_id,
)
from sldgridy.model.geometry import Point

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


# -- column grid of pages (references like "/3.4": page 3, column 4) -----------


def column_edges(width: float, height: float, columns: int) -> list[float]:
    """X positions of the column borders, ``columns + 1`` of them, inside the frame."""
    a, b = frame_corners(width, height)
    step = (b.x - a.x) / columns
    return [a.x + i * step for i in range(columns + 1)]


def column_at(width: float, height: float, columns: int, x: float) -> int:
    """Column (1 … columns) a point at ``x`` lies in; outside the frame the nearest."""
    if columns <= 0:
        return 0
    edges = column_edges(width, height, columns)
    for i in range(columns):
        if x < edges[i + 1]:
            return i + 1
    return columns


def column_strip_entities(width: float, height: float, columns: int) -> list[Entity]:
    """Numbered strip along the top edge of the frame."""
    if columns <= 0:
        return []
    a, _ = frame_corners(width, height)
    edges = column_edges(width, height, columns)
    bottom = a.y + COLUMN_STRIP
    out: list[Entity] = [
        Line(id="cols", p1=Point(edges[0], bottom), p2=Point(edges[-1], bottom), lineweight=0.35)
    ]
    for i in range(columns):
        if i:
            out.append(
                Line(
                    id=f"col{i}",
                    p1=Point(edges[i], a.y),
                    p2=Point(edges[i], bottom),
                    lineweight=0.35,
                )
            )
        out.append(
            Text(
                id=f"colnr{i}",
                position=Point(
                    (edges[i] + edges[i + 1]) / 2, bottom - (COLUMN_STRIP - COLUMN_TEXT) / 2
                ),
                text=str(i + 1),
                height=COLUMN_TEXT,
                halign="center",
            )
        )
    return out


def designation_text(width: float, height: float, label: str) -> Text:
    """Page designation above the frame's top right corner."""
    _, b = frame_corners(width, height)
    a, _ = frame_corners(width, height)
    return Text(
        id="designation",
        position=Point(b.x, a.y - 2.0),
        text=label,
        height=DESIGNATION_TEXT,
        halign="right",
    )
