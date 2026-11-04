"""Arranque:  python run.py   (o)   uvicorn main:app --port 8090

* BOT_PROJECTS=mastertech,citas  -> un servicio, varios proyectos, cada uno bajo /<proyecto>/...
* BOT_PROJECT=mastertech         -> modo clasico de un solo proyecto, rutas en la raiz (/chat).
"""
import importlib
import os

from dotenv import load_dotenv

load_dotenv()

from bot_core.multi import build_app_from_env, project_names   # noqa: E402

if project_names():
    app = build_app_from_env()
else:
    from bot_core.api import create_app   # noqa: E402
    from bot_core.config import Settings  # noqa: E402

    settings = Settings.from_env()
    _mod = importlib.import_module(f"projects.{settings.project}.project")
    _project, _on_close = _mod.build(settings)
    app = create_app(settings, _project, on_close=_on_close)
