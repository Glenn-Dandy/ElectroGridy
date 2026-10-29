import ast
import json
import pathlib
import string

import pytest
from PyQt6.QtCore import QCoreApplication

from electrogridy import i18n
from electrogridy.fileio.files import load_library
from electrogridy.fileio.paths import symbols_dir, system_library_dir, system_template_dir
from electrogridy.fileio.templates import load_frame
from electrogridy.model.document import DOC_KINDS, PAGE_KINDS, Document
from electrogridy.model.reports import COLUMNS, COVER_CAPTIONS
from electrogridy.model.title_block import CAPTIONS, FIELD_LABELS

SRC = pathlib.Path(__file__).parents[1] / "src" / "electrogridy"
EN = i18n.load_table("en")
# Texts kept in the model and translated through variables.
MODEL_TEXTS = {
    *FIELD_LABELS.values(),
    *CAPTIONS.values(),
    *PAGE_KINDS.values(),
    *DOC_KINDS.values(),
    *(caption for columns in COLUMNS.values() for caption, _ in columns),
    *COVER_CAPTIONS,
}
EXTRA = {"von", "Z{row}/S{col}", "Zoll", "Fuß", *MODEL_TEXTS}


def test_model_texts_are_translated():
    assert sorted(t for t in MODEL_TEXTS if t not in EN) == []


def source_texts() -> set[str]:
    """Every literal passed to tr() or QCoreApplication.translate() in the code."""
    texts: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "tr" and node.args and isinstance(node.args[0], ast.Constant):
                texts.add(node.args[0].value)
            elif (
                name == "translate"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
            ):
                texts.add(node.args[1].value)
    return texts


def fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}


def test_every_ui_text_has_an_english_translation():
    missing = sorted(t for t in source_texts() | EXTRA if t not in EN)
    assert missing == []


def test_placeholders_match():
    wrong = [k for k, v in EN.items() if fields(k) != fields(v)]
    assert wrong == []


def test_no_unused_translations_for_ui_strings():
    known = source_texts() | EXTRA | library_texts()
    unused = sorted(k for k in EN if k not in known)
    assert unused == []


def library_texts() -> set[str]:
    texts: set[str] = set()
    for path in [*system_library_dir().glob("*.grdylib"), *symbols_dir().glob("*.grdylib")]:
        title, defs = load_library(path)
        texts.add(title)
        for d in defs:
            texts |= {d.name, d.category, d.description}
            texts |= {a.prompt for a in d.attribute_definitions()}
    for path in system_template_dir().glob("*.grdyframe"):
        texts.add(load_frame(path)[0])
    texts.discard("")
    return texts


def test_shipped_library_and_templates_translated():
    assert sorted(t for t in library_texts() if t not in EN) == []


@pytest.fixture
def english(qapp):
    translator = i18n.DictTranslator(EN)
    qapp.installTranslator(translator)
    previous = i18n._current
    i18n._current = "en"
    yield
    i18n._current = previous
    qapp.removeTranslator(translator)


def test_translator_switches_texts_and_numbers(english):
    assert QCoreApplication.translate("MainWindow", "&Datei") == "&File"
    assert i18n.library_text("Leitungsschutzschalter") == "Miniature circuit breaker"
    assert QCoreApplication.translate("x", "unbekannt") == "unbekannt"
    assert i18n.ui_locale().decimalPoint() == "."
    from electrogridy.ui.styles import mm_label

    assert mm_label(2.5) == "2.5 mm"


def test_english_title_block_and_fields(english):
    from electrogridy.view.display import title_block_parts, title_labels

    doc = Document.new("Sheet 1", title_labels())
    captions = {e.text for e in doc.blocks["Schriftfeld"].entities if hasattr(e, "text")}
    assert {"Project", "Drawn by", "Sheet", "Revision"} <= captions
    texts = {getattr(p, "text", None) for p in title_block_parts(doc, doc.sheets[0])}
    assert "1 of 1" in texts and "A0 landscape" in texts


def test_german_is_the_default_text():
    doc = Document.new("Blatt 1")
    captions = {e.text for e in doc.blocks["Schriftfeld"].entities if hasattr(e, "text")}
    assert "Projekt" in captions
    assert doc.field_values(doc.sheets[0].id)["BLATT"] == "1 von 1"


def test_language_setting(qapp):
    from PyQt6.QtCore import QSettings

    QSettings().setValue(i18n.SETTINGS_KEY, "en")
    assert i18n.configured_language() == "en"
    QSettings().setValue(i18n.SETTINGS_KEY, "xx")
    assert i18n.configured_language() == i18n.system_language()
    QSettings().remove(i18n.SETTINGS_KEY)


def test_translation_file_is_valid_json():
    path = SRC / "resources" / "i18n" / "en.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert all(isinstance(v, str) and v for v in data.values())


def test_qt_buttons_are_german_in_german_mode(qapp, monkeypatch):
    from PyQt6.QtWidgets import QDialogButtonBox

    monkeypatch.setattr(i18n, "_current", "de")
    buttons = i18n.QtButtonsTranslator()
    qapp.installTranslator(buttons)
    try:
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Discard
            | QDialogButtonBox.StandardButton.Cancel
        )
        texts = {b.text().replace("&", "") for b in box.buttons()}
        assert texts == {"Speichern", "Verwerfen", "Abbrechen"}
    finally:
        qapp.removeTranslator(buttons)
    assert QCoreApplication.translate("MainWindow", "Save") == "Save"  # only Qt's context


def test_qt_translations_are_looked_for_in_the_snap(monkeypatch):
    monkeypatch.setenv("SNAP", "/snap/electrogridy/7")
    dirs = i18n.qt_translation_dirs()
    import os

    assert dirs[0] == os.path.join("/snap/electrogridy/7", "usr", "share", "qt6", "translations")
    assert any(d.endswith("translations") for d in dirs[1:])
