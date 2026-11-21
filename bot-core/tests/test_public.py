"""Acceso publico (visitantes sin sesion), cache de respuestas y configuracion del modelo lite."""
import pytest
from fastapi.testclient import TestClient

from bot_core.api import create_app
from bot_core.config import Settings
from bot_core.engine import BotEngine, RateLimited
from bot_core.llm import LLMError, LLMResponse, ToolCall
from bot_core.project import Project
from bot_core.stores import InMemoryStore
from bot_core.tools import ToolContext
from conftest import FakeLLM, SECRET, make_token


class ShopProject(Project):
    id = "tienda"
    fact_keys = {"marca": "marca favorita"}

    def __init__(self):
        super().__init__()
        self.calls = []

        @self.registry.tool("Busca productos", guest=True)
        async def buscar(ctx: ToolContext, texto: str) -> dict:
            self.calls.append(("buscar", ctx.role, ctx.store))
            return {"productos": [{"id": 1, "nombre": texto}], "_ui": {"type": "products", "ids": [1]}}

        @self.registry.tool("Compras del cliente")      # sin guest=True: solo con sesion
        async def mis_compras(ctx: ToolContext) -> dict:
            self.calls.append(("mis_compras", ctx.role))
            return {"pedidos": []}

        @self.registry.tool("Pide confirmacion", guest=True, confirm=True, summary=lambda a: "x")
        async def peligrosa(ctx: ToolContext) -> dict:
            return {}

    def system_prompt(self):
        return "Eres el bot de la tienda."


@pytest.fixture
def pub(settings):
    settings.public_access = True
    settings.public_rate_limit_per_min = 100
    settings.public_global_per_min = 1000

    def _make(script=None, **over):
        for k, v in over.items():
            setattr(settings, k, v)
        proj, llm = ShopProject(), FakeLLM(script)
        return BotEngine(settings, InMemoryStore(), llm, proj), proj, llm
    return _make


# ------------------------------------------------------------------ motor: visitante
async def test_visitante_usa_solo_herramientas_publicas_y_no_toca_la_bd(pub):
    eng, proj, llm = pub([LLMResponse(tool_calls=[ToolCall("buscar", {"texto": "laptop"})]),
                          LLMResponse(text="Te recomiendo esta")])
    r = await eng.chat_guest("busco una laptop", client_key="1.1.1.1")
    assert r.text == "Te recomiendo esta" and r.ui_actions == [{"type": "products", "ids": [1]}]
    assert r.conversation_id.startswith("g-")
    assert [t["name"] for t in llm.calls[0]["tools"]] == ["buscar"]       # ni mis_compras ni la de confirmacion
    assert "MODO VISITANTE" in llm.calls[0]["system"]
    assert proj.calls == [("buscar", "GUEST", None)]                      # sin store: nada de BD
    assert eng.store.users == {} and eng.store.msgs == {}


