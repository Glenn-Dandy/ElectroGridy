"""Links inside an exported PDF: a click on a reference ("/2.4") jumps to the page and
place it names.

Qt's PDF writer has no way to draw links within the document. Each page it writes
does carry an (empty) array of annotations, so the links are added afterwards as an
incremental update: link annotations and the filled arrays are appended to the file
with a new cross-reference section; the bytes Qt wrote stay as they are. Pure Python.
"""

import re
from dataclasses import dataclass
from pathlib import Path

PT_PER_MM = 72 / 25.4
VIEW_MARGIN = 30.0  # mm left of and above the target that the jump still shows


@dataclass(frozen=True)
class Link:
    """A link area on a page and where it leads, in mm from the top left corner."""

    left: float
    top: float
    right: float
    bottom: float
    page: int  # index of the target page in the file
    x: float
    y: float


class PdfStructureError(ValueError):
    pass


def add_links(path: Path, links: list[list[Link]]) -> int:
    """Add ``links[i]`` to page ``i`` of the PDF at ``path``; returns how many were added.
    Raises ``PdfStructureError`` (leaving the file untouched) when the file is not built
    the way Qt writes it."""
    if not any(links):
        return 0
    data = Path(path).read_bytes()
    starts = re.findall(rb"startxref\s+(\d+)", data)
    if not starts:
        raise PdfStructureError("no startxref")
    previous = int(starts[-1])
    offsets, trailer = _xref(data, previous)
    root = _ref(trailer, b"Root")
    size = _int(trailer, b"Size")
    pages = _pages(data, offsets, _ref(_object(data, offsets, root), b"Pages"))
    if len(pages) < len(links):
        raise PdfStructureError("fewer pages than expected")

    new: dict[int, bytes] = {}
    number = size
    added = 0
    for index, page_links in enumerate(links):
        if not page_links:
            continue
        page = _object(data, offsets, pages[index])
        height = _height(page)
        annots = _ref(page, b"Annots")
        existing = _object(data, offsets, annots).strip()
        if not (existing.startswith(b"[") and existing.endswith(b"]")):
            raise PdfStructureError("annotations are not an array")
        refs = [existing[1:-1].strip()] if existing[1:-1].strip() else []
        for link in page_links:
            target = links_target(pages, link)
            if target is None:
                continue
            target_height = _height(_object(data, offsets, target))
            new[number] = _annotation(link, height, target, target_height)
            refs.append(f"{number} 0 R".encode())
            number += 1
            added += 1
        new[annots] = b"[ " + b" ".join(refs) + b" ]"
    if not added:
        return 0

    out = bytearray(data)
    if not out.endswith(b"\n"):
        out += b"\n"
    positions: dict[int, int] = {}
    for num in sorted(new):
        positions[num] = len(out)
        out += f"{num} 0 obj\n".encode() + new[num] + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 1\n0000000000 65535 f \n"
    for run in _runs(sorted(positions)):
        out += f"{run[0]} {len(run)}\n".encode()
        for num in run:
            out += f"{positions[num]:010d} 00000 n \n".encode()
    extra = b""
    for key in (b"Info", b"ID"):
        found = re.search(rb"/" + key + rb"\s*(\d+\s+\d+\s+R|\[[^\]]*\])", trailer)
        if found:
            extra += b"/" + key + b" " + found.group(1) + b"\n"
    out += (
        b"trailer\n<<\n"
        + f"/Size {number}\n/Root {root} 0 R\n/Prev {previous}\n".encode()
        + extra
        + b">>\nstartxref\n"
        + f"{xref_at}\n".encode()
        + b"%%EOF\n"
    )
    Path(path).write_bytes(bytes(out))
    return added


def links_target(pages: list[int], link: Link) -> int | None:
    return pages[link.page] if 0 <= link.page < len(pages) else None


def _annotation(link: Link, height: float, target: int, target_height: float) -> bytes:
    k = PT_PER_MM
    rect = (link.left * k, height - link.bottom * k, link.right * k, height - link.top * k)
    left = max(0.0, link.x - VIEW_MARGIN) * k
    top = target_height - max(0.0, link.y - VIEW_MARGIN) * k
    numbers = " ".join(f"{v:.2f}" for v in rect)
    return (
        f"<< /Type /Annot /Subtype /Link /Rect [{numbers}] /Border [0 0 0] "
        f"/Dest [{target} 0 R /XYZ {left:.2f} {top:.2f} null] >>"
    ).encode()


def _runs(numbers: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for n in numbers:
        if runs and runs[-1][-1] == n - 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def _xref(data: bytes, at: int) -> tuple[dict[int, int], bytes]:
    """Object offsets of a classic cross-reference table and the trailer after it."""
    if data[at : at + 4] != b"xref":
        raise PdfStructureError("no cross-reference table")
    offsets: dict[int, int] = {}
    lines = data[at:].split(b"\n")
    i = 1
    while i < len(lines):
        head = lines[i].strip().split()
        if not head or head[0] == b"trailer":
            break
        if len(head) != 2:
            raise PdfStructureError("bad cross-reference section")
        start, count = int(head[0]), int(head[1])
        for n in range(count):
            entry = lines[i + 1 + n].split()
            if len(entry) >= 3 and entry[2] == b"n":
                offsets[start + n] = int(entry[0])
        i += 1 + count
    end = data.find(b"startxref", at)
    trailer = data[data.find(b"trailer", at) : end]
    return offsets, trailer


def _object(data: bytes, offsets: dict[int, int], number: int) -> bytes:
    if number not in offsets:
        raise PdfStructureError(f"object {number} missing")
    start = offsets[number]
    head = re.match(rb"\s*" + str(number).encode() + rb"\s+0\s+obj", data[start : start + 40])
    if head is None:
        raise PdfStructureError(f"object {number} not where the table says")
    end = data.find(b"endobj", start)
    return data[start + head.end() : end]


def _ref(text: bytes, key: bytes) -> int:
    found = re.search(rb"/" + key + rb"\s+(\d+)\s+0\s+R", text)
    if found is None:
        raise PdfStructureError(f"no /{key.decode()} reference")
    return int(found.group(1))


def _int(text: bytes, key: bytes) -> int:
    found = re.search(rb"/" + key + rb"\s+(\d+)", text)
    if found is None:
        raise PdfStructureError(f"no /{key.decode()}")
    return int(found.group(1))


def _height(page: bytes) -> float:
    found = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]", page)
    if found is None:
        raise PdfStructureError("page without /MediaBox")
    return float(found.group(4)) - float(found.group(2))


def _pages(data: bytes, offsets: dict[int, int], node: int) -> list[int]:
    """Page objects in order below a pages node."""
    text = _object(data, offsets, node)
    if re.search(rb"/Type\s*/Page\b(?!s)", text):
        return [node]
    kids = re.search(rb"/Kids\s*\[([^\]]*)\]", text)
    if kids is None:
        raise PdfStructureError("pages node without /Kids")
    out: list[int] = []
    for kid in re.findall(rb"(\d+)\s+0\s+R", kids.group(1)):
        out += _pages(data, offsets, int(kid))
    return out
