"""Minimal DXF reader for importing symbols. Pure Python, no third-party packages.

Each named block of the DXF becomes a block definition; the model space becomes one
named after the file when it has drawing objects of its own (not only inserted
blocks). Helper blocks nobody inserts whose names start with "_" (dimension arrows
such as "_Closed") are left out. Supported entities: LINE,
LWPOLYLINE, POLYLINE/VERTEX (bulges become arcs), CIRCLE, ARC, TEXT, MTEXT,
ATTDEF, INSERT (resolved into geometry) and POINT (becomes a connection
point). Coordinates are converted to mm via $INSUNITS and the Y axis is
flipped (DXF Y points up). Everything else is counted as skipped.
"""

import math
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from electrogridy.model.blocks import BlockDefinition
from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import (
    Arc,
    AttributeDefinition,
    Circle,
    ConnectionPoint,
    Entity,
    Line,
    Polyline,
    Text,
)
from electrogridy.model.geometry import Point

# $INSUNITS code -> mm per drawing unit (0 = unitless, taken as mm).
UNIT_TO_MM = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 13: 0.001, 14: 0.1}
SUPPORTED = {
    "LINE",
    "LWPOLYLINE",
    "POLYLINE",
    "CIRCLE",
    "ARC",
    "ELLIPSE",
    "TEXT",
    "MTEXT",
    "ATTDEF",
    "INSERT",
    "POINT",
}
MAX_INSERT_DEPTH = 16
ELLIPSE_SEGMENTS = 72  # polyline segments for a full ellipse


class DxfError(ValueError):
    pass


@dataclass
class DxfImport:
    blocks: list[BlockDefinition]
    skipped: Counter = field(default_factory=Counter)
    units: str = "mm"


@dataclass
class _Raw:
    """One DXF entity as (code, value) pairs, plus following VERTEX/ATTRIB entities."""

    kind: str
    tags: list[tuple[int, str]]
    children: list["_Raw"] = field(default_factory=list)

    def first(self, code: int, default: str = "") -> str:
        for c, v in self.tags:
            if c == code:
                return v
        return default

    def num(self, code: int, default: float = 0.0) -> float:
        value = self.first(code, "")
        try:
            return float(value) if value != "" else default
        except ValueError:
            return default


# -- tokenising --------------------------------------------------------------


def _pairs(text: str) -> Iterator[tuple[int, str]]:
    lines = text.splitlines()
    if len(lines) % 2:
        lines = lines[:-1]
    for i in range(0, len(lines), 2):
        try:
            code = int(lines[i].strip())
        except ValueError as exc:
            raise DxfError(f"invalid group code in line {i + 1}") from exc
        yield code, lines[i + 1].strip()


def _read_text(path: Path) -> str:
    data = Path(path).read_bytes()
    if data.startswith(b"AutoCAD Binary DXF"):
        raise DxfError("binary DXF is not supported, please save as ASCII DXF")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


@dataclass
class _Parsed:
    header: dict[str, str]
    blocks: list[tuple[str, int, Point, list[_Raw]]]  # name, flags, base, entities
    entities: list[_Raw]


def _parse(text: str) -> _Parsed:
    pairs = list(_pairs(text))
    header: dict[str, str] = {}
    blocks: list[tuple[str, int, Point, list[_Raw]]] = []
    entities: list[_Raw] = []
    i, n = 0, len(pairs)
    section = None

    def read_entity(start: int) -> tuple[_Raw, int]:
        kind = pairs[start][1]
        j = start + 1
        tags = []
        while j < n and pairs[j][0] != 0:
            tags.append(pairs[j])
            j += 1
        return _Raw(kind, tags), j

    while i < n:
        code, value = pairs[i]
        if code == 0 and value == "SECTION":
            section = pairs[i + 1][1] if i + 1 < n else None
            i += 2
            continue
        if code == 0 and value == "ENDSEC":
            section = None
            i += 1
            continue
        if section == "HEADER" and code == 9:
            if i + 1 < n:
                header[value] = pairs[i + 1][1]
            i += 2
            continue
        if section in ("BLOCKS", "ENTITIES") and code == 0:
            if value == "BLOCK":
                raw, i = read_entity(i)
                name = raw.first(2)
                flags = int(raw.num(70))
                base = Point(raw.num(10), raw.num(20))
                body: list[_Raw] = []
                while i < n and not (pairs[i][0] == 0 and pairs[i][1] == "ENDBLK"):
                    if pairs[i][0] == 0:
                        ent, i = read_entity(i)
                        body.append(ent)
                    else:
                        i += 1
                blocks.append((name, flags, base, _group(body)))
                i += 1
                continue
            if value == "ENDBLK":
                i += 1
                continue
            ent, i = read_entity(i)
            if section == "ENTITIES":
                entities.append(ent)
            continue
        i += 1
    return _Parsed(header, blocks, _group(entities))


