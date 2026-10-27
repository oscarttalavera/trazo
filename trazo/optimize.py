"""Optimización de recorridos para minimizar viajes y levantadas de pluma.

En impresoras con Z por husillo (Ender 3: ~5 mm/s) cada levantada cuesta
~0.5-1 s, así que unir trazos y ordenarlos bien es lo que más ahorra tiempo.
"""
from __future__ import annotations

import math

import numpy as np

from .geometry import dedupe, simplify


class _Grid:
    """Rejilla espacial para buscar el punto vivo más cercano (sustituye a un KD-tree)."""

    def __init__(self, pts: np.ndarray, idx: np.ndarray):
        self.pts = pts
        sub = pts[idx]
        lo, hi = sub.min(axis=0), sub.max(axis=0)
        w, h = (float(v) for v in hi - lo)
        m = max(len(idx), 1)
        # ~3 puntos por celda; acotado para que la rejilla no tenga más de ~4·√m celdas por lado
        # (evita celdas diminutas cuando los puntos están casi alineados)
        self.cell = max(math.sqrt(w * h * 3.0 / m), max(w, h) / (4.0 * math.sqrt(m) + 1.0), 1e-3)
        keys = np.floor(sub / self.cell).astype(np.int64)
        self.lo, self.hi = keys.min(axis=0), keys.max(axis=0)
        self.buckets: dict[tuple[int, int], list[int]] = {}
        for k, (i, j) in zip(idx.tolist(), keys.tolist()):
            self.buckets.setdefault((i, j), []).append(k)

    def _ring(self, cx: int, cy: int, r: int):
        if r == 0:
            yield cx, cy
            return
        for i in range(cx - r, cx + r + 1):
            yield i, cy - r
            yield i, cy + r
        for j in range(cy - r + 1, cy + r):
            yield cx - r, j
            yield cx + r, j

    def nearest(self, pos: np.ndarray, alive) -> tuple[float, int] | None:
        cx, cy = (int(v) for v in np.floor(pos / self.cell))
        rmax = int(max(abs(cx - self.lo[0]), abs(cx - self.hi[0]), abs(cy - self.lo[1]), abs(cy - self.hi[1]))) + 1
        best, bestd = None, math.inf
        for r in range(rmax + 1):
            for key in self._ring(cx, cy, r):
                b = self.buckets.get(key)
                if not b:
                    continue
                live = [k for k in b if alive(k)]
                if len(live) != len(b):
                    if live:
                        self.buckets[key] = live
                    else:
                        del self.buckets[key]
                        continue
                d = np.hypot(*(self.pts[live] - pos).T)
                m = int(np.argmin(d))
                if d[m] < bestd:
                    best, bestd = live[m], float(d[m])
            # cualquier punto en el anillo r+1 está a más de r·celda
            if best is not None and bestd <= r * self.cell:
                break
        return None if best is None else (bestd, best)


def _is_closed(p: np.ndarray) -> bool:
    return len(p) > 3 and np.allclose(p[0], p[-1], atol=1e-6)


def prepare(paths: list[np.ndarray], simplify_tol: float = 0.02, min_len: float = 0.0) -> list[np.ndarray]:
    out = []
    for p in paths:
        p = dedupe(np.asarray(p, float))
        if len(p) == 0:
            continue
        if simplify_tol > 0 and len(p) > 2:
            p = simplify(p, simplify_tol)
        if min_len > 0 and len(p) > 1 and np.hypot(*np.diff(p, axis=0).T).sum() < min_len:
            continue
        out.append(p)
    return out


def order(paths: list[np.ndarray], start=(0.0, 0.0), merge_tol: float = 0.1,
          reverse: bool = True) -> list[np.ndarray]:
    """Vecino más cercano (rejilla espacial); los lazos cerrados pueden empezar en
    cualquier vértice y los abiertos invertirse. Une trazos a < merge_tol."""
    n = len(paths)
    if n == 0:
        return []
    pts, owner, vert = [], [], []
    for i, p in enumerate(paths):
        if _is_closed(p):
            ring = p[:-1]
            pts.append(ring)
            owner += [i] * len(ring)
            vert += list(range(len(ring)))
        else:
            ends = p[[0, -1]] if reverse else p[[0]]
            pts.append(ends)
            owner += [i] * len(ends)
            vert += [0, -1][: len(ends)]
    allpts = np.vstack(pts)
    owner = np.asarray(owner)
    vert = np.asarray(vert)
    used = np.zeros(n, bool)

    def alive(k: int) -> bool:
        return not used[owner[k]]

    grid = _Grid(allpts, np.arange(len(allpts)))
    alive_at_build = n
    result: list[np.ndarray] = []
    pos = np.asarray(start, float)
    done = 0
    while done < n:
        hit = grid.nearest(pos, alive)
        if hit is None:
            break
        dist, gi = hit
        i = owner[gi]
        p = paths[i]
        if _is_closed(p):
            ring = p[:-1]
            p = np.roll(ring, -int(vert[gi]), axis=0)
            p = np.vstack([p, p[:1]])
        elif vert[gi] == -1:
            p = p[::-1]
        used[i] = True
        done += 1
        if result and dist <= merge_tol:
            result[-1] = np.vstack([result[-1], p])
        else:
            result.append(p)
        pos = p[-1]
        # reconstruir la rejilla cuando quedan pocos trazos (celdas más grandes)
        remaining = n - done
        if remaining and remaining < alive_at_build / 4:
            grid = _Grid(allpts, np.nonzero(~used[owner])[0])
            alive_at_build = remaining
    return result


def join_close(paths: list[np.ndarray], merge_tol: float) -> list[np.ndarray]:
    """Sin reordenar: solo une trazos consecutivos cuyo extremo coincide."""
    out: list[np.ndarray] = []
    for p in paths:
        if out and np.hypot(*(out[-1][-1] - p[0])) <= merge_tol:
            out[-1] = np.vstack([out[-1], p])
        else:
            out.append(p)
    return out


def travel_stats(paths: list[np.ndarray], start=(0.0, 0.0)) -> tuple[float, float, int]:
    """(distancia dibujando, distancia viajando, levantadas)."""
    draw = sum(float(np.hypot(*np.diff(p, axis=0).T).sum()) for p in paths if len(p) > 1)
    travel = 0.0
    pos = np.asarray(start, float)
    for p in paths:
        travel += float(np.hypot(*(p[0] - pos)))
        pos = p[-1]
    return draw, travel, len(paths)
