import pytest
from PyQt6.QtGui import QUndoStack

from blocks_fixtures import blocks, fuse
from electrogridy.commands.blocks import AddBlockCommand, ReplaceBlockCommand, SetBasePointCommand
from electrogridy.fileio.json_format import (
    block_signature,
    document_from_dict,
    document_to_dict,
    entity_from_dict,
    entity_to_dict,
    library_from_dict,
    library_to_dict,
)
from electrogridy.model.blocks import (
    BlockDefinition,
    BlockError,
    dependencies,
    expand,
    explode,
    readable,
    world_connections,
    would_create_cycle,
)
from electrogridy.model.container import EntityContainer
from electrogridy.model.document import Document
from electrogridy.model.entities import (
    AttributeDefinition,
    BlockReference,
    Circle,
    ConnectionPoint,
    Line,
    Text,
)
from electrogridy.model.geometry import Point


def ref(**kw) -> BlockReference:
    return BlockReference(id="r", name="Sicherung", insert=Point(100, 50), **kw)


def lines(entities):
    return [e for e in entities if isinstance(e, Line)]


def test_expand_plain_reference():
    parts = expand(ref(attributes=(("BMK", "F7"),)), blocks())
    (line,) = lines(parts)
    assert (line.p1, line.p2) == (Point(100, 50), Point(100, 60))
    (text,) = [e for e in parts if isinstance(e, Text)]
    assert text.text == "F7" and text.position == Point(105, 55)
    assert not any(isinstance(e, ConnectionPoint) for e in parts)


def test_attribute_default_used_when_missing():
    (text,) = [e for e in expand(ref(), blocks()) if isinstance(e, Text)]
    assert text.text == "F1"


def test_expand_rotated_reference():
    (line,) = lines(expand(ref(rotation=90), blocks()))
    # Local (0, 10) points down; rotated 90 counter-clockwise it points right.
    assert (line.p1, line.p2) == (Point(100, 50), Point(110, 50))


def test_expand_mirrored_reference_with_base_point():
    definition = fuse()
    definition.base_point = Point(0, 10)
    parts = expand(ref(mirrored_x=True), {"Sicherung": definition})
    (line,) = lines(parts)
    assert {line.p1, line.p2} == {Point(100, 40), Point(100, 50)}
    (text,) = [e for e in parts if isinstance(e, Text)]
    # Mirrored: the label stays horizontal and to the right of the symbol.
    assert text.rotation == 0 and text.halign == "left" and text.position.x > 102


def attribute_texts(rotation, **attrs):
    r = ref(rotation=rotation, attributes=tuple(sorted(attrs.items())))
    parts = expand(r, blocks())
    geometry = [p for p in parts if not isinstance(p, Text)]
    xs = [x for g in geometry for x in _xs(g)]
    ys = [y for g in geometry for y in _ys(g)]
    return [p for p in parts if isinstance(p, Text)], (min(xs), min(ys), max(xs), max(ys))


def _xs(e):
    if isinstance(e, Line):
        return [e.p1.x, e.p2.x]
    return [e.center.x - e.radius, e.center.x + e.radius]


def _ys(e):
    if isinstance(e, Line):
        return [e.p1.y, e.p2.y]
    return [e.center.y - e.radius, e.center.y + e.radius]


@pytest.mark.parametrize("rotation", [90, 270])
def test_lying_symbol_has_label_above_left_aligned(rotation):
    (text,), (min_x, min_y, _max_x, _max_y) = attribute_texts(rotation, BMK="-F7")
    assert (text.rotation, text.halign) == (0, "left")
    assert text.position.x == pytest.approx(min_x)
    assert text.position.y < min_y  # above the symbol


def test_upside_down_symbol_has_label_on_the_right():
    (text,), (_min_x, min_y, max_x, max_y) = attribute_texts(180, BMK="-F7")
    assert (text.rotation, text.halign) == (0, "left")
    assert text.position.x > max_x
    assert text.position.y == pytest.approx((min_y + max_y) / 2)


def test_empty_values_skipped_and_order_kept_when_rotated():
    definition = fuse()
    definition.entities.add(AttributeDefinition(id="typ", tag="TYP", position=Point(5, 8.5)))
    definition.entities.add(AttributeDefinition(id="wert", tag="WERT", position=Point(5, 12)))
    r = ref(rotation=90, attributes=(("BMK", "-F7"), ("TYP", ""), ("WERT", "16 A")))
    texts = [p for p in expand(r, {"Sicherung": definition}) if isinstance(p, Text)]
    assert [t.text for t in texts] == ["-F7", "16 A"]
    assert texts[0].position.y < texts[1].position.y
    assert texts[0].position.x == texts[1].position.x


