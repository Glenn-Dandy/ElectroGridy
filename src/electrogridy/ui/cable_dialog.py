"""Cable marks: dialog for name, type and cores, and placing or editing a mark (the
crossed wires get cable and core)."""

from dataclasses import replace
from typing import TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from electrogridy.commands.entities import AddEntitiesCommand, ReplaceEntitiesCommand
from electrogridy.model.cables import (
    assigned,
    cable_types,
    crossings,
    fitted,
    next_cable_name,
    suggested_cores,
    used_cables,
)
from electrogridy.model.devices import _natural
from electrogridy.model.entities import CableMark, new_id
from electrogridy.model.geometry import Point

if TYPE_CHECKING:
    from electrogridy.ui.main_window import MainWindow


def tr(text: str) -> str:
    return QCoreApplication.translate("cable", text)


class CableDialog(QDialog):
    def __init__(
        self, name: str, cable_type: str, types: list[str], cores: list[str], parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Kabel"))
        self.name = QLineEdit(name)
        self.name.setToolTip(self.tr("Betriebsmittelkennzeichen des Kabels, z. B. -W1"))
        self.type = QComboBox()
        self.type.setEditable(True)
        self.type.addItems(types)
        self.type.setCurrentText(cable_type)
        self.type.setToolTip(self.tr("Kabeltyp für Klemmenplan und Kabelliste, z. B. NYM-J 5x2,5"))
        self.cores = [QLineEdit(core) for core in cores]
        form = QFormLayout(self)
        form.addRow(self.tr("Kabel:"), self.name)
        form.addRow(self.tr("Kabeltyp:"), self.type)
        form.addRow(QLabel(self.tr("Adern, in Reihenfolge der Leitungen:")))
        for i, edit in enumerate(self.cores, start=1):
            edit.setToolTip(self.tr("Aderfarbe oder Adernummer, z. B. BN, BU, GNYE, 3"))
            form.addRow(self.tr("Leitung {n}:").format(n=i), edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(max(self.sizeHint().width(), 340), self.sizeHint().height())

    def values(self) -> tuple[str, str, list[str]]:
        return (
            self.name.text().strip(),
            self.type.currentText().strip(),
            [edit.text().strip() for edit in self.cores],
        )


def place_cable(w: "MainWindow", p1: Point, p2: Point, mark: CableMark | None = None) -> None:
    """Ask for name, type and cores of the cable crossing the wires between ``p1`` and
    ``p2``, then add the mark (or change ``mark``) and set cable and core on the wires."""
    container = w.container
    probe = mark or fitted(
        CableMark(id="", layer=w.current_layer, p1=p1, p2=p2, name=""), container
    )
    crossed = [wire for _p, wire in crossings(probe, container)]
    if not crossed:
        w.message(tr("Die Linie kreuzt keine Leitung"))
        return
    doc = w.document
    types = sorted(set(cable_types(doc).values()), key=_natural)
    area = next((s.id for s in doc.sheets if s.entities is container), "model")
    proposed = suggested_cores(doc, area, crossed)
    if mark is not None:
        name, kind = mark.name, mark.cable_type
        cores = [wire.core or proposed[i] for i, wire in enumerate(crossed)]
    else:
        name, kind = next_cable_name(used_cables(doc)), types[-1] if types else ""
        cores = proposed
    dialog = CableDialog(name, kind, types, cores, w)
    if dialog.exec() != CableDialog.DialogCode.Accepted:
        return
    name, kind, cores = dialog.values()
    if not name:
        return
    # The cable tool stays active for the next cable.
    w.begin_macro(tr("Kabel {name}").format(name=name))
    if mark is None:
        new = replace(probe, id=new_id(), name=name, cable_type=kind)
        w.push(AddEntitiesCommand(container, [new], ""))
    else:
        w.push(ReplaceEntitiesCommand(container, [replace(mark, name=name, cable_type=kind)], ""))
    w.push(ReplaceEntitiesCommand(container, assigned(crossed, name, cores), ""))
    w.end_macro()
