import pytest
from PyQt6.QtCore import QSettings

from sldgridy.commands.sheets import ChangeSheetCommand
from sldgridy.fileio.json_format import document_from_dict, document_to_dict
from sldgridy.model.dimensions import measured_text
from sldgridy.model.document import DOC_PROJECT, Document
from sldgridy.model.entities import BlockReference, Dimension
from sldgridy.model.geometry import Point
from sldgridy.model.paper import Orientation
from sldgridy.tools.coord_input import parse_coordinate
from sldgridy.tools.dynamic_input import DynamicInput
from sldgridy.ui.main_window import MainWindow
from sldgridy.ui.page_dialog import PageDialog, PageSpec


def test_typed_lengths_are_real_millimetres_on_a_scaled_page():
    d = DynamicInput(mode="polar", scale=0.2)
    for char in "600":
        d.type(char)
    assert d.constrain(Point(0, 0), Point(50, 0)) == Point(120, 0)
    assert d.shown(Point(0, 0), Point(120, 0), True)["length"] == "600"
    size = DynamicInput(mode="size", scale=0.2)
    assert size.shown(Point(0, 0), Point(120, 160), True) == {"width": "600", "height": "800"}
    assert parse_coordinate("@600,0", Point(10, 10), None, 0.2) == Point(130, 10)
    assert parse_coordinate("40,50", Point(10, 10), None, 0.2) == Point(40, 50)  # on the page


def test_dimension_shows_the_real_length_and_files_keep_scales():
    d = Dimension(id="d", p1=Point(0, 0), p2=Point(120, 0), position=Point(60, -10), factor=5)
    assert measured_text(d) == "600"
    doc = Document.new("Blatt 1", kind=DOC_PROJECT)
    doc.sheets[0].scale = 0.2
    doc.sheets[0].entities.add(d)
    loaded = document_from_dict(document_to_dict(doc))
    assert loaded.sheets[0].scale == 0.2
    assert loaded.sheets[0].entities.get("d").factor == 5


def test_page_dialog_offers_the_scale(qapp):
    spec = PageSpec("enclosure", "", "", "", "A3", Orientation.LANDSCAPE, False, 0.2)
    dialog = PageDialog("Seite bearbeiten", spec, [], [], new=False)
    assert dialog.scale.currentText() == "1:5"
    dialog.scale.setCurrentText("1:10")
    assert dialog.spec().scale == pytest.approx(0.1)


@pytest.fixture
def window(qapp, monkeypatch):
    from sldgridy.ui.block_dialogs import AttributeValuesDialog

    QSettings().clear()
    monkeypatch.setattr(AttributeValuesDialog, "exec", lambda self: 1)
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w._set_document(Document.new("Blatt 1", kind=DOC_PROJECT), None)
    w.sheets.show_sheet(w.document.sheets[0].id)
    qapp.processEvents()
    yield w
    for space in w.spaces():
        space.stack.setClean()
    w.undo_stack.setClean()
    w.close()


def test_symbols_and_dimensions_follow_the_page_scale(window):
    from sldgridy.fileio.paths import system_library_dir

    page = window.document.sheets[0]
    window.push(ChangeSheetCommand(window.document, page.id, "", scale=0.2))
    assert window.drawing_scale() == 0.2
    library = str(system_library_dir() / "din_en_60617.sldglib")
    window.blocks.insert_from_source(library, "Schmelzsicherung", Point(100, 100))
    (ref,) = [e for e in window.container if isinstance(e, BlockReference)]
    assert ref.scale == pytest.approx(0.2)
    window.act_dimension.trigger()
    tool = window.tools.active
    for p in (Point(50, 50), Point(170, 50), Point(110, 40)):
        tool.pick(p)
    (dim,) = [e for e in window.container if isinstance(e, Dimension)]
    assert measured_text(dim) == "600"
    # Back to 1:1: new symbols at full size again.
    window.push(ChangeSheetCommand(window.document, page.id, "", scale=1.0))
    assert window.drawing_scale() == 1.0


def test_changing_the_scale_rescales_what_is_drawn(window, monkeypatch):
    from dataclasses import replace

    from sldgridy.model.entities import Rectangle, Text

    page = window.document.sheets[0]
    box = Rectangle(id="box", p1=Point(50, 50), p2=Point(650, 850))
    label = Text(id="t", position=Point(60, 40), text="Gehäuse", height=3.5)
    dim = Dimension(id="d", p1=Point(50, 50), p2=Point(650, 50), position=Point(350, 45))
    ref = BlockReference(id="r", name="X", insert=Point(250, 250))
    for e in (box, label, dim, ref):
        page.entities.add(e)
    current = window.sheets.current_sheet()
    spec = PageSpec(current.kind or "enclosure", "", "", "", "A3", Orientation.LANDSCAPE, False)
    monkeypatch.setattr(window.sheets, "_page_spec", lambda *a: replace(spec, scale=0.2))
    window.sheets.rename_sheet()
    assert page.scale == 0.2
    corner = Point(50, 40)  # upper left of the content
    new_box = page.entities.get("box")
    assert (new_box.p1, new_box.p2) == (
        Point(corner.x, corner.y + 2), Point(corner.x + 120, corner.y + 162)
    )  # fmt: skip
    assert page.entities.get("t").height == 3.5  # stays readable on paper
    assert measured_text(page.entities.get("d")) == "600"  # same real length
    assert page.entities.get("r").scale == pytest.approx(0.2)
    window.act_undo.trigger()  # one step back
    assert page.scale == 1.0 and page.entities.get("box") == box