def _group(raw: list[_Raw]) -> list[_Raw]:
    """Attach VERTEX entities to their POLYLINE and drop ATTRIB/SEQEND after INSERT."""
    out: list[_Raw] = []
    owner: _Raw | None = None
    for e in raw:
        if e.kind in ("VERTEX", "ATTRIB"):
            if owner is not None and e.kind == "VERTEX":
                owner.children.append(e)
            continue
        if e.kind == "SEQEND":
            owner = None
            continue
        out.append(e)
        owner = e if e.kind in ("POLYLINE", "INSERT") else None
    return out


# -- geometry ----------------------------------------------------------------


@dataclass(frozen=True)
class _Transform:
    """DXF coordinates (Y up, drawing units) to mm with Y down, plus INSERT nesting."""

    k: float = 1.0  # mm per unit
    a: float = 1.0  # 2x2 linear part in DXF space
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0  # translation in DXF space
    f: float = 0.0

    def then_insert(self, insert: Point, sx: float, sy: float, rot: float, base: Point):
        """Child transform for an INSERT: p -> R*S*(p - base) + insert, then self."""
        cr, sr = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        # local linear part L = R * diag(sx, sy)
        la, lb, lc, ld = cr * sx, -sr * sy, sr * sx, cr * sy
        lx = insert.x - (la * base.x + lb * base.y)
        ly = insert.y - (lc * base.x + ld * base.y)
        return _Transform(
            self.k,
            self.a * la + self.b * lc,
            self.a * lb + self.b * ld,
            self.c * la + self.d * lc,
            self.c * lb + self.d * ld,
            self.a * lx + self.b * ly + self.e,
            self.c * lx + self.d * ly + self.f,
        )

    def point(self, x: float, y: float) -> Point:
        px = self.a * x + self.b * y + self.e
        py = self.c * x + self.d * y + self.f
        return Point(round(px * self.k, 6), round(-py * self.k, 6))

    @property
    def scale(self) -> float:
        return math.sqrt(abs(self.a * self.d - self.b * self.c)) * self.k

    @property
    def rotation(self) -> float:
        """Rotation of R in the decomposition R * diag(+-1, 1) of the linear part."""
        if self.mirrored:
            return math.degrees(math.atan2(-self.c, -self.a))
        return math.degrees(math.atan2(self.c, self.a))

    @property
    def mirrored(self) -> bool:
        return self.a * self.d - self.b * self.c < 0

    def angle(self, a: float) -> float:
        """Map a DXF angle; flipping Y keeps counter-clockwise angles on screen."""
        if self.mirrored:
            return (180.0 - a + self.rotation) % 360
        return (a + self.rotation) % 360


