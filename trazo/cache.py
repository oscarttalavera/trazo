"""Cachés acotadas por tamaño para no repetir cálculos entre un ajuste y el siguiente."""
from __future__ import annotations

from collections import OrderedDict


class LRU:
    """Diccionario que descarta lo menos usado al pasar de `max_cost` (en puntos, por ejemplo)."""

    def __init__(self, max_cost: int):
        self.max_cost = max_cost
        self.cost = 0
        self._d: "OrderedDict[object, tuple[object, int]]" = OrderedDict()

    def get(self, key):
        hit = self._d.get(key)
        if hit is None:
            return None
        self._d.move_to_end(key)
        return hit[0]

    def put(self, key, value, cost: int = 1) -> None:
        old = self._d.pop(key, None)
        if old is not None:
            self.cost -= old[1]
        if cost > self.max_cost:  # no cabe ni solo
            return
        self._d[key] = (value, cost)
        self.cost += cost
        while self.cost > self.max_cost and self._d:
            _, (_, c) = self._d.popitem(last=False)
            self.cost -= c

    def clear(self) -> None:
        self._d.clear()
        self.cost = 0

    def __len__(self) -> int:
        return len(self._d)


def points(paths) -> int:
    """Costo de una lista de trazos: número de vértices (más uno por trazo)."""
    return sum(len(p) + 1 for p in paths)
