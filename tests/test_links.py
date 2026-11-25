"""References that lead somewhere: double-click in the program, links in the PDF."""

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from electrogridy.fileio.files import load_library
from electrogridy.model.devices import MirrorLine, XRef, crossrefs
from electrogridy.model.document import CIRCUIT, DOC_PROJECT, Document, new_page
from electrogridy.model.entities import BlockReference, InterruptionPoint
from electrogridy.model.geometry import Point

MLD = Path(__file__).parents[1] / "src/electrogridy/resources/library/mld_symbole.grdylib"


def linked_project() -> Document:
    """Cover, coil -K1 and point L1 on page 2, contacts and the other L1 on page 3."""
    doc = Document.new("Deckblatt", kind=DOC_PROJECT)
    doc.sheets += [new_page(CIRCUIT, "Steuerung", "", ""), new_page(CIRCUIT, "Haupt", "", "")]
    doc.blocks.update({b.name: b for b in load_library(MLD)[1]})

    def ref(page, rid, name, x, y):
        doc.sheets[page].entities.add(
            BlockReference(id=rid, name=name, insert=Point(x, y), attributes=(("BMK", "-K1"),))
        )

    ref(1, "coil", "Schützspule", 60, 60)
    ref(2, "main", "Schütz Hauptkontakte 3-polig", 120, 60)
    ref(2, "no", "Schließer", 200, 60)
    doc.sheets[1].entities.add(
        InterruptionPoint(id="ip1", name="L1", position=Point(250, 40), direction=0)
    )
    doc.sheets[2].entities.add(
        InterruptionPoint(id="ip2", name="L1", position=Point(30, 40), direction=180)
    )
    return doc


def test_references_know_their_targets():
    doc = linked_project()
    xr = crossrefs(doc)
    mirror = xr["coil"]
    assert all(isinstance(m, MirrorLine) for m in mirror)
    assert {m.target.entity_id for m in mirror} == {"main", "no"}
    assert mirror[0].target.sheet_id == doc.sheets[2].id
    (back,) = xr["no"]
    assert isinstance(back, XRef) and back == "/2.1"  # still compares as text
    assert back.target.entity_id == "coil"


def test_link_areas_on_a_page(qapp):
    from electrogridy.view.display import sheet_links

    doc = linked_project()
    found = sheet_links(doc, doc.sheets[1])
    targets = {t.entity_id for _, t in found}
    assert targets == {"main", "no", "ip2"}
    assert all(rect.width() > 0 and rect.height() > 0 for rect, _ in found)
    assert sheet_links(doc, doc.sheets[0]) == []


def _annotations(path):
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import resolve1

    with open(path, "rb") as f:
        pages = list(PDFPage.create_pages(PDFDocument(PDFParser(f))))
        ids = [p.pageid for p in pages]
        out = []
        for i, page in enumerate(pages):
            for a in resolve1(page.annots) or []:
                dest = resolve1(resolve1(a)["Dest"])
                out.append((i, ids.index(dest[0].objid)))
        return len(pages), out


@pytest.mark.skipif(
    not __import__("electrogridy.fileio.pdf_import", fromlist=["x"]).available(),
    reason="pdfminer missing",
)
def test_pdf_export_links_references(qapp, tmp_path):
    from electrogridy.printing.output import export_pdf
    from electrogridy.view.display import OutputOptions

    doc = linked_project()
    path = tmp_path / "plan.pdf"
    export_pdf(path, doc, doc.sheets, OutputOptions(helpers=False))
    count, links = _annotations(path)
    assert count == 3
    assert (1, 2) in links and (2, 1) in links  # mirror to the contacts and back
    assert len([1 for page, _ in links if page == 1]) == 3 * 3 + 3 + 1  # poles, NO, L1
    # A page alone: its references lead nowhere in the file and stay plain text.
    alone = tmp_path / "alone.pdf"
    export_pdf(alone, doc, [doc.sheets[1]], OutputOptions(helpers=False))
    assert _annotations(alone) == (1, [])


def test_pdf_links_leave_foreign_files_alone(tmp_path):
    from electrogridy.printing.pdf_links import Link, PdfStructureError, add_links

    path = tmp_path / "other.pdf"
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\nstartxref\n9\n%%EOF\n")
    before = path.read_bytes()
    with pytest.raises(PdfStructureError):
        add_links(path, [[Link(0, 0, 1, 1, 0, 0, 0)]])
    assert path.read_bytes() == before
    assert add_links(path, [[]]) == 0


@pytest.fixture
def window(qapp):
    from electrogridy.ui.main_window import MainWindow

    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w._set_document(linked_project(), None)
    qapp.processEvents()
    yield w
    w.undo_stack.setClean()
    w.close()


def test_double_click_on_a_reference_jumps(window):
    from electrogridy.view.display import sheet_links

    doc = window.document
    window.sheets.show_sheet(doc.sheets[1].id)
    rect, target = next((r, t) for r, t in sheet_links(doc, doc.sheets[1]) if t.entity_id == "no")
    assert window.follow_link_at(rect.center())
    assert window.sheets.current_sheet() is doc.sheets[2]
    assert window.selected_ids() == ["no"]
    back, _ = next((r, t) for r, t in sheet_links(doc, doc.sheets[2]) if t.entity_id == "coil")
    assert window.follow_link_at(back.center())
    assert window.sheets.current_sheet() is doc.sheets[1]
    assert not window.follow_link_at(rect.center() + type(rect.center())(500, 500))


def test_a_new_contact_redraws_its_coil_only(window, qapp):
    from electrogridy.commands.entities import AddEntitiesCommand
    from electrogridy.model.entities import Text

    doc = window.document
    window.sheets.show_sheet(doc.sheets[1].id)
    page = doc.sheets[1]
    page.entities.add(
        BlockReference(
            id="other", name="Schützspule", insert=Point(160, 60), attributes=(("BMK", "-K9"),)
        )
    )
    qapp.processEvents()
    space = window.space
    refreshed = []
    for item in space.sync.items():
        original = item.refresh
        item.refresh = lambda item=item, original=original: (
            refreshed.append(item.entity.id),
            original(),
        )

    def mirror_texts():
        return {p.text for p in space.sync.item("coil")._parts if isinstance(p, Text)}

    before = mirror_texts()
    contact = BlockReference(
        id="nc", name="Öffner", insert=Point(300, 60), attributes=(("BMK", "-K1"),)
    )
    window.push(AddEntitiesCommand(doc.sheets[2].entities, [contact], ""))
    qapp.processEvents()
    assert refreshed == ["coil"]  # -K9 and the other symbols stay as they are
    assert mirror_texts() - before  # the new contact's line in the mirror
