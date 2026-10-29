"""Block definitions used by block tests."""

from electrogridy.model.blocks import BlockDefinition
from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import (
    AttributeDefinition,
    BlockReference,
    Circle,
    ConnectionPoint,
    Line,
)
from electrogridy.model.geometry import Point


def fuse() -> BlockDefinition:
    """10 mm high vertical symbol, base point at the top connection."""
    return BlockDefinition(
        name="Sicherung",
        base_point=Point(0, 0),
        category="Schalten",
        entities=EntityContainer(
            [
                Line(id="l", p1=Point(0, 0), p2=Point(0, 10)),
                Circle(id="c", center=Point(0, 5), radius=2),
                AttributeDefinition(
                    id="a", tag="BMK", prompt="Kennzeichen", default="F1", position=Point(5, 5)
                ),
                ConnectionPoint(id="p1", name="1", position=Point(0, 0), direction=90),
                ConnectionPoint(id="p2", name="2", position=Point(0, 10), direction=270),
            ]
        ),
    )


def panel() -> BlockDefinition:
    """Nested block holding two fuses."""
    return BlockDefinition(
        name="Feld",
        base_point=Point(0, 0),
        entities=EntityContainer(
            [
                Line(id="bus", p1=Point(-10, 0), p2=Point(10, 0)),
                BlockReference(id="f1", name="Sicherung", insert=Point(-5, 0)),
                BlockReference(id="f2", name="Sicherung", insert=Point(5, 0)),
            ]
        ),
    )


def blocks() -> dict[str, BlockDefinition]:
    return {b.name: b for b in (fuse(), panel())}
