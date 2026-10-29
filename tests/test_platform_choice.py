from electrogridy.platform_choice import AUTO, WAYLAND, X11, choose_platform

GNOME_WAYLAND = {
    "XDG_SESSION_TYPE": "wayland",
    "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
    "WAYLAND_DISPLAY": "wayland-0",
    "DISPLAY": ":0",
}


def test_auto_keeps_qts_own_choice():
    assert choose_platform(GNOME_WAYLAND, AUTO) is None
    kde = dict(GNOME_WAYLAND, XDG_CURRENT_DESKTOP="KDE")
    assert choose_platform(kde, AUTO) is None
    x11 = {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "GNOME", "DISPLAY": ":0"}
    assert choose_platform(x11, AUTO) is None


def test_explicit_choices_and_environment_override():
    assert choose_platform(GNOME_WAYLAND, WAYLAND) == "wayland"
    assert choose_platform(GNOME_WAYLAND, X11) == "xcb;wayland"
    no_x = {k: v for k, v in GNOME_WAYLAND.items() if k != "DISPLAY"}
    assert choose_platform(no_x, X11) is None  # no XWayland: keep Wayland
    assert choose_platform(no_x, AUTO) is None
    forced = dict(GNOME_WAYLAND, QT_QPA_PLATFORM="offscreen")
    assert choose_platform(forced, X11) is None
