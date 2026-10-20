"""Print dialog: which sheets, 1:1 / fit / tiles, paper, options, preview."""

from collections.abc import Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPageLayout
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo, QPrintPreviewDialog
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from sldgridy.model.document import Document, SheetLayout
from sldgridy.model.paper import PAPER_FORMATS
from sldgridy.printing.layout import Mode, frame_clipped
from sldgridy.printing.output import Job, plan, render
from sldgridy.view.display import OutputOptions

SIZE_TOLERANCE = 1.0  # mm


def printer_supports(printer: QPrinter, width: float, height: float) -> bool:
    """True if the printer offers a paper size of width x height mm (either orientation)."""
    sizes = QPrinterInfo(printer).supportedPageSizes()
    want = sorted((width, height))
    for size in sizes:
        s = size.size(size.Unit.Millimeter)
        have = sorted((s.width(), s.height()))
        if abs(have[0] - want[0]) <= SIZE_TOLERANCE and abs(have[1] - want[1]) <= SIZE_TOLERANCE:
            return True
    return False


def minimum_margins_mm(printer: QPrinter) -> tuple[float, float, float, float]:
    layout = QPageLayout(printer.pageLayout())
    layout.setUnits(QPageLayout.Unit.Millimeter)
    m = layout.minimumMargins()
    return m.left(), m.top(), m.right(), m.bottom()


