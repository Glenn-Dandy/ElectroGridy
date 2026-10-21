"""Project menu: create missing report pages (cover, contents, lists) and export the
lists as CSV. The content of these pages is generated live (``model/reports.py``)."""

import csv
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication, QObject
from PyQt6.QtWidgets import QFileDialog

from sldgridy.commands.blocks import AddBlockCommand
from sldgridy.commands.sheets import AddSheetCommand
from sldgridy.model.document import CABLES, COVER, PAGE_FORMAT, PARTS, TERMINALS, TOC, Document
from sldgridy.model.paper import Orientation
from sldgridy.model.reports import COLUMNS, report_rows, table_area
from sldgridy.ui.page_dialog import PageSpec

if TYPE_CHECKING:
    from sldgridy.ui.main_window import MainWindow

FILES = {
    TOC: "inhalt.csv",
    PARTS: "stueckliste.csv",
    TERMINALS: "klemmenplan.csv",
    CABLES: "kabelliste.csv",
}


def _tr_reports(text: str) -> str:
    return QCoreApplication.translate("reports", text)


class ReportController(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.w = window

    def tr(self, text: str) -> str:  # noqa: D102 - stable translation context
        return self.w.tr(text)

    @property
    def doc(self) -> Document:
        return self.w.document

    def headers(self, kind: str) -> list[str]:
        return [_tr_reports(caption) for caption, _ in COLUMNS[kind]]

    def rows(self, kind: str) -> list[list[str]]:
        return report_rows(self.doc, kind, _tr_reports)

    # -- report pages ---------------------------------------------------------------

    def complete_pages(self) -> list[str]:
        """Add what is missing: cover and contents at the front, the lists that have
        content at the end, and further pages where a list does not fit. One undo step;
        returns the types of the pages added."""
        if self.w.blocks.in_editor():
            self.w.message(self.tr("Zuerst den Blockeditor schließen"))
            return []
        added: list[str] = []
        self.w.begin_macro(self.tr("Listenseiten ergänzen"))
        for kind, front in ((COVER, 0), (TOC, 1)):
            if not any(p.kind == kind for p in self.doc.sheets):
                self._add(kind, min(front, len(self.doc.sheets)))
                added.append(kind)
        for kind in (PARTS, TERMINALS, CABLES):
            rows = len(self.rows(kind))
            have = [i for i, p in enumerate(self.doc.sheets) if p.kind == kind]
            if not have and not rows:
                continue
            if not have:
                self._add(kind, len(self.doc.sheets))
                added.append(kind)
                have = [len(self.doc.sheets) - 1]
            per_page = table_area(self.doc.sheets[have[0]]).rows
            needed = max(1, -(-rows // per_page))
            for _ in range(needed - len(have)):
                last = max(i for i, p in enumerate(self.doc.sheets) if p.kind == kind)
                self._add(kind, last + 1)
                added.append(kind)
        # The contents may need more pages once everything is in.
        toc_rows = len(self.doc.sheets)
        have = [i for i, p in enumerate(self.doc.sheets) if p.kind == TOC]
        if have:
            per_page = table_area(self.doc.sheets[have[0]]).rows
            while len(have) * per_page < toc_rows + 0:
                self._add(TOC, have[-1] + 1)
                added.append(TOC)
                toc_rows += 1
                have = [i for i, p in enumerate(self.doc.sheets) if p.kind == TOC]
        self.w.end_macro()
        if added:
            from sldgridy.ui.page_dialog import kind_name

            self.w.message(
                self.tr("Seiten ergänzt: {kinds}").format(
                    kinds=", ".join(kind_name(k) for k in added)
                )
            )
        else:
            self.w.message(self.tr("Alle Listenseiten sind vorhanden"))
        return added

    def _add(self, kind: str, index: int) -> None:
        spec = PageSpec(kind, "", "", "", PAGE_FORMAT, Orientation.LANDSCAPE, False)
        page, needed = self.w.sheets.build_page(spec)
        for definition in needed:
            if definition.name not in self.doc.blocks:
                self.w.push(AddBlockCommand(self.doc, definition, ""))
        self.w.push(AddSheetCommand(self.doc, index, page, ""))

    # -- CSV ---------------------------------------------------------------------

    def export_csv(self, directory: Path | None = None) -> list[Path]:
        if directory is None:
            chosen = QFileDialog.getExistingDirectory(
                self.w, self.tr("Listen als CSV exportieren"), self.w.last_dir()
            )
            if not chosen:
                return []
            directory = Path(chosen)
        written = []
        for kind in (TOC, PARTS, TERMINALS, CABLES):
            path = directory / FILES[kind]
            # Semicolons and a byte order mark: opens cleanly in spreadsheet programs.
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(self.headers(kind))
                writer.writerows(self.rows(kind))
            written.append(path)
        self.w.message(
            self.tr("Exportiert: {files}").format(files=", ".join(p.name for p in written))
        )
        return written
