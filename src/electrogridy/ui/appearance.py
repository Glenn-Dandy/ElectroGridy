"""Dark mode of the whole program: menus, docks and dialogs get a dark palette.

Dark uses the Fusion style, the only one that follows a palette on every platform. Light
goes back to the style and palette the program started with.
"""

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

SETTINGS_KEY = "ui/dark_mode"

_started_with: tuple[str, QPalette] | None = None
_dark = False

Role = QPalette.ColorRole
Group = QPalette.ColorGroup

DARK_COLORS = {
    Role.Window: "#2b2d31",
    Role.WindowText: "#e6e8eb",
    Role.Base: "#1f2125",
    Role.AlternateBase: "#282a2e",
    Role.ToolTipBase: "#2b2d31",
    Role.ToolTipText: "#e6e8eb",
    Role.PlaceholderText: "#8a9099",
    Role.Text: "#e6e8eb",
    Role.Button: "#33363b",
    Role.ButtonText: "#e6e8eb",
    Role.BrightText: "#ff6b6b",
    Role.Light: "#45484e",
    Role.Midlight: "#3a3d43",
    Role.Mid: "#2f3237",
    Role.Dark: "#1a1c1f",
    Role.Shadow: "#000000",
    Role.Highlight: "#2f6fb0",
    Role.HighlightedText: "#ffffff",
    Role.Link: "#82b2ff",
    Role.LinkVisited: "#b39ddb",
}
DISABLED_TEXT = "#6f757d"


def dark_palette() -> QPalette:
    palette = QPalette()
    for role, color in DARK_COLORS.items():
        palette.setColor(role, QColor(color))
    for role in (Role.WindowText, Role.Text, Role.ButtonText, Role.HighlightedText):
        palette.setColor(Group.Disabled, role, QColor(DISABLED_TEXT))
    palette.setColor(Group.Disabled, Role.Highlight, QColor("#3a3d43"))
    return palette


def configured() -> bool:
    return QSettings().value(SETTINGS_KEY, False, type=bool)


def is_dark() -> bool:
    return _dark


def apply(dark: bool) -> None:
    """Switch the whole program between light and dark (works while running)."""
    global _started_with, _dark
    app = QApplication.instance()
    if app is None:
        return
    if _started_with is None:
        _started_with = (app.style().name(), QPalette(app.palette()))
    if dark == _dark:
        return
    _dark = dark
    if dark:
        app.setStyle("Fusion")
        app.setPalette(dark_palette())
    else:
        style, palette = _started_with
        app.setStyle(style)
        app.setPalette(palette)