def _bulge_arc(p1: Point, p2: Point, bulge: float, ident: str) -> Arc:
    """Arc for a polyline segment with bulge (in already transformed mm, Y down)."""
    chord = math.hypot(p2.x - p1.x, p2.y - p1.y)
    theta = 4 * math.atan(bulge)  # included angle, positive = counter-clockwise in DXF
    radius = chord / (2 * math.sin(abs(theta) / 2))
    mx, my = (p1.x + p2.x) / 2, (p1.y + p2.y) / 2
    sagitta_dir = 1 if bulge > 0 else -1
    # In Y-down screen space the DXF counter-clockwise direction stays counter-clockwise.
    nx, ny = (p2.y - p1.y) / chord, -(p2.x - p1.x) / chord
    offset = radius - abs(bulge) * chord / 2
    # (nx, ny) is the visual left of p1 -> p2; counter-clockwise arcs have their centre there.
    cx = mx + sagitta_dir * nx * offset
    cy = my + sagitta_dir * ny * offset
    a1 = math.degrees(math.atan2(-(p1.y - cy), p1.x - cx)) % 360
    a2 = math.degrees(math.atan2(-(p2.y - cy), p2.x - cx)) % 360
    start, end = (a1, a2) if bulge > 0 else (a2, a1)
    return Arc(id=ident, center=Point(cx, cy), radius=radius, start_angle=start, end_angle=end)


_MTEXT_CODES = re.compile(r"\\[ACcFfHhLlOoQqTtWw][^;]*;|\\[LlOoKk]")


def _mtext_plain(raw: str) -> str:
    s = raw.replace("\\P", "\n").replace("\\~", " ")
    s = _MTEXT_CODES.sub("", s)
    s = s.replace("{", "").replace("}", "").replace("\\\\", "\\")
    return s


_HALIGN = {0: "left", 1: "center", 2: "right", 4: "center"}


