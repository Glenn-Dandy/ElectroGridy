import math

import pytest

from electrogridy.fileio.dxf import DxfError, read_dxf
from electrogridy.model.entities import (
    Arc,
    AttributeDefinition,
    Circle,
    ConnectionPoint,
    Line,
    Polyline,
    Text,
)
from electrogridy.model.geometry import Point


def dxf(*sections: str) -> str:
    return "".join(sections) + "0\nEOF\n"


def section(name: str, body: str) -> str:
    return f"0\nSECTION\n2\n{name}\n{body}0\nENDSEC\n"


def header(units: int) -> str:
    return section("HEADER", f"9\n$INSUNITS\n70\n{units}\n")


def ent(kind: str, *tags) -> str:
    out = f"0\n{kind}\n8\n0\n"
    for code, value in tags:
        out += f"{code}\n{value}\n"
    return out


def block(name: str, body: str, base=(0, 0), flags=0) -> str:
    return (
        f"0\nBLOCK\n8\n0\n2\n{name}\n70\n{flags}\n10\n{base[0]}\n20\n{base[1]}\n30\n0\n"
        + body
        + "0\nENDBLK\n8\n0\n"
    )


def write(tmp_path, text, name="sym.dxf"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def kinds(definition, cls):
    return [e for e in definition.entities if isinstance(e, cls)]


def test_block_with_line_circle_attdef_and_point(tmp_path):
    body = (
        ent("LINE", (10, 0), (20, 0), (11, 0), (21, -10))
        + ent("CIRCLE", (10, 0), (20, -5), (40, 2))
        + ent(
            "ATTDEF", (10, 5), (20, -5), (40, 2.5), (1, "-F1"), (2, "bmk"), (3, "Kennz."), (70, 0)
        )
        + ent("POINT", (10, 0), (20, 0))
        + ent("POINT", (10, 0), (20, -10))
    )
    path = write(tmp_path, dxf(header(4), section("BLOCKS", block("Sicherung", body))))
    result = read_dxf(path)
    (d,) = result.blocks
    assert d.name == "Sicherung" and d.base_point == Point(0, 0)
    (line,) = kinds(d, Line)
    assert (line.p1, line.p2) == (Point(0, 0), Point(0, 10))  # Y flipped: DXF -10 is below
    (circle,) = kinds(d, Circle)
    assert circle.center == Point(0, 5) and circle.radius == 2
    (att,) = kinds(d, AttributeDefinition)
    assert (att.tag, att.default, att.prompt, att.height) == ("BMK", "-F1", "Kennz.", 2.5)
    cps = {c.name: (c.position, c.direction) for c in kinds(d, ConnectionPoint)}
    assert cps == {"1": (Point(0, 0), 90), "2": (Point(0, 10), 270)}


def test_units_inch_and_skipped_entities(tmp_path):
    body = ent("LINE", (10, 0), (20, 0), (11, 1), (21, 0)) + ent("SPLINE", (70, 8))
    result = read_dxf(write(tmp_path, dxf(header(1), section("BLOCKS", block("B", body)))))
    (line,) = kinds(result.blocks[0], Line)
    assert line.p2 == Point(25.4, 0)
    assert result.skipped == {"SPLINE": 1} and result.units == "Zoll"


def test_arc_angles_survive_y_flip(tmp_path):
    body = ent("ARC", (10, 0), (20, 0), (40, 5), (50, 0), (51, 90))
    (d,) = read_dxf(write(tmp_path, dxf(section("BLOCKS", block("A", body))))).blocks
    (arc,) = kinds(d, Arc)
    assert (arc.start_angle, arc.end_angle, arc.radius) == (0, 90, 5)
    # The DXF point (0, 5) at 90 degrees lies above the centre, i.e. at y = -5 here.
    end = Point(arc.center.x, arc.center.y - arc.radius)
    assert end == Point(0, -5)


def test_lwpolyline_with_bulge_becomes_line_and_arc(tmp_path):
    bulge = math.tan(math.radians(90) / 4)  # 90 degree counter-clockwise arc
    body = ent(
        "LWPOLYLINE",
        (90, 3),
        (70, 0),
        (10, 0),
        (20, 0),
        (42, 0),
        (10, 10),
        (20, 0),
        (42, bulge),
        (10, 20),
        (20, 10),
    )
    (d,) = read_dxf(write(tmp_path, dxf(section("BLOCKS", block("P", body))))).blocks
    (line,) = kinds(d, Line)
    (arc,) = kinds(d, Arc)
    assert (line.p1, line.p2) == (Point(0, 0), Point(10, 0))
    assert arc.center.x == pytest.approx(10) and arc.center.y == pytest.approx(-10)
    assert arc.radius == pytest.approx(10)
    assert arc.start_angle == pytest.approx(270) and arc.end_angle == pytest.approx(0, abs=1e-6)


def test_plain_closed_polyline(tmp_path):
    body = ent("LWPOLYLINE", (90, 3), (70, 1), (10, 0), (20, 0), (10, 5), (20, 0), (10, 5), (20, 5))
    (d,) = read_dxf(write(tmp_path, dxf(section("BLOCKS", block("P", body))))).blocks
    (poly,) = kinds(d, Polyline)
    assert poly.closed and poly.points == (Point(0, 0), Point(5, 0), Point(5, -5))


def test_text_and_mtext(tmp_path):
    body = ent("TEXT", (10, 1), (20, 2), (40, 3.5), (1, "M"), (50, 90)) + ent(
        "MTEXT", (10, 0), (20, 0), (40, 2.5), (71, 5), (1, "{\\fArial;Zeile 1}\\PZeile 2")
    )
    (d,) = read_dxf(write(tmp_path, dxf(section("BLOCKS", block("T", body))))).blocks
    t1, t2 = kinds(d, Text)
    assert (t1.text, t1.position, t1.height, t1.rotation) == ("M", Point(1, -2), 3.5, 90)
    assert t2.text == "Zeile 1\nZeile 2" and (t2.halign, t2.valign) == ("center", "middle")


def test_nested_insert_is_resolved_and_mirrored(tmp_path):
    inner = ent("LINE", (10, 0), (20, 0), (11, 10), (21, 0)) + ent("ATTDEF", (2, "X"), (1, ""))
    outer = ent("INSERT", (2, "Inner"), (10, 5), (20, 0), (41, -1), (42, 1), (50, 0))
    text = dxf(section("BLOCKS", block("Inner", inner) + block("Outer", outer)))
    blocks = {b.name: b for b in read_dxf(write(tmp_path, text)).blocks}
    (line,) = kinds(blocks["Outer"], Line)
    assert {line.p1, line.p2} == {Point(5, 0), Point(-5, 0)}
    assert not kinds(blocks["Outer"], AttributeDefinition)  # attributes of nested blocks dropped


def test_model_space_entities_without_blocks(tmp_path):
    text = dxf(section("ENTITIES", ent("LINE", (10, 0), (20, 0), (11, 4), (21, 3))))
    (d,) = read_dxf(write(tmp_path, text, "Mein Symbol.dxf")).blocks
    assert d.name == "Mein Symbol" and d.base_point == Point(0, 0)


def test_special_blocks_are_ignored(tmp_path):
    body = ent("LINE", (10, 0), (20, 0), (11, 1), (21, 0))
    text = dxf(section("BLOCKS", block("*Model_Space", body) + block("Ext", body, flags=4)))
    with pytest.raises(DxfError):
        read_dxf(write(tmp_path, text))


def test_binary_and_garbage_rejected(tmp_path):
    p = tmp_path / "b.dxf"
    p.write_bytes(b"AutoCAD Binary DXF\r\n\x1a\x00")
    with pytest.raises(DxfError):
        read_dxf(p)
    with pytest.raises(DxfError):
        read_dxf(write(tmp_path, "kein\nDXF\n", "x.dxf"))


def test_dxf_import_into_user_library(qapp, tmp_path):
    from PyQt6.QtCore import QSettings

    from electrogridy.fileio.files import load_library
    from electrogridy.ui.main_window import MainWindow

    QSettings().clear()
    body = ent("LINE", (10, 0), (20, 0), (11, 0), (21, -10)) + ent("POINT", (10, 0), (20, 0))
    text = dxf(section("BLOCKS", block("Trenner", body) + block("Zweiter", body)))
    path = write(tmp_path, text, "Hersteller Symbole.dxf")
    w = MainWindow()
    try:
        target = w.blocks.import_dxf_file(path, ask=False)
        assert target.name == "Hersteller_Symbole.grdylib"
        title, defs = load_library(target)
        assert title == "Hersteller Symbole"
        assert {d.name for d in defs} == {"Trenner", "Zweiter"}
        assert all(d.category == "Hersteller Symbole" for d in defs)
        assert w.library_dock.source.currentData() == str(target)
        assert w.library_dock.list.count() == 2
        # Importing again merges into the same file.
        assert w.blocks.import_dxf_file(path, ask=False) == target
        assert len(load_library(target)[1]) == 2
    finally:
        w.close()


def test_ellipse_as_circle_or_polyline(tmp_path):
    body = ent(
        "ELLIPSE", (10, 0), (20, 0), (11, 4), (21, 0), (40, 1.0), (41, 0), (42, 6.283185307179586)
    ) + ent(
        "ELLIPSE", (10, 20), (20, 0), (11, 4), (21, 0), (40, 0.5), (41, 0), (42, 6.283185307179586)
    )
    (d,) = read_dxf(write(tmp_path, dxf(section("BLOCKS", block("E", body))))).blocks
    (circle,) = kinds(d, Circle)
    assert circle.radius == 4
    (poly,) = kinds(d, Polyline)
    assert poly.closed
    ys = [p.y for p in poly.points]
    xs = [p.x for p in poly.points]
    assert max(xs) == pytest.approx(24) and min(xs) == pytest.approx(16)
    assert max(ys) == pytest.approx(2, abs=0.01) and min(ys) == pytest.approx(-2, abs=0.01)


def test_model_space_drawing_next_to_a_dimension_arrow_block(tmp_path):
    # Device drawings carry "_Closed" (the dimension arrow) as their only block.
    arrow = ent("LINE", (10, 0), (20, 0), (11, -1), (21, 0.2))
    drawing = ent("LINE", (10, 0), (20, 0), (11, 40), (21, 0)) + ent(
        "CIRCLE", (10, 20), (20, 10), (40, 3)
    )
    text = dxf(section("BLOCKS", block("_Closed", arrow)), section("ENTITIES", drawing))
    (d,) = read_dxf(write(tmp_path, text, "UMG604EP.dxf")).blocks
    assert d.name == "UMG604EP" and kinds(d, Line) and kinds(d, Circle)


def test_model_space_of_inserts_only_keeps_the_blocks(tmp_path):
    body = ent("LINE", (10, 0), (20, 0), (11, 1), (21, 0))
    inserts = ent("INSERT", (2, "_Sym"), (10, 0), (20, 0))
    text = dxf(section("BLOCKS", block("_Sym", body)), section("ENTITIES", inserts))
    assert [b.name for b in read_dxf(write(tmp_path, text)).blocks] == ["_Sym"]
