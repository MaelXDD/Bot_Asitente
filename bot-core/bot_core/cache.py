"""Cache en memoria con caducidad (TTL) y tamano maximo. Sin dependencias.

Lo usa el modo invitado para dos cosas:
  * `TTLCache` de respuestas: una pregunta repetida ("¿cómo es la garantía?") no vuelve a gastar cupo de Gemini.
  * `TTLCache` de sesiones: la memoria de cada visitante vive solo en RAM, caduca sola y nunca toca la base de datos.
Un proceso = una cache. Si Render reinicia el servicio, se vacia (por eso es "memoria", no historial).
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections import OrderedDict
from typing import Any, Callable


class TTLCache:
    def __init__(self, ttl_s: float, max_entries: int, clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.max_entries, self._clock = ttl_s, max_entries, clock
        self._d: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._d)

    def get(self, key: str, *, touch: bool = False) -> Any | None:
        """Devuelve el valor o None si no existe o caduco. `touch=True` renueva la caducidad (sesiones)."""
        item = self._d.get(key)
        if item is None:
            return None
        stamp, value = item
        if self._clock() - stamp > self.ttl_s:
            self._d.pop(key, None)
            return None
        if touch:
            self._d[key] = (self._clock(), value)
        self._d.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        if self.ttl_s <= 0 or self.max_entries <= 0:
            return
        self._d[key] = (self._clock(), value)
        self._d.move_to_end(key)
        if len(self._d) > self.max_entries:
            self._purge()

    def delete(self, key: str) -> None:
        self._d.pop(key, None)

    def _purge(self) -> None:
        now = self._clock()
        for k in [k for k, (stamp, _) in self._d.items() if now - stamp > self.ttl_s]:
            del self._d[k]
        while len(self._d) > self.max_entries:      # sigue lleno: sale la mas antigua
            self._d.popitem(last=False)


def normalizar(texto: str) -> str:
    """Clave estable para comparar preguntas: minusculas, sin tildes ni signos, espacios colapsados."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()
