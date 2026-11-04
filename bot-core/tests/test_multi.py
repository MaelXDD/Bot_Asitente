"""Un servicio, varios proyectos: configuracion por proyecto, aislamiento entre ellos y arranque/cierre encadenados."""
import contextlib
import os
import time

import jwt
import pytest

from bot_core.config import Settings
from bot_core.llm import LLMResponse
from bot_core.multi import check_settings, project_names
from bot_core.stores import InMemoryStore
from conftest import DemoProject, FakeLLM

SA, SB = "a" * 40, "b" * 40


@contextlib.contextmanager
def env(**vars):
    """Variables de entorno temporales (None = borrar)."""
    viejas = {k: os.environ.get(k) for k in vars}
    try:
        for k, v in vars.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in viejas.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


LIMPIO = dict(BOT_PROJECT=None, BOT_PROJECTS=None, BOT_DATABASE_URL=None, BOT_JWT_SECRET=None, BOT_JWT_ISSUER=None,
              BOT_JWT_DEFAULT_ROLE=None, BOT_CORS_ORIGINS=None, BOT_POOL_MAX=None, BOT_RATE_LIMIT_PER_MIN=None,
              MASTERTECH_JWT_SECRET=None, MASTERTECH_JWT_ISSUER=None, MASTERTECH_JWT_DEFAULT_ROLE=None,
              MASTERTECH_CORS_ORIGINS=None, MASTERTECH_DATABASE_URL=None, CITAS_JWT_SECRET=None,
              CITAS_JWT_ISSUER=None, CITAS_JWT_DEFAULT_ROLE=None, CITAS_CORS_ORIGINS=None, CITAS_DATABASE_URL=None)


def test_classic_single_project_still_reads_bot_variables():
    with env(**{**LIMPIO, "BOT_PROJECT": "mastertech", "BOT_JWT_SECRET": SA, "BOT_JWT_ISSUER": "",
                "BOT_JWT_DEFAULT_ROLE": "USER", "BOT_DATABASE_URL": "postgresql://x", "BOT_CORS_ORIGINS": "http://localhost:5173"}):
        s = Settings.from_env()
        assert (s.project, s.jwt_secret, s.jwt_issuer, s.jwt_default_role) == ("mastertech", SA, "", "USER")
        assert s.database_url == "postgresql://x" and s.cors_origins == ["http://localhost:5173"]


def test_each_project_has_its_own_auth_and_never_inherits_bot_auth():
    with env(**{**LIMPIO, "BOT_PROJECTS": "mastertech,citas", "BOT_DATABASE_URL": "postgresql://comun",
                "BOT_JWT_SECRET": "z" * 40, "BOT_CORS_ORIGINS": "https://otro.com",
                "MASTERTECH_JWT_SECRET": SA, "MASTERTECH_CORS_ORIGINS": "https://tienda.com, http://localhost:5173",
                "CITAS_JWT_SECRET": SB}):
        assert project_names() == ["mastertech", "citas"]
        m = Settings.from_env("mastertech", {"JWT_DEFAULT_ROLE": "USER"})
        c = Settings.from_env("citas", {"JWT_ISSUER": "citas-api", "JWT_DEFAULT_ROLE": "PACIENTE"})
        assert m.jwt_secret == SA and c.jwt_secret == SB                  # BOT_JWT_SECRET no se hereda
        assert (m.jwt_issuer, m.jwt_default_role) == ("", "USER")
        assert (c.jwt_issuer, c.jwt_default_role) == ("citas-api", "PACIENTE")
        assert m.cors_origins == ["https://tienda.com", "http://localhost:5173"] and c.cors_origins == []
        assert m.database_url == c.database_url == "postgresql://comun"   # la BD y los limites si se comparten


def test_project_variables_override_defaults_and_database_can_differ():
    with env(**{**LIMPIO, "BOT_DATABASE_URL": "postgresql://comun", "BOT_POOL_MAX": "3", "CITAS_DATABASE_URL": "postgresql://citas",
                "CITAS_JWT_ISSUER": "otro-emisor", "MASTERTECH_JWT_ISSUER": ""}):
        c = Settings.from_env("citas", {"JWT_ISSUER": "citas-api"})
        m = Settings.from_env("mastertech", {"JWT_ISSUER": "no-aplica"})
        assert (c.jwt_issuer, c.database_url, c.pool_max) == ("otro-emisor", "postgresql://citas", 3)
        assert m.jwt_issuer == "" and m.database_url == "postgresql://comun"   # "" explicito gana al valor por defecto


def test_missing_variables_fail_fast_with_a_clear_message():
    with env(**LIMPIO):
        s = Settings.from_env("mastertech")
        with pytest.raises(RuntimeError, match="MASTERTECH_JWT_SECRET"):
            check_settings(s)
        s.jwt_secret, s.database_url = SA, "postgresql://x"
        check_settings(s)


def test_migrate_runs_once_per_distinct_database():
    from bot_core.migrate import database_urls
    with env(**{**LIMPIO, "BOT_PROJECTS": "mastertech,citas", "BOT_DATABASE_URL": "postgresql://comun"}):
        assert database_urls() == ["postgresql://comun"]
    with env(**{**LIMPIO, "BOT_PROJECTS": "mastertech,citas", "BOT_DATABASE_URL": "postgresql://comun",
                "CITAS_DATABASE_URL": "postgresql://citas"}):
        assert database_urls() == ["postgresql://comun", "postgresql://citas"]
    with env(**{**LIMPIO, "BOT_DATABASE_URL": "postgresql://solo"}):
        assert database_urls() == ["postgresql://solo"]


# ------------------------------------------------------------------ API con dos proyectos (necesita fastapi)
def _app(cerrados):
    pytest.importorskip("fastapi")
    from bot_core.multi import Entry, create_multi_app

    class A(DemoProject): id = "a"
    class B(DemoProject): id = "b"

    def entry(cls, secret, tag):
        s = Settings(jwt_secret=secret, jwt_issuer="", jwt_default_role="USER", project=cls.id, rate_limit_per_min=50)

        async def cerrar(): cerrados.append(tag)
        return Entry(s, cls(), cerrar, InMemoryStore(), FakeLLM())
    return create_multi_app([entry(A, SA, "a"), entry(B, SB, "b")])


def _tok(secret, sub="7"):
    return {"Authorization": "Bearer " + jwt.encode({"sub": sub, "rol": "USER", "exp": int(time.time()) + 600}, secret, algorithm="HS256")}


def test_two_projects_are_isolated_by_path_and_secret():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    c = TestClient(_app([]))
    assert c.get("/health").json() == {"status": "ok", "projects": ["a", "b"]}
    assert c.get("/a/health").json()["project"] == "a" and c.get("/b/health").json()["project"] == "b"
    assert c.post("/a/chat", json={"message": "hola"}, headers=_tok(SA)).status_code == 200
    assert c.post("/b/chat", json={"message": "hola"}, headers=_tok(SB)).status_code == 200
    assert c.post("/a/chat", json={"message": "hola"}, headers=_tok(SB)).status_code == 401    # token de B no vale en A
    assert c.post("/b/chat", json={"message": "hola"}, headers=_tok(SA)).status_code == 401
    assert c.post("/chat", json={"message": "hola"}, headers=_tok(SA)).status_code == 404      # sin prefijo no existe
    assert c.get("/c/health").status_code == 404


def test_startup_and_shutdown_are_chained_to_every_project():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    cerrados = []
    with TestClient(_app(cerrados)) as c:
        assert c.get("/a/health").status_code == 200
        assert cerrados == []
    assert sorted(cerrados) == ["a", "b"]
