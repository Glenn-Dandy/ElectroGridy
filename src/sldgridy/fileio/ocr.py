"""Texts read from a picture with the tesseract program (packages tesseract-ocr and
tesseract-ocr-deu; the Windows installer brings its own copy).

``read_words`` runs it on a PNG and returns the words with their boxes in pixels;
``text_lines`` puts the words of one label together. Both are free of Qt.
"""

import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

TIMEOUT = 120  # seconds
MIN_CONFIDENCE = 65.0
MIN_CONFIDENCE_LONG = 40.0  # for words of five letters or more and device tags
# Device tags (-Y04, -K1, -X12) as read, letters for digits included: rarely chance.
TAG = re.compile(r"^-[A-Z]{1,3}[0-9OlI]{1,3}$")
LOOKALIKES = str.maketrans({"¥": "Y", "€": "E", "§": "S"})
QUOTES = "\"'“”„‚‘’`´"
# Below the line or above the letters: the box is taller than the capitals.
REACHING_OUT = set("gjpqyQ(),;_[]{}|$")


@dataclass(frozen=True)
class Word:
    text: str
    left: float
    top: float
    width: float
    height: float
    confidence: float
    line: tuple[int, int, int]  # block, paragraph, line as numbered by tesseract


@dataclass(frozen=True)
class TextLine:
    """A label: its text, the left end of its baseline, the height of its capitals."""

    text: str
    left: float
    top: float
    right: float
    bottom: float
    baseline: float
    cap_height: float
    confidence: float


def _bundled() -> Path | None:
    """The copy next to the program (Windows installer)."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        return None
    exe = Path(base) / "tesseract" / "tesseract.exe"
    return exe if exe.exists() else None


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    bundled = _bundled()
    if bundled is not None:  # the snap sets TESSDATA_PREFIX in its start script
        env["TESSDATA_PREFIX"] = str(bundled.parent / "tessdata")
    return env


def _command() -> str | None:
    bundled = _bundled()
    return str(bundled) if bundled is not None else shutil.which("tesseract")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console window on Windows
    return subprocess.run(
        args,
        capture_output=True,
        timeout=TIMEOUT,
        env=_environment(),
        creationflags=flags,
        check=False,
    )


@cache
def languages() -> str:
    """German and English as far as installed, joined for -l; empty without tesseract."""
    command = _command()
    if command is None:
        return ""
    try:
        listed = _run([command, "--list-langs"]).stdout.decode(errors="replace").split()
    except (OSError, subprocess.SubprocessError):
        return ""
    return "+".join(lang for lang in ("deu", "eng") if lang in listed)


def available() -> bool:
    return bool(languages())


def parse_tsv(text: str) -> list[Word]:
    out = []
    for row in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        word = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf") or -1)
            box = [float(row[k]) for k in ("left", "top", "width", "height")]
            line = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        except (KeyError, TypeError, ValueError):
            continue
        if word and confidence >= 0:
            out.append(Word(word, *box, confidence, line))
    return out


def read_words(png: bytes) -> list[Word]:
    """Words tesseract finds scattered over the picture (sparse text)."""
    command, langs = _command(), languages()
    if command is None or not langs:
        return []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder, "text.png")
        path.write_bytes(png)
        try:
            done = _run([command, str(path), "stdout", "-l", langs, "--psm", "11", "tsv"])
        except (OSError, subprocess.SubprocessError):
            return []
    return parse_tsv(done.stdout.decode("utf-8", errors="replace"))


def _plausible(word: Word) -> bool:
    text = word.text.strip(QUOTES)
    letters = sum(c.isalnum() for c in text)
    if not letters:
        return False
    if word.confidence < MIN_CONFIDENCE and not (
        (letters >= 5 or TAG.match(text)) and word.confidence >= MIN_CONFIDENCE_LONG
    ):
        return False
    # Single signs are mostly bits of lines or symbols; single digits number terminals.
    if len(text) == 1:
        return text.isdigit() and word.confidence >= 80
    if letters == 1:  # (2), 5.
        return any(c.isdigit() for c in text) and word.confidence >= 85
    if len(text) == 2:  # A1, 10, -X; lowercase pairs are bits of letters
        return word.confidence >= 85 and not (text.isalpha() and text.islower())
    return True


def _digits(part: str) -> str:
    return part.replace("O", "0").replace("l", "1").replace("I", "1")


def corrected(text: str) -> str:
    """Letters read for digits in device tags and terminals (-YO4 is -Y04, -Kl is -K1,
    Al is A1), DC read as OC; quotes the letters picked up from lines nearby."""
    words = []
    for word in text.translate(LOOKALIKES).split():
        word = word.strip(QUOTES) or word
        word = re.sub(
            r"^(-[A-Z]{1,3}?)([0-9OlI]*[0-9l][0-9OlI]*)$",
            lambda m: m[1] + _digits(m[2]),
            word,
        )
        word = re.sub(r"^([A-Z])([lI])$", r"\g<1>1", word)
        words.append(word)
    out = " ".join(words)
    return re.sub(r"(?<![\w])[O0]C(?= ?\d+ ?V\b)", "DC", out)


def text_lines(words: list[Word]) -> list[TextLine]:
    """Words of one line as tesseract numbered them, split where the gap is wider than
    the letters are high (two labels side by side)."""
    groups: dict[tuple, list[Word]] = {}
    for word in words:
        if _plausible(word):
            groups.setdefault(word.line, []).append(word)
    out = []
    for group in groups.values():
        group.sort(key=lambda w: w.left)
        parts = [[group[0]]]
        for word in group[1:]:
            last = parts[-1][-1]
            if word.left - (last.left + last.width) > 1.5 * max(last.height, word.height):
                parts.append([])
            parts[-1].append(word)
        out += [line for line in map(_line, parts) if _proportioned(line)]
    return out


def _proportioned(line: TextLine) -> bool:
    """As long as its letters make it: letters read across a text turned sideways
    come out few and high."""
    per_letter = (line.right - line.left) / max(1e-9, line.cap_height * len(line.text))
    return 0.3 <= per_letter <= 1.6


def same_size(lines: list, factor: float = 2.2) -> list:
    """Lines whose letters are about as high as those of the sure ones (texts of a
    drawing differ little in size; bits of symbols read as letters do)."""
    sure = sorted(x.cap_height for x in lines if x.confidence >= 80 and len(x.text) >= 3)
    if not sure:
        return lines
    usual = sure[len(sure) // 2]
    return [x for x in lines if usual / (factor * 1.5) <= x.cap_height <= usual * factor]


def _line(words: list[Word]) -> TextLine:
    top = min(w.top for w in words)
    bottom = max(w.top + w.height for w in words)
    plain = [w for w in words if not REACHING_OUT & set(w.text)]
    if plain:
        # Words without parts below the line or above the capitals give it exactly.
        baseline = max(w.top + w.height for w in plain)
        cap = sorted(w.height for w in plain)[len(plain) // 2]
    else:
        cap = (bottom - top) / 1.3
        baseline = top + cap * 1.05
    return TextLine(
        text=corrected(" ".join(w.text for w in words)),
        left=min(w.left for w in words),
        top=top,
        right=max(w.left + w.width for w in words),
        bottom=bottom,
        baseline=baseline,
        cap_height=cap,
        confidence=sum(w.confidence for w in words) / len(words),
    )