class _Converter:
    def __init__(self, parsed: _Parsed, k: float) -> None:
        self.blocks = {name: (base, ents) for name, _f, base, ents in parsed.blocks}
        self.k = k
        self.skipped: Counter = Counter()
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def convert(self, raws: list[_Raw], t: _Transform, depth: int = 0) -> list[Entity]:
        out: list[Entity] = []
        for r in raws:
            if r.kind not in SUPPORTED:
                self.skipped[r.kind] += 1
                continue
            out += self._entity(r, t, depth)
        return out

    def _entity(self, r: _Raw, t: _Transform, depth: int) -> list[Entity]:
        kind = r.kind
        if kind == "LINE":
            p1, p2 = t.point(r.num(10), r.num(20)), t.point(r.num(11), r.num(21))
            return [] if p1 == p2 else [Line(id=self._id("l"), p1=p1, p2=p2)]
        if kind == "CIRCLE":
            return [
                Circle(
                    id=self._id("c"),
                    center=t.point(r.num(10), r.num(20)),
                    radius=r.num(40) * t.scale,
                )
            ]
        if kind == "ARC":
            a0, a1 = t.angle(r.num(50)), t.angle(r.num(51))
            if t.mirrored:
                a0, a1 = a1, a0
            return [
                Arc(
                    id=self._id("a"),
                    center=t.point(r.num(10), r.num(20)),
                    radius=r.num(40) * t.scale,
                    start_angle=a0,
                    end_angle=a1,
                )
            ]
        if kind == "ELLIPSE":
            return self._ellipse(r, t)
        if kind in ("LWPOLYLINE", "POLYLINE"):
            return self._polyline(r, t)
        if kind in ("TEXT", "MTEXT", "ATTDEF"):
            return self._text(r, t)
        if kind == "POINT":
            return [
                ConnectionPoint(id=self._id("p"), name="", position=t.point(r.num(10), r.num(20)))
            ]
        if kind == "INSERT":
            name = r.first(2)
            if name not in self.blocks or depth >= MAX_INSERT_DEPTH:
                self.skipped["INSERT"] += 1
                return []
            base, ents = self.blocks[name]
            child = t.then_insert(
                Point(r.num(10), r.num(20)), r.num(41, 1.0), r.num(42, 1.0), r.num(50), base
            )
            return [
                e
                for e in self.convert(ents, child, depth + 1)
                if not isinstance(e, AttributeDefinition | ConnectionPoint)
            ]
        return []

    def _ellipse(self, r: _Raw, t: _Transform) -> list[Entity]:
        cx, cy = r.num(10), r.num(20)
        mx, my = r.num(11), r.num(21)
        ratio = r.num(40, 1.0)
        start, end = r.num(41, 0.0), r.num(42, 2 * math.pi)
        major = math.hypot(mx, my)
        if major == 0:
            return []
        sweep = (end - start) % (2 * math.pi) or 2 * math.pi
        full = abs(sweep - 2 * math.pi) < 1e-6
        if abs(ratio - 1) < 1e-6:
            center = t.point(cx, cy)
            if full:
                return [Circle(id=self._id("c"), center=center, radius=major * t.scale)]
            rot = math.degrees(math.atan2(my, mx))
            a0, a1 = t.angle(math.degrees(start) + rot), t.angle(math.degrees(end) + rot)
            if t.mirrored:
                a0, a1 = a1, a0
            return [
                Arc(
                    id=self._id("a"),
                    center=center,
                    radius=major * t.scale,
                    start_angle=a0,
                    end_angle=a1,
                )
            ]
        nx, ny = -my * ratio, mx * ratio  # minor axis, counter-clockwise of the major axis
        steps = max(8, round(ELLIPSE_SEGMENTS * sweep / (2 * math.pi)))
        pts = []
        for i in range(steps + (0 if full else 1)):
            a = start + sweep * i / steps
            x = cx + math.cos(a) * mx + math.sin(a) * nx
            y = cy + math.cos(a) * my + math.sin(a) * ny
            pts.append(t.point(x, y))
        return [Polyline(id=self._id("pl"), points=tuple(pts), closed=full)]

    def _polyline(self, r: _Raw, t: _Transform) -> list[Entity]:
        verts: list[tuple[float, float, float]] = []
        if r.kind == "LWPOLYLINE":
            x = y = None
            bulge = 0.0
            for c, v in r.tags:
                if c == 10:
                    if x is not None and y is not None:
                        verts.append((x, y, bulge))
                    x, y, bulge = float(v), None, 0.0
                elif c == 20:
                    y = float(v)
                elif c == 42:
                    bulge = float(v)
            if x is not None and y is not None:
                verts.append((x, y, bulge))
        else:
            verts = [(v.num(10), v.num(20), v.num(42)) for v in r.children]
        closed = bool(int(r.num(70)) & 1)
        if len(verts) < 2:
            return []
        pts = [t.point(x, y) for x, y, _ in verts]
        bulges = [bg for _, _, bg in verts]
        if t.mirrored:
            bulges = [-bg for bg in bulges]
        if not any(abs(bg) > 1e-9 for bg in bulges):
            return [Polyline(id=self._id("pl"), points=tuple(pts), closed=closed)]
        out: list[Entity] = []
        count = len(pts) if closed else len(pts) - 1
        for i in range(count):
            p1, p2 = pts[i], pts[(i + 1) % len(pts)]
            if p1 == p2:
                continue
            if abs(bulges[i]) > 1e-9:
                out.append(_bulge_arc(p1, p2, bulges[i], self._id("a")))
            else:
                out.append(Line(id=self._id("l"), p1=p1, p2=p2))
        return out

    def _text(self, r: _Raw, t: _Transform) -> list[Entity]:
        height = r.num(40, 2.5) * t.scale
        if height <= 0:
            height = 2.5
        halign_code = int(r.num(72))
        valign_code = int(r.num(74 if r.kind == "ATTDEF" else 73))
        use_align = r.kind != "MTEXT" and (halign_code or valign_code)
        x, y = (r.num(11), r.num(21)) if use_align else (r.num(10), r.num(20))
        position = t.point(x, y)
        rotation = int(round((r.num(50) + t.rotation) % 360))
        halign = _HALIGN.get(halign_code, "left")
        valign = "middle" if valign_code == 2 else "baseline"
        if r.kind == "MTEXT":
            attach = int(r.num(71, 1))
            halign = ("left", "center", "right")[(attach - 1) % 3]
            valign = "middle" if attach in (4, 5, 6) else "baseline"
            text = _mtext_plain(r.first(1) + "".join(v for c, v in r.tags if c == 3))
            return (
                [
                    Text(
                        id=self._id("t"),
                        position=position,
                        text=text,
                        height=height,
                        rotation=rotation,
                        halign=halign,
                        valign=valign,
                    )
                ]
                if text.strip()
                else []
            )
        if r.kind == "ATTDEF":
            tag = r.first(2).strip().upper().replace(" ", "_") or "ATTR"
            return [
                AttributeDefinition(
                    id=self._id("att"),
                    tag=tag,
                    prompt=r.first(3),
                    default=r.first(1),
                    position=position,
                    height=height,
                    rotation=rotation,
                    visible=not (int(r.num(70)) & 1),
                    halign=halign,
                    valign=valign,
                )
            ]
        text = r.first(1)
        if not text.strip():
            return []
        return [
            Text(
                id=self._id("t"),
                position=position,
                text=text,
                height=height,
                rotation=rotation,
                halign=halign,
                valign=valign,
            )
        ]


