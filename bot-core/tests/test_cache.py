"""Cache TTL en memoria y normalizacion de preguntas."""
from bot_core.cache import TTLCache, normalizar


def test_ttlcache_expira_y_respeta_el_maximo():
    t = [0.0]
    c = TTLCache(10, 2, clock=lambda: t[0])
    c.set("a", 1)
    t[0] = 5
    c.set("b", 2)
    c.get("a")                          # a se usa despues que b
    c.set("c", 3)                       # lleno: sale la menos usada (b)
    assert len(c) == 2 and c.get("b") is None and c.get("a") == 1
    t[0] = 100
    assert c.get("a") is None and c.get("c") is None


def test_ttlcache_touch_renueva_y_ttl_cero_desactiva():
    t = [0.0]
    c = TTLCache(10, 5, clock=lambda: t[0])
    c.set("s", [1])
    t[0] = 8
    assert c.get("s", touch=True) == [1]
    t[0] = 16
    assert c.get("s") == [1]            # se renovo en t=8
    off = TTLCache(0, 5)
    off.set("x", 1)
    assert off.get("x") is None


def test_normalizar_ignora_tildes_mayusculas_y_signos():
    assert normalizar("  ¿Cómo es la GARANTÍA?? ") == normalizar("como es la garantia")
