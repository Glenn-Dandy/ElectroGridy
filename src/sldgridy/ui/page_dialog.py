"""Dialog for a page of the multi-line circuit diagram: plant, location, description."""

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from sldgridy.model.document import designation


def _editable_combo(current: str, choices: list[str]) -> QComboBox:
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    box.addItems(choices)
    box.setCurrentText(current)
    return box


class PageDialog(QDialog):
    def __init__(
        self,
        title: str,
        plant: str,
        location: str,
        name: str,
        plants: list[str],
        locations: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.plant = _editable_combo(plant, plants)
        self.plant.setToolTip(self.tr("Anlage, z. B. PV1 (wird als =PV1 geschrieben)"))
        self.location = _editable_combo(location, locations)
        self.location.setToolTip(self.tr("Einbauort, z. B. UV1 (wird als +UV1 geschrieben)"))
        self.name = QLineEdit(name)
        self.name.setPlaceholderText(self.tr("z. B. Einspeisung, Steuerung Wechselrichter"))
        self.preview = QLabel()
        for box in (self.plant, self.location):
            box.editTextChanged.connect(self._update)
        form = QFormLayout(self)
        form.addRow(self.tr("Anlage (=):"), self.plant)
        form.addRow(self.tr("Ort (+):"), self.location)
        form.addRow(self.tr("Beschreibung:"), self.name)
        form.addRow(self.tr("Kennzeichen:"), self.preview)
        hint = QLabel(
            self.tr(
                "Seiten werden je Anlage und Ort fortlaufend nummeriert. "
                "Leer lassen, wenn es nur eine Anlage oder einen Ort gibt."
            )
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._update()
        self.resize(max(self.sizeHint().width(), 380), self.sizeHint().height())

    @staticmethod
    def _clean(text: str, prefix: str) -> str:
        """ "=PV1", " PV1 " and "PV1" all mean PV1."""
        return text.strip().removeprefix(prefix).strip()

    def values(self) -> tuple[str, str, str]:
        return (
            self._clean(self.plant.currentText(), "="),
            self._clean(self.location.currentText(), "+"),
            self.name.text().strip(),
        )

    def _update(self) -> None:
        plant, location, _ = self.values()
        self.preview.setText(designation(plant, location) or self.tr("(ohne)"))
