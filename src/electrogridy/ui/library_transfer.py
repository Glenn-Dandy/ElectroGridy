"""Dialogs for importing and exporting libraries: where imported blocks go, what to do
with a name that is taken, and what to export (a library, a category or blocks)."""

from collections.abc import Mapping

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from electrogridy.fileio.library_merge import KEEP, RENAME, REPLACE
from electrogridy.i18n import library_text
from electrogridy.model.blocks import BlockDefinition, dependencies
from electrogridy.view.thumbnails import block_icon, block_image

USER, NEW = "user", "new"
PREVIEW = 180  # px


def _ok_cancel(dialog: QDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class ImportTargetDialog(QDialog):
    """Into "Eigene Symbole" (each block in its category) or as a library of its own."""

    def __init__(self, file_title: str, count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Bibliothek importieren"))
        self.user = QRadioButton(self.tr("In „Eigene Symbole“, jeder Block in seine Kategorie"))
        self.new = QRadioButton(self.tr("Als neue Bibliothek:"))
        self.user.setChecked(True)
        self.name = QLineEdit(file_title)
        self.name.setEnabled(False)
        self.new.toggled.connect(self.name.setEnabled)
        group = QButtonGroup(self)
        group.addButton(self.user)
        group.addButton(self.new)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(self.tr("{n} Blöcke aus „{name}“.").format(n=count, name=file_title))
        )
        layout.addWidget(self.user)
        row = QHBoxLayout()
        row.addWidget(self.new)
        row.addWidget(self.name, 1)
        layout.addLayout(row)
        layout.addWidget(_ok_cancel(self))
        self.resize(max(self.sizeHint().width(), 460), self.sizeHint().height())

    def values(self) -> tuple[str, str]:
        if self.new.isChecked() and self.name.text().strip():
            return NEW, self.name.text().strip()
        return USER, ""


class BlockConflictDialog(QDialog):
    """The block there and the imported one side by side: keep, replace or rename."""

    def __init__(
        self,
        there: BlockDefinition,
        there_blocks: Mapping[str, BlockDefinition],
        incoming: BlockDefinition,
        incoming_blocks: Mapping[str, BlockDefinition],
        library: str,
        taken: set[str],
        suggestion: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Name schon vergeben"))
        self._taken = taken
        self.action = KEEP
        grid = QGridLayout()
        for column, (caption, block, blocks) in enumerate(
            (
                (self.tr("Vorhanden in „{name}“").format(name=library), there, there_blocks),
                (self.tr("Neu aus dem Import"), incoming, incoming_blocks),
            )
        ):
            title = QLabel(f"<b>{caption}</b>")
            picture = QLabel()
            picture.setPixmap(QPixmap.fromImage(block_image(block.name, blocks, PREVIEW)))
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            picture.setMinimumSize(PREVIEW, PREVIEW)
            text = QLabel(
                "\n".join(
                    t
                    for t in (
                        self.tr("Kategorie: {name}").format(
                            name=library_text(block.category) or self.tr("(keine)")
                        ),
                        library_text(block.description),
                    )
                    if t
                )
            )
            text.setWordWrap(True)
            text.setAlignment(Qt.AlignmentFlag.AlignTop)
            grid.addWidget(title, 0, column)
            grid.addWidget(picture, 1, column)
            grid.addWidget(text, 2, column)
        self.name = QLineEdit(suggestion)
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #c62828")
        self.for_all = QCheckBox(
            self.tr("Für alle weiteren doppelten Namen gleich (außer Umbenennen)")
        )
        keep = QPushButton(self.tr("Vorhandenen behalten"))
        replace = QPushButton(self.tr("Ersetzen"))
        rename = QPushButton(self.tr("Neuen umbenennen"))
        cancel = QPushButton(self.tr("Import abbrechen"))
        keep.clicked.connect(lambda: self._choose(KEEP))
        replace.clicked.connect(lambda: self._choose(REPLACE))
        rename.clicked.connect(lambda: self._choose(RENAME))
        cancel.clicked.connect(self.reject)
        rename_row = QFormLayout()
        rename_row.addRow(self.tr("Neuer Name:"), self.name)
        buttons = QHBoxLayout()
        for button in (keep, replace, rename):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                self.tr("Den Block „{name}“ gibt es in „{library}“ schon, aber anders.").format(
                    name=library_text(incoming.name), library=library
                )
            )
        )
        layout.addLayout(grid)
        layout.addLayout(rename_row)
        layout.addWidget(self.problem)
        layout.addWidget(self.for_all)
        layout.addLayout(buttons)
        keep.setDefault(True)

    def _choose(self, action: str) -> None:
        if action == RENAME:
            name = self.name.text().strip()
            if not name or name in self._taken:
                self.problem.setText(self.tr("Diesen Namen gibt es schon"))
                return
        self.action = action
        self.accept()

    def values(self) -> tuple[str, str, bool]:
        """Action, new name (when renaming) and whether it holds for the next ones."""
        return self.action, self.name.text().strip(), self.for_all.isChecked()


