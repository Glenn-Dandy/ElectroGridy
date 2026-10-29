"""Which Qt platform (window system) to use, decided before the application starts.

``auto`` keeps Qt's own choice (Wayland in a Wayland session). X11 through XWayland
can be chosen explicitly; on GNOME it attaches dialogs to the main window, so moving
a dialog moves (and unmaximizes) the main window, which is why it is not the default.
"""

from collections.abc import Mapping

SETTINGS_KEY = "ui/platform"
AUTO, WAYLAND, X11 = "auto", "wayland", "xcb"
CHOICES = (AUTO, WAYLAND, X11)


def choose_platform(env: Mapping[str, str], setting: str) -> str | None:
    """Value for QT_QPA_PLATFORM, or None to leave Qt's own choice.

    An explicit QT_QPA_PLATFORM in the environment always wins. X11 needs an X
    server (DISPLAY); Wayland stays as fallback in the list.
    """
    if env.get("QT_QPA_PLATFORM"):
        return None
    has_x = bool(env.get("DISPLAY"))
    if setting == WAYLAND:
        return "wayland" if env.get("WAYLAND_DISPLAY") else None
    if setting == X11:
        return "xcb;wayland" if has_x else None
    return None
