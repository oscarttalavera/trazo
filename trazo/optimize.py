"""Optimización de recorridos para minimizar viajes y levantadas de pluma.

En impresoras con Z por husillo (Ender 3: ~5 mm/s) cada levantada cuesta
~0.5-1 s, así que unir trazos y ordenarlos bien es lo que más ahorra tiempo.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .geometry import dedupe, simplify


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
    """Vecino más cercano con KD-tree; los lazos cerrados pueden empezar en
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

    idx_map = np.arange(len(allpts))
    tree = cKDTree(allpts)
    alive_at_build = n
    result: list[np.ndarray] = []
    pos = np.asarray(start, float)
    done = 0
    while done < n:
        k = 8
        hit = None
        while hit is None:
            kk = min(k, len(idx_map))
            d, ii = tree.query(pos, k=kk)
            d, ii = np.atleast_1d(d), np.atleast_1d(ii)
            for dist, j in zip(d, ii):
                if j < len(idx_map) and not used[owner[idx_map[j]]]:
                    hit = (dist, idx_map[j])
                    break
            if hit is None:
                if kk >= len(idx_map):
                    break
                k *= 4
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
        # reconstruir el árbol cuando la mitad de los trazos ya se usó
        remaining = n - done
        if remaining and remaining < alive_at_build / 2:
            keep = ~used[owner]
            idx_map = np.nonzero(keep)[0]
            tree = cKDTree(allpts[idx_map])
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