class ExportDialog(QDialog):
    """A whole library, one category or chosen blocks; nested blocks come along."""

    WHOLE, CATEGORY, CHOSEN = "whole", "category", "chosen"

    def __init__(
        self,
        sources: list[tuple[str, Mapping[str, BlockDefinition]]],
        current: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Bibliothek exportieren"))
        self._sources = sources
        self.source = QComboBox()
        for title, _blocks in sources:
            self.source.addItem(title)
        self.whole = QRadioButton(self.tr("Ganze Bibliothek"))
        self.category_choice = QRadioButton(self.tr("Kategorie:"))
        self.chosen = QRadioButton(self.tr("Einzelne Blöcke:"))
        self.whole.setChecked(True)
        group = QButtonGroup(self)
        for button in (self.whole, self.category_choice, self.chosen):
            group.addButton(button)
        self.category = QComboBox()
        self.blocks = QListWidget()
        self.blocks.setIconSize(QSize(32, 32))
        self.count = QLabel()
        form = QFormLayout()
        form.addRow(self.tr("Quelle:"), self.source)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.whole)
        row = QHBoxLayout()
        row.addWidget(self.category_choice)
        row.addWidget(self.category, 1)
        layout.addLayout(row)
        layout.addWidget(self.chosen)
        layout.addWidget(self.blocks, 1)
        layout.addWidget(self.count)
        layout.addWidget(_ok_cancel(self))
        self.source.currentIndexChanged.connect(self._fill)
        for widget in (self.whole, self.category_choice, self.chosen):
            widget.toggled.connect(self._update)
        self.category.currentIndexChanged.connect(self._update)
        self.blocks.itemChanged.connect(self._update)
        self.source.setCurrentIndex(max(0, min(current, len(sources) - 1)))
        self._fill()
        self.resize(480, 560)

    @property
    def library(self) -> Mapping[str, BlockDefinition]:
        return self._sources[self.source.currentIndex()][1]

    @property
    def title(self) -> str:
        return self._sources[self.source.currentIndex()][0]

    def _fill(self, *_args) -> None:
        blocks = self.library
        self.category.blockSignals(True)
        self.category.clear()
        for category in sorted({b.category for b in blocks.values()}, key=str.casefold):
            self.category.addItem(library_text(category) or self.tr("(ohne Kategorie)"), category)
        self.category.blockSignals(False)
        self.blocks.blockSignals(True)
        self.blocks.clear()
        for name in sorted(blocks, key=str.casefold):
            item = QListWidgetItem(block_icon(name, blocks, 32), library_text(name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.blocks.addItem(item)
        self.blocks.blockSignals(False)
        self._update()

    def _update(self, *_args) -> None:
        self.category.setEnabled(self.category_choice.isChecked())
        self.blocks.setEnabled(self.chosen.isChecked())
        self.count.setText(self.tr("{n} Blöcke").format(n=len(self.names())))

    def check(self, names: list[str]) -> None:
        """Tick these blocks and choose single blocks."""
        self.chosen.setChecked(True)
        for i in range(self.blocks.count()):
            item = self.blocks.item(i)
            if item.data(Qt.ItemDataRole.UserRole) in names:
                item.setCheckState(Qt.CheckState.Checked)

    def chosen_names(self) -> list[str]:
        """What was chosen, without the nested blocks."""
        blocks = self.library
        if self.whole.isChecked():
            return list(blocks)
        if self.category_choice.isChecked():
            category = self.category.currentData()
            return [n for n, b in blocks.items() if b.category == category]
        return [
            self.blocks.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.blocks.count())
            if self.blocks.item(i).checkState() == Qt.CheckState.Checked
        ]

    def names(self) -> list[str]:
        """What will be written: the chosen blocks and the blocks nested in them."""
        blocks = self.library
        result: dict[str, None] = {}
        for name in self.chosen_names():
            for dep in dependencies(name, blocks):
                if dep in blocks:
                    result[dep] = None
        return list(result)
