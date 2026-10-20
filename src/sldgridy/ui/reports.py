"""Project menu: create the report pages and export the reports as CSV."""

import csv
import math
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog

from sldgridy.commands.sheets import AddSheetCommand, RemoveSheetCommand
from sldgridy.model.document import PAGES, Document, new_page
from sldgridy.model.netlist import netlist
from sldgridy.model.reports import (
    CABLES,
    PARTS,
    TERMINALS,
    TOC,
    cable_rows,
    parts_rows,
    report_pages,
    rows_per_page,
    terminal_rows,
    toc_rows,
)

if TYPE_CHECKING:
    from sldgridy.ui.main_window import MainWindow

WIDTHS = {
    TOC: (2, 1, 5),
    PARTS: (0.6, 0.7, 2.2, 1.6, 2, 3),
    TERMINALS: (1, 0.8, 3, 3, 1.5),
    CABLES: (0.8, 2, 0.6, 2, 2, 1.6),
}
FILES = {
    TOC: "inhalt.csv",
    PARTS: "stueckliste.csv",
    TERMINALS: "klemmenplan.csv",
    CABLES: "kabelliste.csv",
}


class ReportController(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.w = window

    def tr(self, text: str) -> str:  # noqa: D102 - stable translation context
        return self.w.tr(text)

    @property
    def doc(self) -> Document:
        return self.w.document

    def title(self, kind: str) -> str:
        return {
            TOC: self.tr("Inhaltsverzeichnis"),
            PARTS: self.tr("Stückliste"),
            TERMINALS: self.tr("Klemmenplan"),
            CABLES: self.tr("Kabelliste"),
        }[kind]

    def headers(self, kind: str) -> list[str]:
        return {
            TOC: [self.tr("Anlage/Ort"), self.tr("Seite"), self.tr("Beschreibung")],
            PARTS: [
                self.tr("Pos."),
                self.tr("Menge"),
                self.tr("Bezeichnung"),
                self.tr("Hersteller"),
                self.tr("Typ"),
                self.tr("BMK"),
            ],
            TERMINALS: [
                self.tr("Leiste"),
                self.tr("Klemme"),
                self.tr("Ziel innen"),
                self.tr("Ziel außen"),
                self.tr("Stelle"),
            ],
            CABLES: [
                self.tr("Kabel"),
                self.tr("Typ"),
                self.tr("Adern"),
                self.tr("Von"),
                self.tr("Nach"),
                self.tr("Stelle"),
            ],
        }[kind]

    def rows(self, kind: str, doc: Document | None = None, nl=None) -> list[list[str]]:
        doc = doc or self.doc
        if kind == TOC:
            return toc_rows(doc)
        if kind == PARTS:
            return parts_rows(doc)
        if kind == TERMINALS:
            return terminal_rows(doc, nl)
        return cable_rows(doc, nl)

    # -- report pages ---------------------------------------------------------

    def create_pages(self) -> list[str]:
        """Replace the report pages: table of contents, parts list, terminal plan and
        cable list behind the other pages (one undo step). Returns the kinds made."""
        if self.w.blocks.in_editor():
            self.w.message(self.tr("Zuerst den Blockeditor schließen"))
            return []
        self.w.begin_macro(self.tr("Auswertungen erzeugen"))
        for page in [p for p in self.doc.pages if p.report]:
            self.w.push(RemoveSheetCommand(self.doc, page.id, ""))
        nl = netlist(self.doc)
        made = []
        others = []
        for kind in (PARTS, TERMINALS, CABLES):
            rows = self.rows(kind, nl=nl)
            if rows:
                others += report_pages(
                    kind, self.title(kind), self.headers(kind), WIDTHS[kind], rows
                )
                made.append(kind)
        # The table of contents lists itself and the other reports: find how many
        # pages it needs with placeholders, then fill it from the final page order.
        per_page = rows_per_page(new_page())
        count = 1
        while True:
            placeholders = report_pages(
                TOC, self.title(TOC), [], WIDTHS[TOC], [[""]] * (per_page * (count - 1) + 1)
            )
            probe = Document(pages=[*self.doc.pages, *placeholders, *others])
            needed = max(1, math.ceil(len(toc_rows(probe)) / per_page))
            if needed == count:
                break
            count = needed
        toc = report_pages(TOC, self.title(TOC), self.headers(TOC), WIDTHS[TOC], toc_rows(probe))
        start = len(self.doc.pages)
        for i, page in enumerate([*toc, *others]):
            self.w.push(AddSheetCommand(self.doc, start + i, page, "", kind=PAGES))
        self.w.end_macro()
        self.w.message(
            self.tr("Auswertungen erzeugt: {kinds}").format(
                kinds=", ".join(self.title(k) for k in [TOC, *made])
            )
        )
        if self.w.sheets.pages_mode:
            self.w.sheets.show_sheet(toc[0].id)
        return [TOC, *made]

    # -- CSV ---------------------------------------------------------------------

    def export_csv(self, directory: Path | None = None) -> list[Path]:
        if directory is None:
            chosen = QFileDialog.getExistingDirectory(
                self.w, self.tr("Auswertungen als CSV exportieren"), self.w.last_dir()
            )
            if not chosen:
                return []
            directory = Path(chosen)
        nl = netlist(self.doc)
        written = []
        for kind in (TOC, PARTS, TERMINALS, CABLES):
            path = directory / FILES[kind]
            # Semicolons and a byte order mark: opens cleanly in spreadsheet programs.
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(self.headers(kind))
                writer.writerows(self.rows(kind, nl=nl))
            written.append(path)
        self.w.message(
            self.tr("Exportiert: {files}").format(files=", ".join(p.name for p in written))
        )
        return written