async def test_visitante_no_puede_forzar_herramientas_de_cliente(pub):
    eng, proj, llm = pub([LLMResponse(tool_calls=[ToolCall("mis_compras", {}), ToolCall("peligrosa", {})]),
                          LLMResponse(text="no puedo")])
    await eng.chat_guest("mis pedidos", client_key="ip")
    assert proj.calls == []
    resultados = [m["result"] for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert resultados == [{"error": "herramienta no disponible"}] * 2


async def test_visitante_con_acceso_publico_desactivado_se_rechaza(settings):
    eng = BotEngine(settings, InMemoryStore(), FakeLLM(), ShopProject())
    with pytest.raises(PermissionError):
        await eng.chat_guest("hola")


async def test_memoria_del_visitante_entre_mensajes_y_sesion_nueva(pub):
    eng, _, llm = pub([LLMResponse(text="r1"), LLMResponse(text="r2"), LLMResponse(text="r3")])
    r1 = await eng.chat_guest("hola uno", client_key="ip")
    r2 = await eng.chat_guest("hola dos", r1.conversation_id, "ip")
    assert r2.conversation_id == r1.conversation_id
    assert [m["text"] for m in llm.calls[1]["messages"]] == ["hola uno", "r1", "hola dos"]
    r3 = await eng.chat_guest("hola tres", r1.conversation_id, "ip", new=True)
    assert r3.conversation_id != r1.conversation_id
    assert [m["text"] for m in llm.calls[2]["messages"]] == ["hola tres"]


async def test_id_desconocido_de_visitante_abre_sesion_nueva(pub):
    eng, _, llm = pub([LLMResponse(text="ok")])
    r = await eng.chat_guest("hola", "g-inventado", "ip")
    assert r.conversation_id != "g-inventado"


async def test_historial_del_visitante_se_recorta(pub):
    eng, _, llm = pub(history_messages=4)
    cid = None
    for i in range(6):
        cid = (await eng.chat_guest(f"msg {i}", cid, "ip")).conversation_id
    assert len(eng.guest_sessions.get(cid)) <= 4
    assert eng.guest_sessions.get(cid)[0]["role"] == "user"


# ------------------------------------------------------------------ cache de respuestas
async def test_pregunta_repetida_se_sirve_de_cache_sin_llamar_al_modelo(pub):
    eng, proj, llm = pub([LLMResponse(tool_calls=[ToolCall("buscar", {"texto": "mouse"})]),
                          LLMResponse(text="Este mouse")])
    a = await eng.chat_guest("¿Tienen mouse?", client_key="ip1")
    n = len(llm.calls)
    b = await eng.chat_guest("tienen mouse", client_key="ip2")            # otro visitante, misma pregunta normalizada
    assert len(llm.calls) == n and len(proj.calls) == 1
    assert b.text == a.text and b.ui_actions == a.ui_actions
    assert b.conversation_id != a.conversation_id
    # y el visitante que recibio la respuesta cacheada conserva el contexto para seguir
    c = await eng.chat_guest("¿y más baratos?", b.conversation_id, "ip2")
    assert [m["text"] for m in llm.calls[-1]["messages"]][:2] == ["tienen mouse", "Este mouse"] and c.text


async def test_solo_el_primer_mensaje_se_cachea(pub):
    eng, _, llm = pub([LLMResponse(text="a"), LLMResponse(text="b"), LLMResponse(text="c")])
    r = await eng.chat_guest("primera", client_key="ip")
    await eng.chat_guest("garantia", r.conversation_id, "ip")             # 2.o mensaje: depende del contexto
    await eng.chat_guest("garantia", client_key="otro")                   # 1.er mensaje de otro: no estaba cacheado
    assert len(llm.calls) == 3


async def test_errores_y_tiempos_no_se_cachean(pub):
    class Cae(FakeLLM):
        async def generate(self, **kw):
            raise LLMError("saturado")
    settings_llm = Cae()
    eng, _, _ = pub()
    eng.llm = settings_llm
    r = await eng.chat_guest("hola", client_key="ip")
    assert "no puedo responder" in r.text
    assert len(eng.answer_cache) == 0
    eng.llm = FakeLLM([LLMResponse(text="ahora si")])
    assert (await eng.chat_guest("hola", client_key="ip2")).text == "ahora si"


async def test_cache_desactivada_con_ttl_cero(pub):
    eng, _, llm = pub([LLMResponse(text="x"), LLMResponse(text="y")], cache_ttl_s=0)
    await eng.chat_guest("hola", client_key="a")
    await eng.chat_guest("hola", client_key="b")
    assert len(llm.calls) == 2


# ------------------------------------------------------------------ limites
async def test_limite_por_ip_y_global(pub):
    eng, *_ = pub(public_rate_limit_per_min=2, public_global_per_min=3)
    await eng.chat_guest("uno", client_key="ipA")
    await eng.chat_guest("dos", client_key="ipA")
    with pytest.raises(RateLimited):
        await eng.chat_guest("tres", client_key="ipA")                   # tercera de la misma IP
    await eng.chat_guest("cuatro", client_key="ipB")                      # 3.a global
    with pytest.raises(RateLimited):
        await eng.chat_guest("cinco", client_key="ipC")                  # tope global agotado


async def test_mensaje_vacio_o_muy_largo(pub):
    eng, *_ = pub()
    with pytest.raises(ValueError):
        await eng.chat_guest("   ")
    with pytest.raises(ValueError):
        await eng.chat_guest("x" * (eng.s.max_user_chars + 1))


# ------------------------------------------------------------------ API HTTP
def _client(settings, script=None, public=True):
    settings.public_access = public
    return TestClient(create_app(settings, ShopProject(), InMemoryStore(), FakeLLM(script)))


def test_api_sin_token_con_acceso_publico(settings):
    c = _client(settings, [LLMResponse(text="hola visitante")])
    assert c.get("/health").json() == {"status": "ok", "project": "tienda", "public": True}
    r = c.post("/chat", json={"message": "hola"})
    assert r.status_code == 200 and r.json()["text"] == "hola visitante"
    assert c.get("/history").json() == {"conversation_id": None, "messages": []}


def test_api_token_invalido_sigue_dando_401_aunque_sea_publico(settings):
    c = _client(settings)
    assert c.post("/chat", json={"message": "hola"}, headers={"Authorization": "Bearer basura"}).status_code == 401
    assert c.post("/chat", json={"message": "hola"}, headers={"Authorization": f"Bearer {make_token(exp_in=-5)}"}).status_code == 401


def test_api_rutas_personales_exigen_sesion_aunque_sea_publico(settings):
    c = _client(settings)
    assert c.delete("/me/data").status_code == 401
    assert c.get("/me/facts").status_code == 401
    assert c.post("/actions/abc/confirm", json={"approve": True}).status_code == 401


def test_api_sin_acceso_publico_sigue_exigiendo_token(settings):
    c = _client(settings, public=False)
    assert c.post("/chat", json={"message": "hola"}).status_code == 401
    assert c.get("/history").status_code == 401


def test_api_usuario_con_sesion_sigue_usando_su_memoria_persistente(settings):
    c = _client(settings, [LLMResponse(text="hola Ana")])
    h = {"Authorization": f"Bearer {make_token(sub='7', nombre='Ana', iss='citas-api')}"}
    r = c.post("/chat", json={"message": "hola"}, headers=h)
    assert r.status_code == 200 and not r.json()["conversation_id"].startswith("g-")
    assert c.get("/history", headers=h).json()["messages"][0]["text"] == "hola"


def test_api_limite_por_ip_responde_429(settings):
    settings.public_rate_limit_per_min = 2
    c = _client(settings)
    codes = [c.post("/chat", json={"message": f"m{i}"}, headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}).status_code
             for i in range(3)]
    assert codes == [200, 200, 429]
    assert c.post("/chat", json={"message": "otra"}, headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 200


# ------------------------------------------------------------------ configuracion
def test_modelo_por_defecto_es_flash_lite(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert Settings.from_env(project="x").gemini_model == "gemini-flash-lite-latest"
    assert Settings().gemini_model == "gemini-flash-lite-latest"


def test_acceso_publico_por_proyecto(monkeypatch):
    for k in ("PUBLIC_ACCESS", "MASTERTECH_PUBLIC_ACCESS", "BOT_PUBLIC_ACCESS", "CITAS_PUBLIC_ACCESS"):
        monkeypatch.delenv(k, raising=False)
    from projects.mastertech.project import ENV_DEFAULTS
    assert Settings.from_env(project="mastertech", defaults=ENV_DEFAULTS).public_access is True
    assert Settings.from_env(project="citas").public_access is False                 # opt-in: citas sigue privado
    monkeypatch.setenv("MASTERTECH_PUBLIC_ACCESS", "false")
    assert Settings.from_env(project="mastertech", defaults=ENV_DEFAULTS).public_access is False
    monkeypatch.setenv("MASTERTECH_CACHE_TTL_S", "42")
    assert Settings.from_env(project="mastertech", defaults=ENV_DEFAULTS).cache_ttl_s == 42


def test_mastertech_solo_expone_el_catalogo_a_visitantes():
    from projects.mastertech.project import MastertechProject
    reg = MastertechProject(api=object(), specs=object()).registry
    nombres = {t.name for t in reg.for_guest()}
    assert nombres == {"buscar_productos", "detalle_producto", "comparar_productos", "listar_categorias"}
    assert not ({"mis_compras", "recomendaciones_para_mi", "recordar_dato", "olvidar_dato"} & nombres)
