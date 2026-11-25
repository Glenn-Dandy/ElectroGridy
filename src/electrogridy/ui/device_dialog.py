"""The window of a circuit diagram symbol in a project: attributes, the names of its
terminals laid out like the symbol, turning and mirroring with a preview.

Contacts (auxiliary functions) choose the device they belong to from the main
functions of the project; the field stays editable for a new one.
"""

from collections.abc import Mapping
from dataclasses import replace

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from electrogridy.i18n import library_text
from electrogridy.model.blocks import BlockDefinition, BlockError, expand, options_on
from electrogridy.model.devices import BMK, pole_texts
from electrogridy.model.entities import AttributeDefinition, BlockReference
from electrogridy.ui.block_dialogs import AttributeValueEdit
from electrogridy.view.render import Style, entity_bounds, paint_entity

PREVIEW_SIZE = 180
PREVIEW_WEIGHT = 0.25


def uses_device_dialog(definition: BlockDefinition | None) -> bool:
    """Circuit diagram symbols: main and auxiliary functions (not terminals)."""
    return definition is not None and definition.function in ("main", "aux")


def reference_image(
    ref: BlockReference, blocks: Mapping[str, BlockDefinition], size: int = PREVIEW_SIZE
) -> QImage:
    """The reference as drawn on the page (with its terminal names), fitted into a
    square."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    try:
        from electrogridy.view.display import raised_attributes

        parts = raised_attributes(blocks, ref, expand(ref, blocks)) + pole_texts(ref, blocks)
    except BlockError:
        return image
    bounds = QRectF()
    for p in parts:
        bounds = bounds.united(entity_bounds(p, PREVIEW_WEIGHT))
    if bounds.isEmpty():
        return image
    margin = 8
    scale = min(
        (size - 2 * margin) / max(bounds.width(), 1e-6),
        (size - 2 * margin) / max(bounds.height(), 1e-6),
    )
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(size / 2, size / 2)
    painter.scale(scale, scale)
    painter.translate(-bounds.center())
    style = Style(QGuiApplication.palette().color(QPalette.ColorRole.Text), PREVIEW_WEIGHT)
    for p in parts:
        paint_entity(painter, p, style, scale)
    painter.end()
    return image


class DeviceDialog(QDialog):
    def __init__(
        self,
        ref: BlockReference,
        blocks: Mapping[str, BlockDefinition],
        values: dict[str, str],
        devices: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._ref = ref
        self._blocks = blocks
        self._definition = blocks[ref.name]
        self.setWindowTitle(self.tr("Gerät: {name}").format(name=library_text(ref.name)))

        # Attributes; a contact picks its device from the main functions.
        form = QFormLayout()
        self._edits: dict[str, AttributeValueEdit] = {}
        self.device: QComboBox | None = None
        for d in self._attribute_definitions():
            label = f"{library_text(d.prompt) or d.tag}:"
            value = values.get(d.tag, d.default)
            if d.tag == BMK and self._definition.function == "aux":
                self.device = QComboBox()
                self.device.setEditable(True)
                self.device.addItems(devices)
                self.device.setCurrentText(value)
                self.device.setToolTip(
                    self.tr("Gerät, zu dem der Kontakt gehört (erscheint in dessen Kontaktspiegel)")
                )
                form.addRow(label, self.device)
                continue
            edit = AttributeValueEdit(value)
            edit.submitted.connect(self.accept)
            form.addRow(label, edit)
            self._edits[d.tag] = edit

        # Terminal names in the layout of the symbol: one column per pole, upper end
        # above, lower end below.
        self._terminals: dict[str, QLineEdit] = {}
        group = QGroupBox(self.tr("Anschlüsse"))
        grid = QGridLayout(group)
        points = self._definition.connection_points()
        xs = sorted({round(c.position.x, 1) for c in points})
        ys = sorted({round(c.position.y, 1) for c in points})
        for c in points:
            edit = QLineEdit(ref.terminal_label(c.name))
            edit.setPlaceholderText(c.name)
            edit.setMaximumWidth(64)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.textChanged.connect(self._update_preview)
            row = ys.index(round(c.position.y, 1)) * 2
            grid.addWidget(edit, row, xs.index(round(c.position.x, 1)))
            self._terminals[c.name] = edit
        for col, x in enumerate(xs):  # a pole joins its upper and lower terminal
            column = [c for c in points if round(c.position.x, 1) == x]
            rows = sorted(ys.index(round(c.position.y, 1)) for c in column)
            for row in range(rows[0], rows[-1]):
                bar = QFrame()
                bar.setFrameShape(QFrame.Shape.VLine)
                bar.setFixedHeight(14)
                grid.addWidget(bar, 2 * row + 1, col, Qt.AlignmentFlag.AlignHCenter)
        # Parts of the symbol that can be left out (releases of a motor protection switch).
        self._options: dict[str, QCheckBox] = {}
        options = QGroupBox(self.tr("Ausführung"))
        option_box = QVBoxLayout(options)
        states = options_on(ref, self._definition)
        for o in self._definition.options:
            check = QCheckBox(library_text(o.label))
            check.setChecked(states[o.key])
            check.toggled.connect(self._update_preview)
            option_box.addWidget(check)
            self._options[o.key] = check

        hint = QLabel(self.tr("Leer lassen: Name aus dem Symbol"))
        hint.setEnabled(False)
        grid.addWidget(hint, 2 * len(ys), 0, 1, max(1, len(xs)))

        # Preview with turning and mirroring.
        self._rotation = ref.rotation % 360
        self._mirrored = ref.mirrored_x
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_left = QPushButton("↺ 90°")
        self.btn_left.setToolTip(self.tr("90° gegen den Uhrzeigersinn drehen"))
        self.btn_right = QPushButton("↻ 90°")
        self.btn_right.setToolTip(self.tr("90° im Uhrzeigersinn drehen"))
        self.btn_mirror = QPushButton("⇆ " + self.tr("Spiegeln"))
        self.btn_mirror.setToolTip(self.tr("An der senkrechten Achse spiegeln"))
        for button in (self.btn_left, self.btn_right, self.btn_mirror):
            button.setAutoDefault(False)  # Enter stays OK
        self.btn_left.clicked.connect(lambda _checked=False: self.turn(1))
        self.btn_right.clicked.connect(lambda _checked=False: self.turn(-1))
        self.btn_mirror.clicked.connect(lambda _checked=False: self.mirror())
        turns = QHBoxLayout()
        for button in (self.btn_left, self.btn_right, self.btn_mirror):
            turns.addWidget(button)

        left = QVBoxLayout()
        left.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        left.addLayout(turns)
        left.addStretch(1)
        right = QVBoxLayout()
        right.addLayout(form)
        if self._options:
            right.addWidget(options)
        if points:
            right.addWidget(group)
        right.addStretch(1)
        body = QHBoxLayout()
        holder = QWidget()
        holder.setLayout(left)
        body.addWidget(holder)
        body.addLayout(right, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer = QVBoxLayout(self)
        outer.addLayout(body)
        outer.addWidget(buttons)
        self._update_preview()

    def _attribute_definitions(self) -> list[AttributeDefinition]:
        return self._definition.attribute_definitions()

    # -- turning ------------------------------------------------------------------

    def turn(self, quarters: int) -> None:
        """``quarters`` counter-clockwise (negative: clockwise)."""
        self._rotation = (self._rotation + 90 * quarters) % 360
        self._update_preview()

    def mirror(self) -> None:
        # Mirrored at the vertical axis through the insertion point, as the turned
        # symbol is seen: M . R(r) . Mx^m = R(-r) . Mx^(m+1).
        self._rotation = -self._rotation % 360
        self._mirrored = not self._mirrored
        self._update_preview()

    def _update_preview(self, *_args) -> None:
        image = reference_image(self.reference(), self._blocks)
        self.preview.setPixmap(QPixmap.fromImage(image))

    # -- result -------------------------------------------------------------------

    def values(self) -> dict[str, str]:
        out = {tag: edit.text() for tag, edit in self._edits.items()}
        if self.device is not None:
            out[BMK] = self.device.currentText().strip()
        return out

    def labels(self) -> tuple[tuple[str, str], ...]:
        """Own terminal names (an empty field keeps the name from the symbol)."""
        return tuple(
            sorted(
                (name, edit.text().strip())
                for name, edit in self._terminals.items()
                if edit.text().strip() and edit.text().strip() != name
            )
        )

    def option_states(self) -> tuple[tuple[str, bool], ...]:
        """Options switched away from their default."""
        defaults = {o.key: o.default for o in self._definition.options}
        return tuple(
            sorted(
                (key, check.isChecked())
                for key, check in self._options.items()
                if check.isChecked() != defaults[key]
            )
        )

    def reference(self) -> BlockReference:
        """The reference with everything chosen in the window."""
        return replace(
            self._ref,
            attributes=tuple(sorted(self.values().items())),
            terminal_labels=self.labels(),
            option_states=self.option_states(),
            rotation=self._rotation,
            mirrored_x=self._mirrored,
        )
