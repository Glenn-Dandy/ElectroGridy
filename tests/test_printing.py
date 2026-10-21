import re
import zlib

import pytest
from PyQt6.QtGui import QImage

from sldgridy.model.document import Document, new_sheet
from sldgridy.model.entities import Line, Text
from sldgridy.model.geometry import Point
from sldgridy.model.layers import Layer
from sldgridy.model.paper import Orientation
from sldgridy.printing.layout import (
    Mode,
    fit,
    fit_rect,
    frame_clipped,
    one_to_one,
    tile_count,
    tiles,
)
from sldgridy.printing.output import Job, export_pdf, export_png, export_svg, plan, sheet_image
from sldgridy.view.display import OutputOptions

A4 = (210.0, 297.0)
A3 = (297.0, 420.0)
PT_PER_MM = 72 / 25.4
OUT = OutputOptions(helpers=False)


def test_one_to_one_page_is_sheet():
    (page,) = one_to_one(1189, 841)
    assert (page.width, page.height, page.scale) == (1189, 841, 1.0)


def test_fit_a0_on_a3_turns_paper_and_centres():
    (page,) = fit(1189, 841, *A3)
    assert (page.width, page.height) == (420, 297)
    assert page.scale == pytest.approx(297 / 841)
    x, y = page.to_page(1189 / 2, 841 / 2)
    assert x == pytest.approx(210) and y == pytest.approx(148.5)


def test_tiles_a0_on_a4():
    # Portrait A4: columns ceil((1189-10)/200) = 6, rows ceil((841-10)/287) = 3.
    assert tile_count(1189, 841, 210, 297, 10) == (3, 6)
    pages = tiles(1189, 841, *A4)
    assert len(pages) == 18
    assert (pages[0].width, pages[0].height) == A4
    assert [p.tile for p in pages[:7]] == [(1, c) for c in range(1, 7)] + [(2, 1)]
    second = pages[1]
    assert (second.origin_x, second.origin_y) == (200, 0)
    assert second.cut_x == [5, 205] and second.cut_y == [292]
    last = pages[-1]
    assert (last.origin_x, last.origin_y) == (1000, 574)
    assert last.origin_x + last.width >= 1189 and last.origin_y + last.height >= 841
    assert last.cut_x == [5] and last.cut_y == [5]


def test_tiles_a0_on_a3_choose_landscape():
    # The orientation needing fewer sheets wins: landscape A3 needs 3 x 3 = 9.
    portrait = tile_count(1189, 841, 297, 420, 10)
    landscape = tile_count(1189, 841, 420, 297, 10)
    pages = tiles(1189, 841, *A3)
    assert len(pages) == min(portrait[0] * portrait[1], landscape[0] * landscape[1])
    assert len(pages) == 9
    # Neighbouring tiles overlap by 10 mm.
    assert pages[1].origin_x - pages[0].origin_x == pages[0].width - 10


def test_tiles_cover_whole_sheet():
    for paper in (A4, A3):
        pages = tiles(1189, 841, *paper)
        assert max(p.origin_x + p.width for p in pages) >= 1189
        assert max(p.origin_y + p.height for p in pages) >= 841


def test_quick_print_fit():
    page = fit_rect(100, 50, 300, 100, *A4)
    assert (page.width, page.height) == (297, 210)
    assert page.scale == pytest.approx(277 / 300)
    assert page.to_page(250, 100) == pytest.approx((148.5, 105))


def test_frame_clipped_warning():
    (page,) = one_to_one(1189, 841)
    assert not frame_clipped(page, (5, 5, 5, 5))
    assert frame_clipped(page, (5, 12, 5, 5))
    (small,) = fit(1189, 841, *A4)
    assert frame_clipped(small, (4.2, 4.2, 4.2, 4.2))


def sample_doc() -> Document:
    doc = Document.new("Blatt 1")
    doc.model_space.add(Line(id="l", p1=Point(0, 0), p2=Point(100, 0)))
    doc.model_space.add(Text(id="t", position=Point(0, 20), text="Wechselrichter"))
    doc.insert_sheet(1, new_sheet("Blatt 2", "A3", Orientation.PORTRAIT))
    return doc


