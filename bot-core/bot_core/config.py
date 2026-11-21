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
    gemini_model: str = "gemini-flash-lite-latest"   # Flash-Lite: el de mayor cupo (peticiones/tokens) del plan gratuito
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
    max_output_tokens: int = 800      # tope de la respuesta del modelo (respuestas cortas; protege el cupo)

    # --- acceso publico (visitantes sin sesion) -------------------------------------------------
    public_access: bool = False       # True = /chat responde tambien sin token (modo invitado, sin datos personales)
    public_rate_limit_per_min: int = 8      # mensajes por minuto y por IP de visitante
    public_global_per_min: int = 40         # mensajes por minuto de TODOS los visitantes juntos (protege el cupo de Gemini)
    guest_session_ttl_min: int = 60         # la memoria de un visitante vive en RAM y caduca tras tanto tiempo sin uso
    guest_max_sessions: int = 2000
    cache_ttl_s: int = 300                  # respuestas repetidas (1.er mensaje de un visitante) se sirven de cache; 0 = sin cache
    cache_max_entries: int = 500

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

        def flag(name: str, default: bool) -> bool:
            return get(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "si", "sí", "on")

        def lista(valor: str) -> list[str]:
            return [o.strip() for o in valor.split(",") if o.strip()]

        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
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
            max_output_tokens=num("MAX_OUTPUT_TOKENS", 800),
            public_access=flag("PUBLIC_ACCESS", False),
            public_rate_limit_per_min=num("PUBLIC_RATE_LIMIT_PER_MIN", 8),
            public_global_per_min=num("PUBLIC_GLOBAL_PER_MIN", 40),
            guest_session_ttl_min=num("GUEST_SESSION_TTL_MIN", 60),
            guest_max_sessions=num("GUEST_MAX_SESSIONS", 2000),
            cache_ttl_s=num("CACHE_TTL_S", 300),
            cache_max_entries=num("CACHE_MAX_ENTRIES", 500),
            cors_origins=lista(get("CORS_ORIGINS", shared=False)),
        )
