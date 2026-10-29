"""Object snap mode menu (status bar button and Shift + right click)."""

from collections.abc import Callable

from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QToolButton, QWidget

from electrogridy.model.snap import ALL_MODES, SnapMode

HOVER_DELAY_MS = 600


def tr(text: str) -> str:
    return QCoreApplication.translate("OsnapMenu", text)


def mode_labels() -> dict[SnapMode, str]:
    return {
        SnapMode.CONNECTION: tr("Anschlusspunkt (Vorrang)"),
        SnapMode.PERPENDICULAR: tr("Lotfußpunkt (rechtwinklig vom letzten Punkt)"),
        SnapMode.ENDPOINT: tr("Endpunkt"),
        SnapMode.MIDPOINT: tr("Mittelpunkt"),
        SnapMode.INTERSECTION: tr("Schnittpunkt"),
        SnapMode.CENTER: tr("Zentrum"),
        SnapMode.INSERTION: tr("Einfügepunkt (Bezugspunkt von Texten)"),
        SnapMode.BUSBAR: tr("Sammelschiene (beliebiger Punkt im Raster)"),
        SnapMode.NEAREST: tr("Nächster Punkt (auf Linie, Kreis, Bogen)"),
    }


class OsnapMenu(QMenu):
    """Checkable list of snap modes; reads and writes them through callbacks."""

    def __init__(
        self,
        parent: QWidget,
        osnap_action: QAction,
        get_modes: Callable[[], frozenset[SnapMode]],
        set_modes: Callable[[frozenset[SnapMode]], None],
    ) -> None:
        super().__init__(tr("Objektfang"), parent)
        self._get, self._set = get_modes, set_modes
        self.addAction(osnap_action)
        self.addSeparator()
        self.mode_actions: dict[SnapMode, QAction] = {}
        for mode, label in mode_labels().items():
            action = self.addAction(label)
            action.setCheckable(True)
            action.toggled.connect(self._changed)
            self.mode_actions[mode] = action
        self.addSeparator()
        self.addAction(tr("Alle"), lambda: self._apply(ALL_MODES))
        self.addAction(tr("Keine"), lambda: self._apply(frozenset()))
        self.aboutToShow.connect(self.sync)
        self.sync()

    def sync(self) -> None:
        modes = self._get()
        for mode, action in self.mode_actions.items():
            action.blockSignals(True)
            action.setChecked(mode in modes)
            action.blockSignals(False)

    def _apply(self, modes: frozenset[SnapMode]) -> None:
        self._set(modes)
        self.sync()

    def _changed(self) -> None:
        self._set(frozenset(m for m, a in self.mode_actions.items() if a.isChecked()))


class HoverMenuButton(QToolButton):
    """Tool button whose menu also opens when the mouse rests on it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(HOVER_DELAY_MS)
        self._timer.timeout.connect(self._open)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().leaveEvent(event)

    def _open(self) -> None:
        if self.underMouse() and self.menu() is not None:
            self.showMenu()
