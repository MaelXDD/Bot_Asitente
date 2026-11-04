from __future__ import annotations
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    gemini_fallback_models: list[str] = field(default_factory=list)   # se prueban si el principal falla/está saturado
    database_url: str = ""
    jwt_secret: str = ""
    jwt_issuer: str = ""
    jwt_role_claim: str = "rol"       # nombre del claim con el rol en el JWT de TU backend
    jwt_name_claim: str = "nombre"    # nombre del claim con el nombre visible
    jwt_default_role: str = "PACIENTE"
    project: str = "citas"
    rate_limit_per_min: int = 12
    history_messages: int = 16
    cors_origins: list[str] = field(default_factory=list)
    max_tool_rounds: int = 5
    max_user_chars: int = 1500
    chat_budget_s: float = 50.0       # tiempo maximo por mensaje (modelo + herramientas); el navegador espera mas
    resume_days: int = 30             # una conversacion se retoma si su ultimo mensaje es mas reciente que esto

    pool_max: int = 5                 # conexiones a Postgres por proyecto (Render/Supabase gratis: pocas)

    @classmethod
    def from_env(cls, project: str | None = None, defaults: dict[str, str] | None = None) -> "Settings":
        """Un solo proyecto (modo clasico): todo sale de BOT_*.

        Varios proyectos en un servicio (`project` = su id): cada uno lee `<ID>_X` (p. ej. MASTERTECH_JWT_SECRET).
        - Autenticacion y CORS (JWT_*, CORS_ORIGINS): SOLO `<ID>_X`, o el valor por defecto del proyecto (`defaults`).
          Nunca se heredan de BOT_*: cada proyecto tiene su propio backend y su propio secreto.
        - Lo demas (DATABASE_URL, limites): `<ID>_X`, y si falta, el valor comun BOT_X.
        """
        pre = project.upper().replace("-", "_") if project else None
        defaults = defaults or {}

        def get(name: str, default: str = "", shared: bool = True) -> str:
            if pre is None:
                return os.getenv(f"BOT_{name}", default)
            v = os.getenv(f"{pre}_{name}")
            if v is not None:
                return v
            if name in defaults:
                return defaults[name]
            return os.getenv(f"BOT_{name}", default) if shared else default

        def num(name: str, default: int) -> int:
            try:
                return int(get(name, str(default)))
            except ValueError:
                return default

        def lista(valor: str) -> list[str]:
            return [o.strip() for o in valor.split(",") if o.strip()]

        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
            gemini_fallback_models=lista(os.getenv("GEMINI_FALLBACK_MODELS", "")),
            database_url=get("DATABASE_URL"),
            jwt_secret=get("JWT_SECRET", shared=False),
            jwt_issuer=get("JWT_ISSUER", shared=False),
            jwt_role_claim=get("JWT_ROLE_CLAIM", "rol", shared=False),
            jwt_name_claim=get("JWT_NAME_CLAIM", "nombre", shared=False),
            jwt_default_role=get("JWT_DEFAULT_ROLE", "PACIENTE", shared=False),
            project=project or os.getenv("BOT_PROJECT", "citas"),
            rate_limit_per_min=num("RATE_LIMIT_PER_MIN", 12),
            history_messages=num("HISTORY_MESSAGES", 16),
            resume_days=num("RESUME_DAYS", 30),
            chat_budget_s=float(num("CHAT_BUDGET_S", 50)),
            pool_max=num("POOL_MAX", 5),
            cors_origins=lista(get("CORS_ORIGINS", shared=False)),
        )
