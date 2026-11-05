"""Straightening a photographed sheet: the drawing's own long lines show how it lies.

Pure Python. Pieces of nearly horizontal lines (and of nearly vertical ones, found in
the picture turned a quarter) are found as connected runs of ink. First a perspective
step makes both families of lines parallel to the axes (their vanishing points sent
to infinity), then two smooth surfaces of cubic B-splines take out the bending of the
sheet: under the map (u, v) every horizontal piece has one v and every vertical piece
one u. Turned, tilted and bent sheets come out straight.
"""

import math
import re
from dataclasses import dataclass


@dataclass
class Piece:
    """Samples (along, across) of one piece of line, in picture pixels."""

    points: list[tuple[float, float]]
    weights: list[float]

    @property
    def extent(self) -> float:
        xs = [p[0] for p in self.points]
        return max(xs) - min(xs)


def line_pieces(
    width: int,
    height: int,
    ink: bytes,
    min_run: int,
    min_extent: float,
    max_thickness: int,
    bin_px: int = 12,
) -> list[Piece]:
    """Pieces of nearly horizontal lines: runs of at least ``min_run`` pixels of ink
    along the rows (each row taken together with its neighbours, so slightly sloped
    lines run on), joined where they overlap on neighbouring rows."""
    rows = [ink[y * width : (y + 1) * width] for y in range(height)]
    as_int = [int.from_bytes(r, "big") for r in rows]
    pattern = re.compile(rb"\x01{%d,}" % min_run)
    runs: list[tuple[int, int, int]] = []  # y, x1, x2
    starts: list[int] = []  # index of the first run of each row
    for y in range(height):
        starts.append(len(runs))
        a = as_int[y - 1] if y else 0
        b = as_int[y + 1] if y + 1 < height else 0
        smeared = (a | as_int[y] | b).to_bytes(width, "big")
        for m in pattern.finditer(smeared):
            runs.append((y, m.start(), m.end()))
    starts.append(len(runs))
    parent = list(range(len(runs)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(1, height):
        prev = range(starts[y - 1], starts[y])
        cur = range(starts[y], starts[y + 1])
        j0 = prev.start
        for i in cur:
            _, x1, x2 = runs[i]
            for j in range(j0, prev.stop):
                _, a1, a2 = runs[j]
                if a2 < x1:
                    j0 = j + 1
                    continue
                if a1 > x2:
                    break
                ri, rj = root(i), root(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list[int]] = {}
    for i in range(len(runs)):
        groups.setdefault(root(i), []).append(i)
    pieces = []
    for members in groups.values():
        x_lo = min(runs[i][1] for i in members)
        x_hi = max(runs[i][2] for i in members)
        if x_hi - x_lo < min_extent:
            continue
        # Per bin of the run's direction: the middle of the rows covering it.
        bins: dict[int, list[int]] = {}
        for i in members:
            y, x1, x2 = runs[i]
            for b in range(x1 // bin_px, (x2 - 1) // bin_px + 1):
                lo, hi = max(x1, b * bin_px), min(x2, (b + 1) * bin_px)
                if hi - lo >= bin_px // 2:
                    bins.setdefault(b, []).append(y)
        points, weights = [], []
        for b, ys in bins.items():
            # Smeared by a row each side; a filled area or two lines are too thick.
            thickness = max(ys) - min(ys) + 1 - 2
            if thickness > max_thickness or len(ys) < 2:
                continue
            points.append(((b + 0.5) * bin_px, (max(ys) + min(ys)) / 2))
            weights.append(1.0)
        if len(points) >= 4 and max(p[0] for p in points) - min(p[0] for p in points) >= min_extent:
            points.sort()
            extent = points[-1][0] - points[0][0]
            degree = 3 if extent < 0.2 * width else 5 if extent < 0.5 * width else 7
            if _smooth(points, degree):
                pieces.append(Piece(points, weights))
    return pieces


def _smooth(
    points: list[tuple[float, float]], degree: int = 3, rms_px: float = 1.2, max_px: float = 3.5
) -> bool:
    """Whether the points follow one smooth curve (a polynomial of ``degree``): a
    line, however bent, and not two lines run together or the edge of a shadow."""
    xs = [p[0] for p in points]
    lo, hi = min(xs), max(xs)
    mid, half = (lo + hi) / 2, max(1e-9, (hi - lo) / 2)
    n = degree + 1
    ata = [[0.0] * n for _ in range(n)]
    atb = [0.0] * n
    for x, y in points:
        t = (x - mid) / half
        f = [t**k for k in range(n)]
        for i in range(n):
            atb[i] += f[i] * y
            for j in range(n):
                ata[i][j] += f[i] * f[j]
    c = _solve(ata, atb)
    if c is None:
        return False
    res = []
    for x, y in points:
        t = (x - mid) / half
        res.append(y - sum(c[k] * t**k for k in range(n)))
    rms = math.sqrt(sum(r * r for r in res) / len(res))
    return rms <= rms_px and max(abs(r) for r in res) <= max_px


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [row[:] + [v] for row, v in zip(a, b, strict=True)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[r][n] / m[r][r] for r in range(n)]


def _basis(t: float, n: int) -> tuple[int, list[float], list[float]]:
    """First control index, values and derivatives (per unit of t) of the four
    uniform cubic B-splines at ``t`` in [0, n] (clamped)."""
    t = min(max(t, 0.0), float(n))
    i = min(int(t), n - 1)
    u = t - i
    v = 1 - u
    vals = [
        v * v * v / 6,
        (3 * u**3 - 6 * u * u + 4) / 6,
        (-3 * u**3 + 3 * u * u + 3 * u + 1) / 6,
        u**3 / 6,
    ]
    ders = [-v * v / 2, (3 * u * u - 4 * u) / 2, (-3 * u * u + 2 * u + 1) / 2, u * u / 2]
    return i, vals, ders


@dataclass
class SplineWarp:
    """(u, v) = (x + E(x, y) - E(x, y0), y + D(x, y) - D(x0, y)): D and E are
    B-spline surfaces over the picture (``nx`` by ``ny`` cells); taking off their
    value on the middle column and row keeps the fit from squeezing everything
    together (along a line only the bending counts)."""

    width: float
    height: float
    nx: int
    ny: int
    d: list[float]  # (nx + 3) * (ny + 3) control values of D, row by row in y
    e: list[float]
    x0: float = 0.0  # the surfaces cover x0 .. x0 + width, y0 .. y0 + height
    y0: float = 0.0

    def _surface(self, c: list[float], x: float, y: float) -> tuple[float, float, float]:
        hx, hy = self.width / self.nx, self.height / self.ny
        i, bx, dbx = _basis((x - self.x0) / hx, self.nx)
        j, by, dby = _basis((y - self.y0) / hy, self.ny)
        stride = self.nx + 3
        val = dx = dy = 0.0
        for b in range(4):
            row = (j + b) * stride + i
            for a in range(4):
                cv = c[row + a]
                val += cv * bx[a] * by[b]
                dx += cv * dbx[a] * by[b]
                dy += cv * bx[a] * dby[b]
        return val, dx / hx, dy / hy

    def forward(self, x: float, y: float) -> tuple[float, float]:
        x0, y0 = self.x0 + self.width / 2, self.y0 + self.height / 2
        return (
            x + self._surface(self.e, x, y)[0] - self._surface(self.e, x, y0)[0],
            y + self._surface(self.d, x, y)[0] - self._surface(self.d, x0, y)[0],
        )

    def inverse(self, u: float, v: float, start=None) -> tuple[float, float]:
        x0, y0 = self.x0 + self.width / 2, self.y0 + self.height / 2
        x, y = start if start else (u, v)
        for _ in range(10):
            e, ex, ey = self._surface(self.e, x, y)
            e0, e0x, _ = self._surface(self.e, x, y0)
            d, dx, dy = self._surface(self.d, x, y)
            d0, _, d0y = self._surface(self.d, x0, y)
            fu = x + e - e0 - u
            fv = y + d - d0 - v
            if abs(fu) + abs(fv) < 1e-4:
                break
            a11, a12 = 1 + ex - e0x, ey
            a21, a22 = dx, 1 + dy - d0y
            det = a11 * a22 - a12 * a21
            if abs(det) < 1e-9:
                break
            x -= (a22 * fu - a12 * fv) / det
            y -= (-a21 * fu + a11 * fv) / det
        return x, y


def _fit_surface(
    pieces,
    across: bool,
    width: float,
    height: float,
    nx: int,
    ny: int,
    smoothing: float,
    ox: float = 0.0,
    oy: float = 0.0,
) -> list[float]:
    """Control values of D (or E for ``across``) that make the pieces straight; the
    surface covers ox .. ox + width, oy .. oy + height."""
    hx, hy = width / nx, height / ny
    stride = nx + 3
    n = stride * (ny + 3)
    x0, y0 = width / 2, height / 2
    ata = [[0.0] * n for _ in range(n)]
    atb = [0.0] * n
    samples = 0
    for pc in pieces:
        rows = []
        for (along, side), w in zip(pc.points, pc.weights, strict=True):
            x, y = (side, along) if across else (along, side)
            target = x if across else y
            x, y = x - ox, y - oy
            f: dict[int, float] = {}
            i, bx, _ = _basis(x / hx, nx)
            j, by, _ = _basis(y / hy, ny)
            for b in range(4):
                for a in range(4):
                    k = (j + b) * stride + i + a
                    f[k] = f.get(k, 0.0) + bx[a] * by[b]
            # minus the value on the middle column (row for E)
            if across:
                i0, bx0, _ = i, bx, None
                j0, by0, _ = _basis(y0 / hy, ny)
            else:
                i0, bx0, _ = _basis(x0 / hx, nx)
                j0, by0 = j, by
            for b in range(4):
                for a in range(4):
                    k = (j0 + b) * stride + i0 + a
                    f[k] = f.get(k, 0.0) - bx0[a] * by0[b]
            rows.append((f, target, w))
        wsum = sum(w for _, _, w in rows)
        mean_f: dict[int, float] = {}
        for f, _, w in rows:
            for k, val in f.items():
                mean_f[k] = mean_f.get(k, 0.0) + val * w / wsum
        mean_t = sum(t * w for _, t, w in rows) / wsum
        for f, t, w in rows:
            g = dict(mean_f)
            for k in g:
                g[k] = -g[k]
            for k, val in f.items():
                g[k] = g.get(k, 0.0) + val
            r = -(t - mean_t)
            items = [(k, val) for k, val in g.items() if abs(val) > 1e-12]
            for k, val in items:
                wv = w * val
                atb[k] += wv * r
                row = ata[k]
                for k2, val2 in items:
                    row[k2] += wv * val2
            samples += 1
    lam = smoothing * max(1, samples) / n
    for jy in range(ny + 3):
        for ix in range(stride):
            k = jy * stride + ix
            for dk in ((1, 0), (0, 1)):
                # second differences along x and along y
                ks = []
                for s in (-1, 0, 1):
                    xx, yy = ix + s * dk[0], jy + s * dk[1]
                    if 0 <= xx < stride and 0 <= yy < ny + 3:
                        ks.append(yy * stride + xx)
                if len(ks) == 3:
                    coeffs = list(zip(ks, (1.0, -2.0, 1.0), strict=True))
                    for ka, ca in coeffs:
                        for kb, cb in coeffs:
                            ata[ka][kb] += lam * ca * cb
            ata[k][k] += 1e-6 * lam + 1e-9
    sol = _solve(ata, atb)
    return sol if sol is not None else [0.0] * n


def fit_spline_warp(
    width: float,
    height: float,
    horizontal: list[Piece],
    vertical: list[Piece],
    cells: int = 8,
    smoothing: float = 0.05,
    x0: float = 0.0,
    y0: float = 0.0,
) -> SplineWarp:
    """Surfaces over x0 .. x0 + width, y0 .. y0 + height."""
    nx = cells if width >= height else max(3, round(cells * width / height))
    ny = cells if height > width else max(3, round(cells * height / width))
    d = _fit_surface(horizontal, False, width, height, nx, ny, smoothing, x0, y0)
    e = _fit_surface(vertical, True, width, height, nx, ny, smoothing, x0, y0)
    return SplineWarp(width, height, nx, ny, d, e, x0, y0)


def _eigh3(m):
    """Eigenvalues and eigenvectors (columns) of a symmetric 3x3 matrix (Jacobi)."""
    a = [row[:] for row in m]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(50):
        off = abs(a[0][1]) + abs(a[0][2]) + abs(a[1][2])
        if off < 1e-15:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            if abs(a[p][q]) < 1e-18:
                continue
            theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
            t = (1 if theta >= 0 else -1) / (abs(theta) + math.sqrt(theta * theta + 1))
            c = 1 / math.sqrt(t * t + 1)
            s = t * c
            for k in range(3):
                akp, akq = a[k][p], a[k][q]
                a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
            for k in range(3):
                apk, aqk = a[p][k], a[q][k]
                a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
            for k in range(3):
                vkp, vkq = v[k][p], v[k][q]
                v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return [a[i][i] for i in range(3)], v


def vanishing_point(pieces, across: bool, cx: float, cy: float, scale: float):
    """Where the pieces meet (homogeneous, around (cx, cy) in units of ``scale``):
    each piece as a straight line through its points, the point closest to all."""
    m = [[0.0] * 3 for _ in range(3)]
    for pc in pieces:
        pts = [((side, along) if across else (along, side)) for along, side in pc.points]
        xs = [(x - cx) / scale for x, _ in pts]
        ys = [(y - cy) / scale for _, y in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in ys)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
        # direction of the line: main axis of the points
        angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
        dx, dy = math.cos(angle), math.sin(angle)
        a, b = -dy, dx
        c = -(a * mx + b * my)
        w = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        line = (a, b, c)
        for i in range(3):
            for j in range(3):
                m[i][j] += w * line[i] * line[j]
    vals, vecs = _eigh3(m)
    k = min(range(3), key=lambda i: vals[i])
    return [vecs[0][k], vecs[1][k], vecs[2][k]]


@dataclass
class Homography:
    """Picture pixels to pixels in which both families of lines are parallel to the
    axes; the middle of the picture keeps its place and size."""

    cx: float
    cy: float
    scale: float
    m: list[list[float]]
    inv: list[list[float]]

    @staticmethod
    def _apply(m, x, y):
        d = m[2][0] * x + m[2][1] * y + m[2][2]
        return (m[0][0] * x + m[0][1] * y + m[0][2]) / d, (m[1][0] * x + m[1][1] * y + m[1][2]) / d

    def forward(self, x, y):
        X, Y = self._apply(self.m, (x - self.cx) / self.scale, (y - self.cy) / self.scale)
        return self.cx + X * self.scale, self.cy + Y * self.scale

    def inverse(self, u, v, start=None):
        X, Y = self._apply(self.inv, (u - self.cx) / self.scale, (v - self.cy) / self.scale)
        return self.cx + X * self.scale, self.cy + Y * self.scale


def _inv3(m):
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [
        [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
        [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
        [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
    ]


def rectifying_homography(width, height, horizontal, vertical, max_tilt: float = 0.6):
    cx, cy, scale = width / 2, height / 2, max(width, height) / 2
    ident = Homography(
        cx, cy, scale, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    )
    if len(horizontal) < 3 or len(vertical) < 3:
        return ident
    vh = vanishing_point(horizontal, False, cx, cy, scale)
    vv = vanishing_point(vertical, True, cx, cy, scale)
    # the vanishing line through both points
    line = [
        vh[1] * vv[2] - vh[2] * vv[1],
        vh[2] * vv[0] - vh[0] * vv[2],
        vh[0] * vv[1] - vh[1] * vv[0],
    ]
    if abs(line[2]) < 1e-12:
        return ident
    l1, l2 = line[0] / line[2], line[1] / line[2]
    if math.hypot(l1, l2) > max_tilt:  # implausibly strong: leave it to the bending
        return ident
    hp = [[1, 0, 0], [0, 1, 0], [l1, l2, 1]]

    def mul(m, p):
        return [sum(m[i][k] * p[k] for k in range(3)) for i in range(3)]

    dh = mul(hp, vh)
    dv = mul(hp, vv)
    dh, dv = dh[:2], dv[:2]
    if dh[0] < 0:
        dh = [-dh[0], -dh[1]]
    if dv[1] < 0:
        dv = [-dv[0], -dv[1]]
    nh, nv = math.hypot(*dh), math.hypot(*dv)
    dh, dv = [dh[0] / nh, dh[1] / nh], [dv[0] / nv, dv[1] / nv]
    det = dh[0] * dv[1] - dv[0] * dh[1]
    if abs(det) < 0.5:
        return ident
    a = [[dv[1] / det, -dv[0] / det], [-dh[1] / det, dh[0] / det]]
    full = [[a[0][0], a[0][1], 0], [a[1][0], a[1][1], 0], [0, 0, 1]]
    m = [[sum(full[i][k] * hp[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return Homography(cx, cy, scale, m, _inv3(m))


@dataclass
class Combined:
    """First the perspective, then the bending."""

    first: Homography
    second: SplineWarp

    def forward(self, x, y):
        return self.second.forward(*self.first.forward(x, y))

    def inverse(self, u, v, start=None):
        p = self.second.inverse(u, v, self.first.forward(*start) if start else None)
        return self.first.inverse(*p)


def mapped_pieces(pieces, across: bool, h: Homography) -> list[Piece]:
    out = []
    for pc in pieces:
        pts = []
        for along, side in pc.points:
            x, y = (side, along) if across else (along, side)
            u, v = h.forward(x, y)
            pts.append((v, u) if across else (u, v))
        out.append(Piece(pts, pc.weights))
    return out


def transposed(width: int, height: int, data: bytes) -> bytes:
    """The picture turned a quarter (rows become columns)."""
    return b"".join(data[x::width] for x in range(width))


def estimate(width: int, height: int, ink: bytes) -> Combined:
    """The map that straightens the picture (one byte per pixel, 1 for ink)."""
    side = max(width, height)
    min_run = max(12, side // 140)
    min_extent = side * 0.04
    thick = max(4, side // 450)
    hs = line_pieces(width, height, ink, min_run, min_extent, thick)
    # vertical lines as rows of the turned picture: points come as (y, x)
    vs = line_pieces(height, width, transposed(width, height, ink), min_run, min_extent, thick)
    persp = rectifying_homography(width, height, hs, vs)
    # the bending is fitted over the picture as the perspective step moved it
    corners = [persp.forward(x, y) for x, y in ((0, 0), (width, 0), (width, height), (0, height))]
    u0, u1 = min(c[0] for c in corners), max(c[0] for c in corners)
    v0, v1 = min(c[1] for c in corners), max(c[1] for c in corners)
    mu, mv = 0.03 * (u1 - u0), 0.03 * (v1 - v0)
    bend = fit_spline_warp(
        u1 - u0 + 2 * mu,
        v1 - v0 + 2 * mv,
        mapped_pieces(hs, False, persp),
        mapped_pieces(vs, True, persp),
        x0=u0 - mu,
        y0=v0 - mv,
    )
    return Combined(persp, bend)