def test_unrotated_symbol_keeps_defined_label_position():
    (text,), _ = attribute_texts(0, BMK="-F7")
    assert text.position == Point(105, 55) and text.rotation == 0


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_attribute_text_always_horizontal(rotation):
    (text,) = [e for e in expand(ref(rotation=rotation), blocks()) if isinstance(e, Text)]
    assert text.rotation == 0


def test_readable_flips_alignment():
    t = Text(id="t", position=Point(0, 0), text="X", rotation=180, halign="left")
    r = readable(t)
    assert (r.rotation, r.halign, r.position) == (0, "right", Point(0, 0))


def test_invisible_attribute_not_shown():
    definition = fuse()
    att = definition.entities.get("a")
    from dataclasses import replace

    definition.entities.replace(replace(att, visible=False))
    assert not [e for e in expand(ref(), {"Sicherung": definition}) if isinstance(e, Text)]


def test_layer_zero_entities_inherit_reference_style():
    parts = expand(ref(layer="Schutz", color="#ff0000"), blocks())
    assert all(p.layer == "Schutz" and p.color == "#ff0000" for p in parts)


def test_nested_expansion():
    parts = expand(BlockReference(id="p", name="Feld", insert=Point(0, 0)), blocks())
    circles = sorted((c.center.x, c.center.y) for c in parts if isinstance(c, Circle))
    assert circles == [(-5, 5), (5, 5)]


def test_world_connections_follow_transform():
    conns = world_connections(ref(rotation=90), blocks())
    assert {(c.name, c.position, c.direction) for c in conns} == {
        ("1", Point(100, 50), 180),
        ("2", Point(110, 50), 0),
    }


def test_explode_one_level_with_new_ids():
    parts = explode(BlockReference(id="p", name="Feld", insert=Point(0, 0)), blocks())
    assert sorted(type(p).__name__ for p in parts) == ["BlockReference", "BlockReference", "Line"]
    assert {p.id for p in parts}.isdisjoint({"bus", "f1", "f2"})


def test_cycle_detection():
    b = blocks()
    assert would_create_cycle(
        "Sicherung", [BlockReference(id="x", name="Feld", insert=Point(0, 0))], b
    )
    assert not would_create_cycle(
        "Neu", [BlockReference(id="x", name="Feld", insert=Point(0, 0))], b
    )
    b["Sicherung"].entities.add(BlockReference(id="loop", name="Feld", insert=Point(0, 0)))
    with pytest.raises(BlockError):
        expand(BlockReference(id="p", name="Feld", insert=Point(0, 0)), b)


def test_dependencies():
    assert dependencies("Feld", blocks()) == ["Feld", "Sicherung"]


def test_reference_mirror_and_rotate_compose():
    r = ref(rotation=90)
    m = r.mirrored(Point(100, 0), horizontal=False)
    assert (m.rotation, m.mirrored_x) == (270, True)
    h = r.mirrored(Point(0, 50), horizontal=True)
    assert (h.rotation, h.mirrored_x) == (90, True)
    # Mirroring geometry of the reference equals mirroring its expanded parts.
    parts = sorted((p.p1, p.p2) for p in lines(expand(h, blocks())))
    expected = sorted(
        (q.p1, q.p2) for q in (e.mirrored(Point(0, 50), True) for e in lines(expand(r, blocks())))
    )
    assert [sorted(pair, key=lambda p: (p.x, p.y)) for pair in parts] == [
        sorted(pair, key=lambda p: (p.x, p.y)) for pair in expected
    ]


