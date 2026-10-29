import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtPrintSupport import QPrinter

from electrogridy.model.document import new_sheet
from electrogridy.model.entities import Line
from electrogridy.model.geometry import Point
from electrogridy.printing.layout import Mode
from electrogridy.ui.main_window import MainWindow
from electrogridy.ui.print_dialog import PrintDialog
from electrogridy.view.display import OutputOptions


@pytest.fixture
def window(qapp):
    QSettings().clear()
    w = MainWindow()
    w.show()
    qapp.processEvents()
    w.document.model_space.add(Line(id="l", p1=Point(0, 0), p2=Point(300, 100)))
    yield w
    w.undo_stack.setClean()
    w.close()


def pdf_printer(path) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    return printer


def test_dialog_defaults_on_sheet(window, tmp_path):
    window.sheets.tabs.setCurrentIndex(1)
    dialog = PrintDialog(
        window.document, window.sheets.current_sheet(), pdf_printer(tmp_path / "a.pdf")
    )
    job = dialog.job()
    assert [s.name for s in job.sheets] == ["Blatt 1"] and job.mode is Mode.ONE_TO_ONE
    assert not job.model and job.options.printable_only and not job.options.helpers


def test_dialog_in_model_offers_quick_print(window, tmp_path):
    dialog = PrintDialog(window.document, None, pdf_printer(tmp_path / "a.pdf"))
    assert dialog.job().model
    assert not dialog.rb_current.isEnabled()


def test_render_tiles_to_pdf(window, tmp_path):
    path = tmp_path / "kacheln.pdf"
    window.sheets.tabs.setCurrentIndex(1)
    dialog = PrintDialog(window.document, window.sheets.current_sheet(), pdf_printer(path))
    dialog.rb_tiles.setChecked(True)
    dialog.paper.setCurrentIndex(dialog.paper.findText("A3"))
    assert dialog.render_to(dialog.printer) == 9
    assert path.stat().st_size > 1000


def test_selection_of_sheets(window, tmp_path):
    window.document.insert_sheet(1, new_sheet("Blatt 2"))
    dialog = PrintDialog(
        window.document, window.document.sheets[0], pdf_printer(tmp_path / "a.pdf")
    )
    dialog.rb_selection.setChecked(True)
    assert dialog.job().sheets == []
    assert not dialog.btn_print.isEnabled()
    dialog.sheet_list.item(1).setCheckState(dialog.sheet_list.item(1).checkState().Checked)
    assert [s.name for s in dialog.job().sheets] == ["Blatt 2"]
    dialog.rb_all.setChecked(True)
    assert len(dialog.job().sheets) == 2


def test_export_to_files(window, tmp_path):
    window.document.insert_sheet(1, new_sheet("Blatt 2"))
    opts = OutputOptions(helpers=False)
    written = window.export_to("svg", tmp_path / "plan.svg", window.document.sheets, opts)
    assert [p.name for p in written] == ["plan_Blatt_1.svg", "plan_Blatt_2.svg"]
    (pdf,) = window.export_to("pdf", tmp_path / "plan.pdf", window.document.sheets, opts)
    assert pdf.exists()
    (png,) = window.export_to("png", tmp_path / "p.png", window.document.sheets[:1], opts, 50)
    assert png.exists()
