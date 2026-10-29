"""Options for PDF, SVG and PNG export."""

from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QRadioButton,
    QSpinBox,
)

from electrogridy.view.display import OutputOptions

PDF, SVG, PNG = "pdf", "svg", "png"


class ExportDialog(QDialog):
    def __init__(self, kind: str, has_current: bool, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle(self.tr("Export {kind}").format(kind=kind.upper()))
        self.rb_current = QRadioButton(self.tr("Aktuelles Blatt"))
        self.rb_all = QRadioButton(
            self.tr("Alle Blätter (eine Seite je Blatt)")
            if kind == PDF
            else self.tr("Alle Blätter (eine Datei je Blatt)")
        )
        group = QButtonGroup(self)
        group.addButton(self.rb_current)
        group.addButton(self.rb_all)
        self.rb_current.setEnabled(has_current)
        (self.rb_current if has_current else self.rb_all).setChecked(True)
        self.dpi = QSpinBox()
        self.dpi.setRange(50, 1200)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        self.cb_mono = QCheckBox(self.tr("Schwarz-weiß"))
        self.cb_printable = QCheckBox(self.tr("Nur druckbare Ebenen"))
        self.cb_printable.setChecked(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(self.rb_current)
        form.addRow(self.rb_all)
        if kind == PNG:
            form.addRow(self.tr("Auflösung:"), self.dpi)
        form.addRow(self.cb_mono)
        form.addRow(self.cb_printable)
        form.addRow(buttons)

    def all_sheets(self) -> bool:
        return self.rb_all.isChecked()

    def options(self) -> OutputOptions:
        return OutputOptions(
            helpers=False,
            monochrome=self.cb_mono.isChecked(),
            printable_only=self.cb_printable.isChecked(),
        )
