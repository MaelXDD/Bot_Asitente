"""python -m bot_core.migrate   -> crea/actualiza el esquema 'bot' en la(s) BD de los proyectos activos.

Es idempotente: se puede ejecutar en cada arranque. Si varios proyectos usan la misma BD, se migra una sola vez."""
import asyncio
import os
import sys

from dotenv import load_dotenv

from .db import apply_schema
from .multi import project_names


def database_urls() -> list[str]:
    from .config import Settings
    names = project_names()
    urls = [Settings.from_env(project=n).database_url for n in names] if names else [os.environ.get("BOT_DATABASE_URL", "")]
    vistas: list[str] = []
    for u in urls:
        if u and u not in vistas:
            vistas.append(u)
    return vistas


async def main() -> None:
    urls = database_urls()
    if not urls:
        sys.exit("Falta BOT_DATABASE_URL (o <PROYECTO>_DATABASE_URL).")
    for u in urls:
        await apply_schema(u)


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
    print("Esquema 'bot' listo.")
