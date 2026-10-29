import pytest
from PyQt6.QtGui import QUndoStack

from electrogridy.commands.layers import AddLayerCommand, ChangeLayerCommand, RemoveLayerCommand
from electrogridy.fileio.json_format import document_to_dict
from electrogridy.model.document import Document
from electrogridy.model.entities import Arc, Line, Polyline, Rectangle, Text
from electrogridy.model.geometry import Point
from electrogridy.model.grips import grip_kinds, grip_points, move_grip
from electrogridy.model.layers import Layer
from electrogridy.tools.coord_input import CoordinateError, parse_coordinate
from factories import sample_entities


def test_mirror_line_vertical_axis():
    line = Line(id="a", p1=Point(1, 0), p2=Point(4, 2))
    m = line.mirrored(Point(5, 0), horizontal=False)
    assert (m.p1, m.p2) == (Point(9, 0), Point(6, 2))


def test_mirror_arc_swaps_and_reflects_angles():
    arc = Arc(id="a", center=Point(0, 0), radius=5, start_angle=10, end_angle=80)
    m = arc.mirrored(Point(0, 0), horizontal=True)
    assert (m.start_angle, m.end_angle) == (280, 350)
    assert m.sweep == arc.sweep
    v = arc.mirrored(Point(0, 0), horizontal=False)
    assert (v.start_angle, v.end_angle) == (100, 170)


def test_mirror_text_keeps_rotation():
    t = Text(id="t", position=Point(2, 3), text="A", rotation=90)
    m = t.mirrored(Point(0, 0), horizontal=False)
    assert m.position == Point(-2, 3) and m.rotation == 90


def test_grips_and_rectangle_corner_drag():
    rect = Rectangle(id="r", p1=Point(0, 0), p2=Point(20, 10))
    assert grip_points(rect)[:4] == [Point(0, 0), Point(20, 0), Point(20, 10), Point(0, 10)]
    moved = move_grip(rect, 2, Point(30, 15))
    assert (moved.p1, moved.p2) == (Point(0, 0), Point(30, 15))
    assert move_grip(rect, 2, Point(0, 15)) is None


def test_rectangle_side_is_shifted_parallel():
    rect = Rectangle(id="r", p1=Point(0, 0), p2=Point(20, 10))
    assert grip_points(rect)[4:] == [Point(10, 0), Point(20, 5), Point(10, 10), Point(0, 5)]
    assert grip_kinds(rect) == ["point"] * 4 + ["segment"] * 4
    right = move_grip(rect, 5, Point(27, 8))  # only across: the side stays upright
    assert (right.p1, right.p2) == (Point(0, 0), Point(27, 10))
    top = move_grip(rect, 4, Point(3, -4))
    assert (top.p1, top.p2) == (Point(0, -4), Point(20, 10))
    assert move_grip(rect, 7, Point(20, 1)) is None  # left onto right: nothing left


def test_polyline_side_is_shifted_parallel():
    open_ = Polyline(id="p", points=(Point(0, 0), Point(10, 0), Point(10, 10)))
    assert grip_points(open_)[3:] == [Point(5, 0), Point(10, 5)]
    moved = move_grip(open_, 4, Point(14, 2))  # the vertical side to x = 14
    assert moved.points == (Point(0, 0), Point(14, 0), Point(14, 10))
    closed = Polyline(id="q", points=(Point(0, 0), Point(10, 0), Point(10, 10)), closed=True)
    assert len(grip_points(closed)) == 6  # the closing side too
    moved = move_grip(closed, 5, Point(0, 10))  # the slanted side through (0, 10)
    a, b = moved.points[2], moved.points[0]
    assert b.x - a.x == pytest.approx(-10) and b.y - a.y == pytest.approx(-10)  # parallel
    assert a.x - a.y == pytest.approx(-10)  # (0, 10) lies on it
    assert moved.points[1] == Point(10, 0)


def test_arc_grip_changes_angle_only():
    arc = Arc(id="a", center=Point(0, 0), radius=5, start_angle=0, end_angle=90)
    moved = move_grip(arc, 1, Point(-10, 0))
    assert moved.end_angle == 180 and moved.radius == 5


def test_circle_and_text_grip_moves_entity():
    for e in sample_entities():
        if e.id in ("c1", "t1"):
            ref = grip_points(e)[0]
            moved = move_grip(e, 0, Point(ref.x + 3, ref.y))
            assert grip_points(moved)[0] == Point(ref.x + 3, ref.y)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10,20", Point(10, 20)),
        ("10.5,-2", Point(10.5, -2)),
        ("10,5;2,25", Point(10.5, 2.25)),
        ("@5,-5", Point(15, 15)),
        ("@1,5;0", Point(11.5, 20)),
    ],
)
def test_parse_coordinates(text, expected):
    assert parse_coordinate(text, Point(10, 20), None) == expected


def test_parse_length_needs_ortho_direction():
    assert parse_coordinate("25", Point(10, 20), (0.0, -1.0)) == Point(10, -5)
    assert parse_coordinate("2.5", Point(0, 0), (1.0, 0.0)) == Point(2.5, 0)
    # A comma always means a point; lengths use a decimal point.
    assert parse_coordinate("2,5", Point(0, 0), (1.0, 0.0)) == Point(2, 5)
    with pytest.raises(CoordinateError):
        parse_coordinate("25", Point(10, 20), None)
    with pytest.raises(CoordinateError):
        parse_coordinate("@1,1", None, None)
    with pytest.raises(CoordinateError):
        parse_coordinate("a,b", None, None)


def make_doc() -> Document:
    doc = Document.new("Blatt 1")
    doc.layers.append(Layer("Kabel", color="#0000ff"))
    for e in sample_entities():
        doc.model_space.add(e)
    doc.model_space.add(Line(id="k1", layer="Kabel", p1=Point(0, 0), p2=Point(1, 1)))
    return doc


def check_do_undo_redo(doc, command):
    stack = QUndoStack()
    before = document_to_dict(doc)
    stack.push(command)
    after = document_to_dict(doc)
    assert after != before
    stack.undo()
    assert document_to_dict(doc) == before
    stack.redo()
    assert document_to_dict(doc) == after


def test_add_layer_command():
    doc = make_doc()
    check_do_undo_redo(doc, AddLayerCommand(doc, Layer("Neu"), "add"))


def test_remove_unused_layer_command():
    doc = make_doc()
    doc.layers.append(Layer("Leer"))
    check_do_undo_redo(doc, RemoveLayerCommand(doc, "Leer", "remove"))


def test_remove_layer_in_use_or_zero_is_refused():
    doc = make_doc()
    with pytest.raises(ValueError):
        RemoveLayerCommand(doc, "Kabel", "remove")
    with pytest.raises(ValueError):
        doc.remove_layer("0")


def test_change_layer_properties():
    doc = make_doc()
    new = Layer("Kabel", color="#ff0000", lineweight=0.5, visible=False)
    check_do_undo_redo(doc, ChangeLayerCommand(doc, "Kabel", new, "change"))


def test_rename_layer_moves_entities():
    doc = make_doc()
    cmd = ChangeLayerCommand(doc, "Kabel", Layer("Leitungen", color="#0000ff"), "rename")
    check_do_undo_redo(doc, cmd)
    assert doc.model_space.get("k1").layer == "Leitungen"
    assert not doc.has_layer("Kabel")


def test_layer_listeners_fire():
    doc = make_doc()
    calls = []
    doc.subscribe_layers(lambda: calls.append(1))
    doc.insert_layer(1, Layer("X"))
    doc.remove_layer("X")
    assert calls == [1, 1]