def pdf_pages(path) -> list[tuple[float, float]]:
    data = path.read_bytes()
    boxes = re.findall(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", data)
    return [(float(w) / PT_PER_MM, float(h) / PT_PER_MM) for w, h in boxes]


def pdf_text_operators(path) -> bool:
    data = path.read_bytes()
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            content = zlib.decompress(m.group(1))
        except zlib.error:
            content = m.group(1)
        if b"BT" in content and (b"Tj" in content or b"TJ" in content):
            return True
    return False


def test_pdf_a0_landscape_page_size(qapp, tmp_path):
    doc = sample_doc()
    path = tmp_path / "plan.pdf"
    assert export_pdf(path, doc, doc.sheets[:1], OUT) == 1
    (size,) = pdf_pages(path)
    assert size == pytest.approx((1189, 841), abs=0.5)


def test_pdf_two_sheets_two_pages_and_text_stays_text(qapp, tmp_path):
    doc = sample_doc()
    path = tmp_path / "plan.pdf"
    assert export_pdf(path, doc, doc.sheets, OUT) == 2
    sizes = pdf_pages(path)
    assert sizes == [pytest.approx((1189, 841), abs=0.5), pytest.approx((297, 420), abs=0.5)]
    assert pdf_text_operators(path)


def test_plan_modes(qapp):
    doc = sample_doc()
    assert len(plan(doc, Job(doc.sheets, Mode.ONE_TO_ONE))) == 2
    assert len(plan(doc, Job(doc.sheets[:1], Mode.FIT, A3))) == 1
    assert len(plan(doc, Job(doc.sheets[:1], Mode.TILES, A4))) == 18
    ((sheet, page),) = plan(doc, Job([], paper=A4, model=True))
    assert sheet is None and page.scale > 1


def test_svg_export_in_mm(qapp, tmp_path):
    doc = sample_doc()
    path = tmp_path / "plan.svg"
    export_svg(path, doc, doc.sheets[0], OUT)
    text = path.read_text(encoding="utf-8")
    assert 'viewBox="0 0 1189 841"' in text
    assert re.search(r'width="118\.9cm"|width="1189mm"|width="11890"', text)


def test_png_resolution(qapp, tmp_path):
    doc = sample_doc()
    path = tmp_path / "plan.png"
    export_png(path, doc, doc.sheets[1], 100, OUT)
    image = QImage(str(path))
    assert (image.width(), image.height()) == (round(297 / 25.4 * 100), round(420 / 25.4 * 100))


def _dark_pixels(image: QImage) -> int:
    count = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if image.pixelColor(x, y).lightness() < 128:
                count += 1
    return count


def test_non_printable_layer_left_out(qapp):
    doc = Document.new("Blatt 1")
    doc.layers.append(Layer("Hilf", printable=False))
    doc.sheets[0].title_block = ""
    doc.model_space.add(
        Line(id="l", layer="Hilf", p1=Point(10, 10), p2=Point(200, 10), lineweight=2)
    )
    with_layer = sheet_image(doc, doc.sheets[0], 20, OutputOptions(helpers=False))
    without = sheet_image(doc, doc.sheets[0], 20, OutputOptions(helpers=False, printable_only=True))
    assert _dark_pixels(with_layer) > _dark_pixels(without)


def test_monochrome_turns_colours_black(qapp):
    doc = Document.new("Blatt 1")
    doc.sheets[0].title_block = ""
    doc.model_space.add(
        Line(id="l", color="#ff0000", p1=Point(10, 10), p2=Point(400, 10), lineweight=3)
    )
    color = sheet_image(doc, doc.sheets[0], 20, OutputOptions(helpers=False))
    mono = sheet_image(doc, doc.sheets[0], 20, OutputOptions(helpers=False, monochrome=True))
    y = round((10 + 10) / 25.4 * 20)
    x = round((20 + 100) / 25.4 * 20)
    assert color.pixelColor(x, y).red() > 200
    assert mono.pixelColor(x, y).red() < 60


def test_line_widths_in_a_viewport_are_paper_widths(qapp, monkeypatch):
    from dataclasses import replace

    from PyQt6.QtGui import QImage, QPainter

    from sldgridy.model.document import Document
    from sldgridy.model.entities import Line
    from sldgridy.model.geometry import Point
    from sldgridy.view import display

    doc = Document.new("Blatt 1")
    doc.model_space.add(Line(id="l", p1=Point(0, 0), p2=Point(1000, 0), lineweight=0.5))
    sheet = doc.sheets[0]
    vp = replace(sheet.viewports()[0], scale=0.02)  # 1:50
    seen = []
    monkeypatch.setattr(
        display, "paint_entity", lambda painter, e, style, *a: seen.append(style.lineweight)
    )
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    display.paint_viewport(painter, doc, vp, 0, display.OutputOptions(helpers=False))
    painter.end()
    # 0.5 mm on paper is 25 mm in the model at 1:50.
    assert seen == [pytest.approx(25.0)]


def test_pdf_of_circuit_diagram_pages_is_a4_landscape(qapp, tmp_path):
    from sldgridy.model.document import CIRCUIT, PARTS, new_page
    from sldgridy.model.sheet import schematic_title_width
    from sldgridy.model.title_block import schematic_title_block_definition

    doc = sample_doc()
    pages = [new_page(CIRCUIT, "Einspeisung", "PV1", "UV1"), new_page(PARTS)]
    width = schematic_title_width(*pages[0].size)
    definition = schematic_title_block_definition(width)
    doc.blocks[definition.name] = definition
    for page in pages:
        page.title_block = definition.name
        doc.sheets.append(page)
    path = tmp_path / "plan.pdf"
    assert export_pdf(path, doc, pages, OUT) == 2
    assert pdf_pages(path) == [pytest.approx((297, 210), abs=0.5)] * 2
    assert pdf_text_operators(path)  # column numbers, title block and list are text
