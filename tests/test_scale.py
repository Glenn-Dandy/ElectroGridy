import pytest

from electrogridy.fileio.json_format import entity_from_dict, entity_to_dict
from electrogridy.model.blocks import BlockDefinition, expand, point_to_local, world_connections
from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import (
    BlockReference,
    Circle,
    ConnectionPoint,
    Dimension,
    Line,
    Text,
    Wire,
)
from electrogridy.model.geometry import Point
from electrogridy.model.scale import scale_entity, scale_point
from factories import sample_entities

BASE = Point(10, 10)


def test_scale_point_and_simple_entities():
    assert scale_point(Point(20, 30), BASE, 2) == Point(30, 50)
    line = scale_entity(Line(id="l", p1=Point(10, 10), p2=Point(40, 10)), BASE, 0.5)
    assert (line.p1, line.p2) == (Point(10, 10), Point(25, 10))
    circle = scale_entity(Circle(id="c", center=Point(20, 10), radius=5), BASE, 3)
    assert circle.center == Point(40, 10) and circle.radius == 15
    text = scale_entity(Text(id="t", position=Point(12, 10), text="A", height=2.5), BASE, 2)
    assert text.position == Point(14, 10) and text.height == 5


def test_dimension_wire_and_every_sample_scale():
    d = Dimension(id="d", p1=Point(10, 10), p2=Point(50, 10), position=Point(30, 0), height=2.5)
    big = scale_entity(d, BASE, 2)
    assert big.p2 == Point(90, 10) and big.height == 5
    w = Wire(id="w", points=(Point(10, 10), Point(10, 30)), label="X", label_height=2.5)
    assert scale_entity(w, BASE, 2).points[-1] == Point(10, 50)
    for e in sample_entities():  # no type is left out or breaks
        assert scale_entity(e, BASE, 1.5).id == e.id
    with pytest.raises(ValueError):
        scale_entity(d, BASE, 0)


def symbol():
    return BlockDefinition(
        name="S",
        base_point=Point(0, 0),
        entities=EntityContainer(
            [
                Line(id="a", p1=Point(0, 0), p2=Point(0, 10)),
                ConnectionPoint(id="c1", name="1", position=Point(0, 10), direction=270),
            ]
        ),
    )


def test_scaled_block_reference():
    blocks = {"S": symbol()}
    ref = BlockReference(id="r", name="S", insert=Point(100, 100))
    big = scale_entity(ref, Point(100, 100), 2)
    assert big.scale == 2 and big.insert == Point(100, 100)
    (line,) = [e for e in expand(big, blocks) if isinstance(e, Line)]
    assert (line.p1, line.p2) == (Point(100, 100), Point(100, 120))
    (cp,) = world_connections(big, blocks)
    assert cp.position == Point(100, 120)
    assert point_to_local(big, Point(0, 0), Point(100, 120)) == Point(0, 10)
    turned = BlockReference(id="r", name="S", insert=Point(0, 0), rotation=90, scale=0.5)
    (cp,) = world_connections(turned, blocks)
    assert cp.position.x == pytest.approx(5) and cp.position.y == pytest.approx(0)
    assert point_to_local(turned, Point(0, 0), cp.position) == Point(0, 10)


def test_block_scale_is_saved_only_when_set():
    ref = BlockReference(id="r", name="S", insert=Point(1, 2))
    assert "scale" not in entity_to_dict(ref)
    big = BlockReference(id="r", name="S", insert=Point(1, 2), scale=2.5)
    assert entity_from_dict(entity_to_dict(big)) == big