class PrintDialog(QDialog):
    def __init__(
        self,
        doc: Document,
        current: SheetLayout | None,
        printer: QPrinter | None = None,
        parent=None,
        layouts: list[SheetLayout] | None = None,
        pages: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Drucken"))
        self.doc = doc
        # Sheets of the circuit diagram and drawing, or the pages of the multi-line one.
        self.layouts = list(doc.sheets if layouts is None else layouts)
        self.pages = pages
        self.printer = printer or QPrinter(QPrinter.PrinterMode.HighResolution)

        # What to print.
        self.rb_current = QRadioButton(
            self.tr("Aktuelle Seite") if pages else self.tr("Aktuelles Blatt")
        )
        self.rb_all = QRadioButton(self.tr("Alle Seiten") if pages else self.tr("Alle Blätter"))
        self.rb_selection = QRadioButton(self.tr("Auswahl:"))
        self.rb_model = QRadioButton(self.tr("Modell (Schnelldruck, auf Papier eingepasst)"))
        self.sheet_list = QListWidget()
        for sheet in self.layouts:
            label = f"{doc.page_label(sheet.id)} {sheet.name}".strip() if pages else sheet.name
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, sheet.id)
            self.sheet_list.addItem(item)
        self.sheet_list.setMaximumHeight(110)
        self._current = current
        what = QButtonGroup(self)
        for b in (self.rb_current, self.rb_all, self.rb_selection, self.rb_model):
            what.addButton(b)
        if current is None:
            self.rb_current.setEnabled(False)
            self.rb_model.setChecked(True)
        else:
            self.rb_current.setChecked(True)
        box_what = QGroupBox(self.tr("Bereich"))
        lw = QVBoxLayout(box_what)
        for w in (self.rb_current, self.rb_all, self.rb_selection, self.sheet_list, self.rb_model):
            lw.addWidget(w)
        self.rb_model.setVisible(not pages)  # the multi-line diagram has no model

        # How.
        self.rb_one = QRadioButton(self.tr("1:1 (Blattformat = Papierformat)"))
        self.rb_fit = QRadioButton(self.tr("Einpassen auf Papier"))
        self.rb_tiles = QRadioButton(self.tr("Kacheln (1:1, 10 mm Überlappung)"))
        how = QButtonGroup(self)
        for b in (self.rb_one, self.rb_fit, self.rb_tiles):
            how.addButton(b)
        self.rb_one.setChecked(True)
        self.paper = QComboBox()
        for name in sorted(PAPER_FORMATS, key=lambda n: PAPER_FORMATS[n][0]):
            self.paper.addItem(name, PAPER_FORMATS[name])
        self.paper.setCurrentIndex(max(self.paper.findText("A3"), 0))
        box_how = QGroupBox(self.tr("Modus"))
        lh = QFormLayout(box_how)
        lh.addRow(self.rb_one)
        lh.addRow(self.rb_fit)
        lh.addRow(self.rb_tiles)
        lh.addRow(self.tr("Papier für Einpassen, Kacheln, Schnelldruck:"), self.paper)

        # Options and printer.
        self.cb_mono = QCheckBox(self.tr("Schwarz-weiß"))
        self.cb_printable = QCheckBox(self.tr("Nur druckbare Ebenen"))
        self.cb_printable.setChecked(True)
        self.lbl_printer = QLabel()
        btn_printer = QPushButton(self.tr("Drucker …"))
        btn_printer.clicked.connect(self._choose_printer)
        printer_row = QHBoxLayout()
        printer_row.addWidget(self.lbl_printer, 1)
        printer_row.addWidget(btn_printer)
        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color: #b00000")

        buttons = QDialogButtonBox()
        self.btn_preview = buttons.addButton(
            self.tr("Vorschau …"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.btn_print = buttons.addButton(
            self.tr("Drucken"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        self.btn_print.clicked.connect(self._print)
        self.btn_preview.clicked.connect(self.preview)

        layout = QVBoxLayout(self)
        layout.addWidget(box_what)
        layout.addWidget(box_how)
        layout.addWidget(self.cb_mono)
        layout.addWidget(self.cb_printable)
        layout.addLayout(printer_row)
        layout.addWidget(self.lbl_hint)
        layout.addWidget(buttons)

        for w in (
            self.rb_current,
            self.rb_all,
            self.rb_selection,
            self.rb_model,
            self.rb_one,
            self.rb_fit,
            self.rb_tiles,
        ):
            w.toggled.connect(self._update)
        self.paper.currentIndexChanged.connect(self._update)
        self.sheet_list.itemChanged.connect(self._update)
        self._update()

    # -- state --------------------------------------------------------------

    def sheets(self) -> list[SheetLayout]:
        if self.rb_model.isChecked():
            return []
        if self.rb_current.isChecked() and self._current is not None:
            return [self._current]
        if self.rb_all.isChecked():
            return list(self.layouts)
        ids = {
            self.sheet_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.sheet_list.count())
            if self.sheet_list.item(i).checkState() == Qt.CheckState.Checked
        }
        return [s for s in self.layouts if s.id in ids]

    def mode(self) -> Mode:
        if self.rb_fit.isChecked():
            return Mode.FIT
        if self.rb_tiles.isChecked():
            return Mode.TILES
        return Mode.ONE_TO_ONE

    def options(self) -> OutputOptions:
        return OutputOptions(
            helpers=False,
            monochrome=self.cb_mono.isChecked(),
            printable_only=self.cb_printable.isChecked(),
        )

    def job(self) -> Job:
        return Job(
            sheets=self.sheets(),
            mode=self.mode(),
            paper=tuple(self.paper.currentData()),
            options=self.options(),
            model=self.rb_model.isChecked(),
        )

    def _one_to_one_possible(self, sheets: Sequence[SheetLayout]) -> bool:
        if (
            not self.printer.isValid()
            or self.printer.outputFormat() != QPrinter.OutputFormat.NativeFormat
        ):
            return True
        return all(printer_supports(self.printer, *s.size) for s in sheets)

    def warnings(self) -> list[str]:
        result = []
        job = self.job()
        if not job.model and not job.sheets:
            result.append(self.tr("Kein Blatt ausgewählt."))
            return result
        if (
            self.printer.isValid()
            and self.printer.outputFormat() == QPrinter.OutputFormat.NativeFormat
        ):
            margins = minimum_margins_mm(self.printer)
            pages = plan(self.doc, job)
            if any(frame_clipped(page, margins) for sheet, page in pages if sheet is not None):
                result.append(
                    self.tr(
                        "Der nicht bedruckbare Rand des Druckers ({m:.1f} mm) schneidet in "
                        "den Blattrahmen."
                    ).format(m=max(margins))
                )
        return result

    def _update(self) -> None:
        sheet_mode = not self.rb_model.isChecked()
        self.sheet_list.setEnabled(self.rb_selection.isChecked())
        for b in (self.rb_one, self.rb_fit, self.rb_tiles):
            b.setEnabled(sheet_mode)
        hints = []
        possible = self._one_to_one_possible(self.sheets())
        if sheet_mode and not possible:
            self.rb_one.setEnabled(False)
            if self.rb_one.isChecked():
                self.rb_fit.setChecked(True)
            hints.append(
                self.tr("Der Drucker bietet das Blattformat nicht an: Einpassen oder Kacheln.")
            )
        self.paper.setEnabled(not sheet_mode or not self.rb_one.isChecked())
        self.lbl_printer.setText(
            self.tr("Drucker: {name}").format(
                name=self.printer.printerName() or self.tr("(keiner)")
            )
        )
        hints += self.warnings()
        self.lbl_hint.setText("\n".join(hints))
        self.btn_print.setEnabled(bool(self.job().model or self.job().sheets))

    def _choose_printer(self) -> None:
        dialog = QPrintDialog(self.printer, self)
        dialog.setOption(QPrintDialog.PrintDialogOption.PrintToFile, True)
        dialog.exec()
        self._update()

    # -- output -------------------------------------------------------------

    def render_to(self, printer: QPrinter) -> int:
        job = self.job()
        printer.setFullPage(True)
        return render(printer, self.doc, plan(self.doc, job), job.options)

    def preview(self) -> None:
        dialog = QPrintPreviewDialog(self.printer, self)
        dialog.setWindowTitle(self.tr("Druckvorschau"))
        dialog.paintRequested.connect(self.render_to)
        warnings = self.warnings()
        if warnings:
            dialog.setWindowTitle(self.tr("Druckvorschau – Achtung: {w}").format(w=warnings[0]))
        dialog.resize(1000, 800)
        dialog.exec()

    def _print(self) -> None:
        if self.render_to(self.printer):
            self.accept()