def _name_connections(entities: list[Entity]) -> list[Entity]:
    """Name connection points 1, 2, ... and point them away from the symbol centre."""
    geometry = [e for e in entities if not isinstance(e, ConnectionPoint)]
    xs, ys = [], []
    for e in geometry:
        for p in _points_of(e):
            xs.append(p.x)
            ys.append(p.y)
    cx = (min(xs) + max(xs)) / 2 if xs else 0.0
    cy = (min(ys) + max(ys)) / 2 if ys else 0.0
    out: list[Entity] = []
    n = 0
    for e in entities:
        if isinstance(e, ConnectionPoint):
            n += 1
            dx, dy = e.position.x - cx, e.position.y - cy
            if abs(dx) >= abs(dy):
                direction = 0 if dx >= 0 else 180
            else:
                direction = 270 if dy > 0 else 90  # Y down: below the centre points down
            e = ConnectionPoint(id=e.id, name=str(n), position=e.position, direction=direction)
        out.append(e)
    return out


def _points_of(e: Entity) -> list[Point]:
    match e:
        case Line():
            return [e.p1, e.p2]
        case Polyline():
            return list(e.points)
        case Circle() | Arc():
            r = e.radius
            return [Point(e.center.x - r, e.center.y - r), Point(e.center.x + r, e.center.y + r)]
        case Text() | AttributeDefinition():
            return [e.position]
    return []


def read_dxf(path: Path) -> DxfImport:
    """Symbols of a DXF file as block definitions (not yet added anywhere)."""
    parsed = _parse(_read_text(path))
    try:
        units = int(float(parsed.header.get("$INSUNITS", "0")))
    except ValueError:
        units = 0
    k = UNIT_TO_MM.get(units, 1.0)
    conv = _Converter(parsed, k)
    t = _Transform(k)
    result: list[BlockDefinition] = []
    inserted = {
        r.first(2)
        for raws in [parsed.entities, *(ents for *_rest, ents in parsed.blocks)]
        for r in raws
        if r.kind == "INSERT"
    }
    for name, flags, base, ents in parsed.blocks:
        # Skip model/paper space and anonymous, external or layout blocks.
        if not name or name.startswith("*") or flags & (1 | 4 | 32):
            continue
        if name.startswith("_") and name not in inserted:
            continue  # dimension arrow and other helper blocks
        entities = _name_connections(conv.convert(ents, t))
        if not entities:
            continue
        result.append(
            BlockDefinition(
                name=name, base_point=t.point(base.x, base.y), entities=EntityContainer(entities)
            )
        )
    own_drawing = any(r.kind != "INSERT" for r in parsed.entities)
    if parsed.entities and (own_drawing or not result):
        entities = _name_connections(conv.convert(parsed.entities, t))
        if entities:
            pts = [p for e in entities for p in _points_of(e)]
            base = Point(min(p.x for p in pts), max(p.y for p in pts)) if pts else Point(0, 0)
            result.append(
                BlockDefinition(
                    name=Path(path).stem, base_point=base, entities=EntityContainer(entities)
                )
            )
    if not result:
        raise DxfError("the file contains no usable drawing objects")
    unit_name = {1: "Zoll", 2: "Fuß", 5: "cm", 6: "m"}.get(units, "mm")
    return DxfImport(result, conv.skipped, unit_name)