@pytest.mark.parametrize(
    "entity",
    [
        BlockReference(
            id="r",
            name="X",
            insert=Point(1, 2),
            rotation=270,
            mirrored_x=True,
            attributes=(("BMK", "Q1"), ("TYP", "NH00")),
        ),
        AttributeDefinition(
            id="a",
            tag="BMK",
            prompt="p",
            default="d",
            position=Point(1, 1),
            visible=False,
            halign="center",
        ),
        ConnectionPoint(id="c", name="L1", position=Point(3, 4), direction=180),
        Text(id="t", position=Point(0, 0), text="x", halign="right", valign="middle"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_new_entity_roundtrip(entity):
    assert entity_from_dict(entity_to_dict(entity)) == entity


def test_document_with_blocks_roundtrip():
    doc = Document.new("Blatt 1")
    doc.blocks.update(blocks())
    doc.model_space.add(ref())
    data = document_to_dict(doc)
    again = document_from_dict(data)
    assert document_to_dict(again) == data
    assert {"Sicherung", "Feld"} <= set(again.blocks)


def test_library_roundtrip_and_signature():
    lib = library_to_dict(list(blocks().values()), "Test")
    name, loaded = library_from_dict(lib)
    assert name == "Test" and [b.name for b in loaded] == ["Sicherung", "Feld"]
    a, b = fuse(), fuse()
    assert block_signature(a) == block_signature(b)
    copy = BlockDefinition(
        "Sicherung", Point(0, 0), EntityContainer([e.with_new_id() for e in a.entities]), "Schalten"
    )
    assert block_signature(copy) == block_signature(a)


def check(doc, command):
    stack = QUndoStack()
    before = document_to_dict(doc)
    stack.push(command)
    after = document_to_dict(doc)
    assert after != before
    stack.undo()
    assert document_to_dict(doc) == before
    stack.redo()
    assert document_to_dict(doc) == after


def test_block_commands():
    doc = Document.new("Blatt 1")
    check(doc, AddBlockCommand(doc, fuse(), "add"))
    changed = fuse()
    changed.entities.remove("c")
    check(doc, ReplaceBlockCommand(doc, changed, "replace"))


def test_set_base_point_command():
    d = fuse()
    stack = QUndoStack()
    stack.push(SetBasePointCommand(d, Point(1, 2), "base"))
    assert d.base_point == Point(1, 2)
    stack.undo()
    assert d.base_point == Point(0, 0)


def test_block_in_use_and_layer_usage_inside_blocks():
    doc = Document.new("Blatt 1")
    doc.blocks.update(blocks())
    assert doc.block_in_use("Sicherung")  # used inside "Feld"
    assert not doc.block_in_use("Feld")


def test_multi_line_attribute_pushes_the_next_ones_down():
    from electrogridy.model.blocks import BlockDefinition, explode
    from electrogridy.model.container import EntityContainer
    from electrogridy.model.entities import AttributeDefinition, BlockReference, Line
    from electrogridy.model.geometry import Point

    def att(tag, y):
        return AttributeDefinition(id=tag, tag=tag, position=Point(7.5, y), height=2.5)

    definition = BlockDefinition(
        name="Kasten",
        base_point=Point(0, 0),
        entities=EntityContainer(
            [Line(id="l", p1=Point(0, 0), p2=Point(0, 10)), att("BMK", 1.25), att("TYP", 4.75)]
        ),
    )
    ref = BlockReference(
        id="r",
        name="Kasten",
        insert=Point(100, 100),
        attributes=(("BMK", "-T1"), ("TYP", "Symo GEN24\n10.0 Plus")),
    )
    texts = {t.text: t.position for t in explode(ref, {"Kasten": definition}) if hasattr(t, "text")}
    assert texts["-T1"] == Point(107.5, 101.25)
    assert texts["Symo GEN24"] == Point(107.5, 104.75)
    assert texts["10.0 Plus"] == Point(107.5, 108.25)  # one line pitch (2.5 * 1.4) lower

    # A break in BMK moves TYP down by one line.
    ref2 = ref.with_attribute("BMK", "-T1\nWR 1")
    texts = {
        t.text: t.position for t in explode(ref2, {"Kasten": definition}) if hasattr(t, "text")
    }
    assert texts["WR 1"] == Point(107.5, 104.75)
    assert texts["Symo GEN24"] == Point(107.5, 108.25)

    # Rotated: every line is its own row of the block above the symbol.
    rotated = explode(replace_rotation(ref, 90), {"Kasten": definition})
    assert [t.text for t in rotated if hasattr(t, "text")] == ["-T1", "Symo GEN24", "10.0 Plus"]


def replace_rotation(ref, rotation):
    from dataclasses import replace

    return replace(ref, rotation=rotation)


def test_dock_points_follow_the_reference():
    from dataclasses import replace

    from electrogridy.model.blocks import BlockDefinition, dock_target, world_connections
    from electrogridy.model.container import EntityContainer
    from electrogridy.model.entities import BlockReference, ConnectionPoint, Rectangle
    from electrogridy.model.geometry import Point

    box = BlockDefinition(
        name="WR",
        base_point=Point(0, 0),
        entities=EntityContainer(
            [
                Rectangle(id="r", p1=Point(-5, 0), p2=Point(5, 10)),
                ConnectionPoint(id="c", name="1", position=Point(0, 0), direction=90),
            ]
        ),
    )
    blocks = {"WR": box}
    ref = BlockReference(id="t1", name="WR", insert=Point(100, 50))
    # Left edge, lower than the edge middle.
    local = dock_target(ref, blocks, Point(95, 57.5), 1.0)
    assert local == Point(-5, 7.5)
    assert dock_target(ref, blocks, Point(100, 50), 1.0) is None  # already a connection
    assert dock_target(ref, blocks, Point(80, 57.5), 1.0) is None  # not on the symbol
    docked = replace(ref, docks=(local,))
    dock = [c for c in world_connections(docked, blocks) if c.name == "A1"][0]
    assert dock.position == Point(95, 57.5) and dock.direction == 180
    # Moved and rotated, the dock stays on the same spot of the symbol.
    turned = replace(docked, insert=Point(0, 0), rotation=90)
    dock = [c for c in world_connections(turned, blocks) if c.name == "A1"][0]
    assert dock.position.x == pytest.approx(7.5) and dock.position.y == pytest.approx(5)
