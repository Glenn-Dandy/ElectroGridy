"""Own title bar for dock widgets.

Under Wayland a client cannot position its windows, so Qt's own dragging of
dock widgets fails: floating docks with the native frame cannot be docked
again, and frameless ones cannot be moved or resized. This title bar keeps a
dock/undock button, hands moving and resizing of floating docks to the
compositor (``startSystemMove``/``startSystemResize``) and offers docking to
an area through a context menu instead of drag-and-drop.
"""

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QStyle,
    QToolButton,
    QWidget,
)

RESIZE_MARGIN = 6  # px at the edges of a floating dock that start resizing


def is_wayland() -> bool:
    return QGuiApplication.platformName().startswith("wayland")


class DockTitleBar(QWidget):
    def __init__(self, dock: QDockWidget) -> None:
        super().__init__(dock)
        self._dock = dock
        self.label = QLabel(dock.windowTitle())
        # A font, not a style sheet: widgets with a style sheet keep the palette they had
        # then, the title stayed dark in dark mode.
        font = self.label.font()
        font.setBold(True)
        self.label.setFont(font)
        style = self.style()
        self.btn_float = QToolButton()
        self.btn_float.setAutoRaise(True)
        self.btn_float.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton))
        self.btn_float.clicked.connect(self.toggle)
        self.btn_close = QToolButton()
        self.btn_close.setAutoRaise(True)
        self.btn_close.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.btn_close.setToolTip(self.tr("Schließen"))
        self.btn_close.clicked.connect(dock.close)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 2, 2)
        layout.setSpacing(2)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.btn_float)
        layout.addWidget(self.btn_close)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        dock.windowTitleChanged.connect(self.label.setText)
        dock.topLevelChanged.connect(self._update_tooltip)
        self._update_tooltip(dock.isFloating())

    def _update_tooltip(self, floating: bool) -> None:
        self.btn_float.setToolTip(
            self.tr("Andocken (oder Doppelklick auf den Titel)")
            if floating
            else self.tr("Abdocken (oder Doppelklick auf den Titel)")
        )
        self.setToolTip(
            self.tr("Ziehen verschiebt das Fenster, Rechtsklick wählt den Andockplatz")
            if floating
            else self.tr("Rechtsklick wählt den Andockplatz")
        )

    def toggle(self) -> None:
        self._dock.setFloating(not self._dock.isFloating())

    def dock_to(self, area: Qt.DockWidgetArea) -> None:
        window = self._dock.parent()
        if not isinstance(window, QMainWindow):
            return
        self._dock.setFloating(False)
        window.removeDockWidget(self._dock)
        window.addDockWidget(area, self._dock)
        self._dock.show()

    def _context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        areas = (
            (self.tr("Links andocken"), Qt.DockWidgetArea.LeftDockWidgetArea),
            (self.tr("Rechts andocken"), Qt.DockWidgetArea.RightDockWidgetArea),
            (self.tr("Unten andocken"), Qt.DockWidgetArea.BottomDockWidgetArea),
        )
        for text, area in areas:
            menu.addAction(text, lambda a=area: self.dock_to(a))
        if not self._dock.isFloating():
            menu.addSeparator()
            menu.addAction(self.tr("Abdocken"), self.toggle)
        menu.exec(self.mapToGlobal(pos))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dock.isFloating():
                handle = self._dock.windowHandle()
                if handle is not None and handle.startSystemMove():
                    event.accept()
                    return
            elif is_wayland():
                # Qt's drag-out moves a window by itself, which Wayland ignores.
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if is_wayland() and not self._dock.isFloating():
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _ResizeFilter(QObject):
    """Lets the compositor resize floating docks from their edges."""

    def __init__(self, dock: QDockWidget) -> None:
        super().__init__(dock)
        self._dock = dock

    def _edges(self, pos: QPoint) -> Qt.Edge:
        r = self._dock.rect()
        edges = Qt.Edge(0)
        if pos.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= r.width() - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= r.height() - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        try:
            floating = self._dock.isFloating()
        except RuntimeError:  # dock already deleted while the window closes
            return False
        if not floating:
            return False
        if event.type() == QEvent.Type.MouseMove and not event.buttons():
            edges = self._edges(event.position().toPoint())
            shape = Qt.CursorShape.ArrowCursor
            horizontal = edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
            vertical = edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
            if horizontal and vertical:
                diagonal = edges in (
                    Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                    Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
                )
                shape = (
                    Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
                )
            elif horizontal:
                shape = Qt.CursorShape.SizeHorCursor
            elif vertical:
                shape = Qt.CursorShape.SizeVerCursor
            self._dock.setCursor(shape)
        elif event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                edges = self._edges(event.position().toPoint())
                handle = self._dock.windowHandle()
                if edges and handle is not None and handle.startSystemResize(edges):
                    return True
        return False


def install_title_bar(dock: QDockWidget) -> DockTitleBar:
    bar = DockTitleBar(dock)
    dock.setTitleBarWidget(bar)
    dock.setMouseTracking(True)
    dock.installEventFilter(_ResizeFilter(dock))
    return bar
