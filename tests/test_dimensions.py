import pytest

from electrogridy.model.dimensions import (
    auto_orientation,
    dimension_geometry,
    format_value,
    measured,
)
from electrogridy.model.entities import Dimension, Line, Text
from electrogridy.model.geometry import Point


def dim(p1, p2, pos, orientation="aligned", **kw):
    return Dimension(
        id="d", p1=Point(*p1), p2=Point(*p2), position=Point(*pos), orientation=orientation, **kw
    )


def test_measured_values():
    assert measured(dim((0, 0), (30, 40), (0, 0))) == pytest.approx(50)
    assert measured(dim((0, 0), (30, 40), (0, -10), "horizontal")) == pytest.approx(30)
    assert measured(dim((0, 0), (30, 40), (-10, 0), "vertical")) == pytest.approx(40)
    assert format_value(1250.0) == "1250"
    assert format_value(12.5) == "12,5" and format_value(12.5, decimal_comma=False) == "12.5"


def test_horizontal_dimension_above_two_points():
    parts = dimension_geometry(dim((0, 0), (100, 20), (50, -15), "horizontal"))
    line = next(p for p in parts if p.id == "d:line")
    assert line.p1 == Point(0, -15) and line.p2 == Point(100, -15)
    text = next(p for p in parts if isinstance(p, Text))
    assert text.text == "100" and text.rotation == 0
    assert text.position.y < -15  # above the dimension line
    exts = [p for p in parts if p.id.startswith("d:ext")]
    assert len(exts) == 2
    # Extension lines run a little past the dimension line (upwards here).
    assert min(e.p2.y for e in exts) < -15
    arrows = [p for p in parts if p.id.startswith("d:arrow")]
    assert len(arrows) == 4 and all(isinstance(a, Line) for a in arrows)


def test_vertical_value_reads_from_the_right_and_override_text():
    parts = dimension_geometry(dim((0, 0), (0, 80), (-20, 40), "vertical", text="ca. 8 m"))
    text = next(p for p in parts if isinstance(p, Text))
    assert text.text == "ca. 8 m" and text.rotation == 90


def test_auto_orientation_follows_the_dragged_side():
    p1, p2 = Point(0, 0), Point(100, 50)
    assert auto_orientation(p1, p2, Point(50, -20)) == "horizontal"  # above
    assert auto_orientation(p1, p2, Point(130, 25)) == "vertical"  # right of both
    assert auto_orientation(Point(0, 0), Point(0, 50), Point(50, 50)) == "vertical"


def test_rotating_a_dimension_swaps_its_orientation():
    d = dim((0, 0), (100, 0), (50, -10), "horizontal")
    turned = d.rotated(Point(0, 0), 1)
    assert turned.orientation == "vertical"
    assert measured(turned) == pytest.approx(100)


def test_dimension_height_follows_the_viewport_scale():
    from dataclasses import replace

    from electrogridy.model.dimensions import default_height
    from electrogridy.model.document import Document

    doc = Document.new("Blatt 1")
    sheet = doc.sheets[0]
    vp = sheet.viewports()[0]
    sheet.entities.replace(replace(vp, scale=0.02))  # 1:50
    a, b = sheet.entities.get(vp.id).model_rect()
    inside = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
    assert default_height(doc.sheets, inside) == pytest.approx(125)  # 2.5 mm on paper
    assert default_height(doc.sheets, Point(b.x + 1e6, 0)) == pytest.approx(2.5)


@pytest.mark.parametrize(
    ("p1", "p2"),
    [
        ((0, 0), (40, -60)),
        ((40, -60), (0, 0)),
        ((40, -60), (80, 0)),
        ((80, 0), (40, -60)),
        ((0, 0), (0, -50)),
        ((0, -50), (0, 0)),
        ((0, 0), (-50, 0)),
    ],
)
def test_value_is_never_upside_down(p1, p2):
    d = dim(p1, p2, ((p1[0] + p2[0]) / 2 - 10, (p1[1] + p2[1]) / 2))
    (text,) = [e for e in dimension_geometry(d) if e.id.endswith(":text")]
    assert -90 < text.rotation <= 90


def angle_dim(position, p1=(50, 0), p2=(30, -40)):
    return Dimension(
        id="a",
        p1=Point(*p1),
        p2=Point(*p2),
        position=Point(*position),
        orientation="angular",
        vertex=Point(0, 0),
    )


def test_angle_between_legs_and_across_the_vertex():
    from electrogridy.model.dimensions import measured_text

    assert measured(angle_dim((20, -10))) == pytest.approx(53.130102)
    assert measured_text(angle_dim((20, -10))) == "53,1°"
    # Dragged to the other side of a leg: the supplementary angle.
    assert measured(angle_dim((-20, -20))) == pytest.approx(180 - 53.130102)
    # Across the vertex: the opposite angle, same size.
    assert measured(angle_dim((-20, 10))) == pytest.approx(53.130102)


def test_angle_geometry_arc_arrows_and_text():
    from electrogridy.model.entities import Arc

    d = angle_dim((20, -10))
    parts = dimension_geometry(d)
    (arc,) = [p for p in parts if isinstance(p, Arc)]
    assert arc.radius == pytest.approx(22.36068, abs=1e-4)
    assert (arc.start_angle, arc.end_angle) == pytest.approx((0, 53.130102))
    assert len([p for p in parts if ":arrow" in p.id]) == 4
    (text,) = [p for p in parts if isinstance(p, Text)]
    assert text.text == "53,1°" and -90 < text.rotation <= 90
    # The arc is inside both legs (50 mm long): no extension lines.
    assert not [p for p in parts if ":ext" in p.id]
    far = dimension_geometry(angle_dim((80, -40)))
    assert len([p for p in far if ":ext" in p.id]) == 2


def test_angle_dimension_follows_moves_rotation_and_mirroring():
    from electrogridy.model.rotate import rotate_entity

    d = angle_dim((20, -10))
    moved = d.translated(10, 5)
    assert moved.vertex == Point(10, 5) and measured(moved) == pytest.approx(measured(d))
    turned = rotate_entity(d, Point(0, 0), 30)
    assert turned.orientation == "angular" and measured(turned) == pytest.approx(measured(d))
    assert measured(d.rotated(Point(0, 0), 1)) == pytest.approx(measured(d))
    assert measured(d.mirrored(Point(0, 0), True)) == pytest.approx(measured(d))
