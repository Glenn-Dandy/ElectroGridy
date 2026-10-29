"""Command line below the canvas: shows the prompt and takes typed coordinates."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget


class _Edit(QLineEdit):
    escape_pressed = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class CommandLine(QWidget):
    submitted = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.prompt = QLabel()
        self.edit = _Edit()
        self.edit.setPlaceholderText(self.tr("x,y   @dx,dy   Länge (bei Ortho)"))
        self.edit.setMinimumWidth(240)
        self.edit.returnPressed.connect(self._submit)
        self.edit.escape_pressed.connect(self._cancel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.addWidget(self.prompt)
        layout.addWidget(self.edit, 1)

    def set_prompt(self, text: str) -> None:
        self.prompt.setText(text)

    def start_typing(self, text: str) -> None:
        self.edit.setFocus()
        self.edit.insert(text)

    def _submit(self) -> None:
        text = self.edit.text()
        self.edit.clear()
        self.submitted.emit(text)

    def _cancel(self) -> None:
        self.edit.clear()
        self.cancelled.emit()
