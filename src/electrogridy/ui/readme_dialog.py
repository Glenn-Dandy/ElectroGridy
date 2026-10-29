"""Help > README: the user guide (README.md) shown inside the program, offline."""

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

_PACKAGE_DIR = Path(__file__).resolve().parent.parent


def readme_path() -> Path | None:
    """README.md shipped with the package, or the one of the source tree."""
    for candidate in (
        _PACKAGE_DIR / "resources" / "README.md",  # .deb and snap
        _PACKAGE_DIR.parent.parent / "README.md",  # running from the source tree
    ):
        if candidate.is_file():
            return candidate
    return None


def readme_markdown() -> str:
    path = readme_path()
    if path is None:
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    # Badges are remote images; offline they would only show broken icons.
    return "\n".join(line for line in lines if not line.startswith("[!["))


class ReadmeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("README"))
        self.browser = QTextBrowser()
        # Links within the README (#deutsch) jump to the heading, others open the browser.
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._follow)
        text = readme_markdown()
        if text:
            self.browser.setMarkdown(text)
        else:
            self.browser.setPlainText(
                self.tr("Die Anleitung liegt unter https://github.com/Glenn-Dandy/ElectroGridy")
            )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.browser)
        layout.addWidget(buttons)
        self.resize(820, 720)

    def _follow(self, url: QUrl) -> None:
        if url.scheme() or not url.fragment():
            QDesktopServices.openUrl(url)
            return
        self.jump_to_heading(url.fragment())

    def jump_to_heading(self, fragment: str) -> bool:
        """Scroll to the first heading whose GitHub-style anchor is ``fragment``."""
        block = self.browser.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() and _anchor(block.text()) == fragment:
                cursor = QTextCursor(block)
                self.browser.setTextCursor(cursor)
                bar = self.browser.verticalScrollBar()
                bar.setValue(bar.maximum())  # then up, so the heading ends at the top
                self.browser.ensureCursorVisible()
                return True
            block = block.next()
        return False


def _anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, spaces to dashes, punctuation dropped."""
    kept = "".join(c for c in heading.strip().lower() if c.isalnum() or c in " -_")
    return kept.replace(" ", "-")
