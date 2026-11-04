"""Un solo servicio para varios proyectos.

BOT_PROJECTS=mastertech,citas   ->  /mastertech/chat, /mastertech/history, ...  y  /citas/chat, ...
Cada proyecto es una sub-aplicacion con SU propio secreto JWT, CORS, backend y memoria (project_id distinto en la BD).
Solo comparten el proceso, la clave de Gemini y (si coinciden) la base de datos.
"""
from __future__ import annotations

import importlib
import os
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable

from .config import Settings
from .project import Project


@dataclass
class Entry:
    settings: Settings
    project: Project
    on_close: Callable[[], Any] | None = None
    store: Any = None          # solo tests
    llm: Any = None            # solo tests


def project_names(env: dict[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    return [n.strip() for n in env.get("BOT_PROJECTS", "").split(",") if n.strip()]


def check_settings(settings: Settings) -> None:
    """Falla al arrancar, con un mensaje claro, en vez de dar 401 a todo el mundo despues."""
    pre = settings.project.upper().replace("-", "_")
    faltan = []
    if len(settings.jwt_secret) < 32:
        faltan.append(f"{pre}_JWT_SECRET (mínimo 32 caracteres, igual al secreto con que firma tu backend)")
    if not settings.database_url:
        faltan.append(f"{pre}_DATABASE_URL o BOT_DATABASE_URL")
    if faltan:
        raise RuntimeError(f"Proyecto '{settings.project}': faltan variables de entorno: " + "; ".join(faltan))


def load_entry(name: str) -> Entry:
    mod = importlib.import_module(f"projects.{name}.project")
    settings = Settings.from_env(project=name, defaults=getattr(mod, "ENV_DEFAULTS", {}))
    check_settings(settings)
    project, on_close = mod.build(settings)
    return Entry(settings, project, on_close)


def create_multi_app(entries: list[Entry]):
    from fastapi import FastAPI
    from .api import create_app

    ids = [e.project.id for e in entries]
    if len(set(ids)) != len(ids):
        raise ValueError(f"proyectos repetidos: {ids}")
    subs: list = []

    @asynccontextmanager
    async def lifespan(app):
        # Starlette no ejecuta el arranque/cierre de las apps montadas: lo encadenamos aqui.
        async with AsyncExitStack() as stack:
            for sub in subs:
                await stack.enter_async_context(sub.router.lifespan_context(sub))
            yield

    app = FastAPI(title="bot-core", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", "projects": ids}

    for e in entries:
        sub = create_app(e.settings, e.project, e.store, e.llm, e.on_close)
        subs.append(sub)
        app.mount(f"/{e.project.id}", sub)
    return app


def build_app_from_env():
    names = project_names()
    if not names:
        raise RuntimeError("BOT_PROJECTS vacío")
    return create_multi_app([load_entry(n) for n in names])
