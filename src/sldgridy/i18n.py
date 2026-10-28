"""User interface languages: German source texts with an English dictionary.

German is the source language in the code (``tr()`` texts). English comes
from ``resources/i18n/en.json`` through a small QTranslator, so no Qt
translation tools are needed.
"""

import json
import os
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QSettings, QTranslator

I18N_DIR = Path(__file__).resolve().parent / "resources" / "i18n"
LANGUAGES = {"de": "Deutsch", "en": "English"}
SETTINGS_KEY = "ui/language"

_current = "de"


class DictTranslator(QTranslator):
    """Looks up the German source text, ignoring the context."""

    def __init__(self, table: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.table = table

    def translate(self, context, source_text, disambiguation=None, n=-1):  # noqa: D102
        # None becomes a null QString, which tells Qt "not translated, keep the source".
        # An empty string would count as a translation and blank the text.
        return self.table.get(source_text)

    def isEmpty(self) -> bool:  # noqa: N802 - Qt API
        return not self.table


# Qt's own standard buttons in German, for systems without Qt's translations
# (qt6-translations-l10n is not installed everywhere).
QT_BUTTONS_DE = {
    "Save": "Speichern",
    "Save All": "Alles speichern",
    "Open": "Öffnen",
    "&Yes": "&Ja",
    "Yes to &All": "Ja, &alle",
    "&No": "&Nein",
    "N&o to All": "N&ein, keine",
    "Abort": "Abbrechen",
    "Retry": "Wiederholen",
    "Ignore": "Ignorieren",
    "Close": "Schließen",
    "Cancel": "Abbrechen",
    "Discard": "Verwerfen",
    "Help": "Hilfe",
    "Apply": "Anwenden",
    "Reset": "Zurücksetzen",
    "Restore Defaults": "Voreinstellungen",
}


class QtButtonsTranslator(QTranslator):
    """German texts of Qt's standard buttons (context QPlatformTheme)."""

    def translate(self, context, source_text, disambiguation=None, n=-1):  # noqa: D102
        if context != "QPlatformTheme":
            return None
        return QT_BUTTONS_DE.get(source_text)

    def isEmpty(self) -> bool:  # noqa: N802 - Qt API
        return False


def load_table(language: str) -> dict[str, str]:
    path = I18N_DIR / f"{language}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def system_language() -> str:
    return "de" if QLocale.system().name().lower().startswith("de") else "en"


def configured_language() -> str:
    value = QSettings().value(SETTINGS_KEY, "")
    return value if value in LANGUAGES else system_language()


def install(app: QCoreApplication, language: str) -> QTranslator | None:
    """Activate ``language`` for this run. German texts are the source; only Qt's own
    texts (buttons such as Save, Discard, Cancel; print and file dialogs) need German."""
    global _current
    _current = language if language in LANGUAGES else "de"
    if _current == "de":
        return install_qt_german(app)
    translator = DictTranslator(load_table(_current), app)
    app.installTranslator(translator)
    return translator


def install_qt_german(app: QCoreApplication) -> QTranslator:
    """Qt's German translation when installed; the standard buttons in any case."""
    buttons = QtButtonsTranslator(app)
    app.installTranslator(buttons)
    qt = QTranslator(app)
    for path in qt_translation_dirs():
        if qt.load("qtbase_de", path):
            app.installTranslator(qt)  # installed last, asked first
            return qt
    return buttons


def qt_translation_dirs() -> list[str]:
    """Where Qt's translations may be: inside the snap, Qt's own directory, next to
    PyQt6 (pip and the Windows build)."""
    dirs = []
    if os.environ.get("SNAP"):
        dirs.append(os.path.join(os.environ["SNAP"], "usr", "share", "qt6", "translations"))
    dirs.append(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    import PyQt6

    dirs.append(str(Path(PyQt6.__file__).parent / "Qt6" / "translations"))
    return dirs


def current() -> str:
    return _current


def ui_locale() -> QLocale:
    """Number formatting of the active language (decimal comma or point)."""
    if _current == "de":
        return QLocale(QLocale.Language.German, QLocale.Country.Germany)
    return QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom)


def library_text(text: str) -> str:
    """Display text for names, categories and prompts stored in libraries and drawings."""
    return QCoreApplication.translate("library", text) if text else text
