# bot-core — chatbot IA reutilizable

## Un servicio para varios proyectos (y Render)

Con `BOT_PROJECTS=mastertech,citas` un solo proceso atiende a los dos proyectos, cada uno bajo su prefijo:

| Proyecto | Base de la URL que usa su frontend |
|---|---|
| Master Tech | `https://TU-SERVICIO.onrender.com/mastertech` → `/chat`, `/history`, `/me/data` |
| Citas | `https://TU-SERVICIO.onrender.com/citas` → `/chat`, `/history`, ... |

Cada proyecto tiene **su propio** secreto JWT, CORS, backend y memoria; solo comparten el proceso, la clave de Gemini y la BD
(el bot separa a los clientes por `project_id`, así que un cliente de Master Tech nunca ve nada de Citas).
Variables por proyecto: `<PROYECTO>_JWT_SECRET`, `_JWT_ISSUER`, `_JWT_DEFAULT_ROLE`, `_CORS_ORIGINS`, `_API_URL` y, si hace falta, `_DATABASE_URL`.
Si falta un secreto, el servicio **no arranca** y dice cuál variable falta. `GET /health` lista los proyectos activos.
Para añadir un tercero: carpeta `projects/<nombre>/` (ver `_template`), `ENV_DEFAULTS` en su `project.py` y añadirlo a `BOT_PROJECTS`.

**Importante:** en este modo ya no existe `/chat` en la raíz. El frontend de Master Tech debe usar `VITE_BOT_URL=https://TU-SERVICIO.onrender.com/mastertech`.

### Desplegar en Render
1. Sube el repo a GitHub. En Render: New → Blueprint (usa `render.yaml`) o New → Web Service con *Runtime: Docker* y *Root Directory:* `bot-core`.
2. Health check path: `/health`. Región cercana a tu BD.
3. Variables de entorno (Environment): las del `.env.example`, **sin** `localhost`:
   `GEMINI_API_KEY`, `BOT_DATABASE_URL`, `BOT_PROJECTS`, `BOT_POOL_MAX=3`, y por proyecto `*_JWT_SECRET`, `*_API_URL` (URL pública de su backend) y `*_CORS_ORIGINS` (URL pública de su frontend).
4. Al arrancar, el contenedor aplica el esquema `bot` solo (idempotente); no hace falta ejecutar `migrate` a mano.
5. Cuando el despliegue termine, `https://TU-SERVICIO.onrender.com/health` debe responder `{"status":"ok","projects":["mastertech","citas"]}`.
6. Cada frontend apunta a su prefijo; añade la URL de cada frontend a su `*_CORS_ORIGINS` (sin barra final).

Plan gratuito: el servicio se duerme tras ~15 min sin uso y tarda ~30-60 s en despertar; la primera pregunta tras ese rato puede demorar
(los backends gratuitos de Spring también duermen). Para evitarlo, usa un plan de pago o un ping periódico a `/health`.

---

## Proyecto `mastertech` (tienda Master Tech)

Asistente con Gemini que conoce el catálogo en vivo, el historial de compras de cada cliente y lo que el cliente
le ha contado (uso, presupuesto, marca favorita…). Todo vive en `projects/mastertech/`:

| Archivo | Qué hace |
|---|---|
| `prompt.md` | Personalidad, políticas de la tienda (envío, garantía, devoluciones) y límites. Edítalo sin tocar código. |
| `tools.py` | `buscar_productos`, `detalle_producto`, `comparar_productos`, `listar_categorias`, `mis_compras`, `recomendaciones_para_mi` (+ `recordar_dato` / `olvidar_dato` del motor). Solo lectura. |
| `project.py` | Preferencias que recuerda (`fact_keys`) y el **contexto personal** que se inyecta en cada mensaje. |
| `backend.py` | Cliente de la API Spring (catálogo público con caché corto; `/me` y `/me/pedidos` con el JWT del cliente). |
| `specs.py` | Lee la tabla `especificaciones` (opcional: si no existe, el bot sigue sin ella). |
| `catalog.py` | Búsqueda (sin tildes, plurales, sinónimos), fichas y puntuación de recomendaciones. Sin red. |

**Memoria por usuario** (esquema `bot` de la misma BD, no toca `public`):
`bot.users` (un registro por cliente, clave = correo del JWT) · `bot.conversations` + `bot.messages` (historial completo,
con las tarjetas de producto para repintarlo) · `bot.user_facts` (preferencias duraderas) · `bot.tool_audit` (qué consultó el bot).
Cada mensaje: el modelo ve los últimos `BOT_HISTORY_MESSAGES` + un resumen de lo anterior + las preferencias + el historial de compras.
Al volver, `GET /history` devuelve la última conversación (si tiene menos de `BOT_RESUME_DAYS` días) y `POST /chat` la retoma sola;
`{"new": true}` empieza una nueva (las preferencias se conservan). `DELETE /me/data` borra todo lo que el bot sabe del cliente.

**Qué NO recibe el modelo:** DNI, teléfono, dirección, correo ni contraseña. Solo nombre, fecha de alta y compras.

### Poner en marcha con Spring
1. En Spring y en el bot usa el **mismo** secreto: `JWT_SECRET` (Spring) = `BOT_JWT_SECRET` (bot).
2. `cp .env.example .env` y rellena `GEMINI_API_KEY`, `BOT_DATABASE_URL` (la BD de Mastertech), `BOT_JWT_SECRET`.
3. `python -m bot_core.migrate` (crea/actualiza el esquema `bot`; es idempotente, también para añadir la columna `ui`).
4. `uvicorn main:app --port 8090` → `http://localhost:8090/health` debe responder `{"status":"ok","project":"mastertech"}`.
5. Frontend: `VITE_BOT_URL=http://localhost:8090`. En producción añade la URL del frontend a `BOT_CORS_ORIGINS`.
Spring no necesita cambios de código.

---

Servicio FastAPI + Gemini. El **núcleo** (`bot_core/`) no sabe nada de la tienda: aporta JWT, memoria de
preferencias, auditoría, confirmación de acciones, límite de uso y la API. Cada proyecto aporta solo
una carpeta en `projects/<nombre>/` (`mastertech` es el activo; `citas` queda como ejemplo).

## Arrancar (Master Tech)
```bat
cd bot-core
python -m venv .venv
.venv\Scripts\activate                 :: Linux/Mac: source .venv/bin/activate
python -m pip install -r requirements.txt
copy .env.example .env                  :: rellena GEMINI_API_KEY, BOT_DATABASE_URL, BOT_JWT_SECRET
python -m bot_core.migrate              :: crea el esquema "bot" (una vez)
python run.py                           :: puerto 8090 (en Windows usa run.py, no uvicorn directo)
```
Spring (puerto 8089) debe usar el **mismo** secreto: `JWT_SECRET` = `BOT_JWT_SECRET` (≥ 32 caracteres).
Comprueba: `http://localhost:8090/health` → `{"status":"ok","project":"mastertech"}`.

Flujo: login Spring (`/api/auth/login`) → devuelve `token` → el frontend lo guarda y lo envía a `VITE_BOT_URL`
(`/chat`, `/history`) → el bot valida el JWT y lee de Spring (`/api/v1/productos`, `/api/v1/me`, `/api/v1/me/pedidos`)
reenviando ese mismo JWT.

## Reutilizarlo en otro proyecto
1. Copia `bot-core/` entero (o publícalo como repo propio).
2. `cp -r projects/_template projects/mi_proyecto` y edita `project.py`:
   prompt, `fact_keys`, `load_context()` y tus tools con `@self.registry.tool(...)`
   (`confirm=True` para acciones que modifican datos).
3. `.env`: `BOT_PROJECT=mi_proyecto` y, si tu JWT usa otros nombres, `BOT_JWT_ROLE_CLAIM` / `BOT_JWT_NAME_CLAIM`.
4. Tu backend debe emitir un JWT HMAC (HS256/384/512) con `sub`, `exp` (y `iss` si configuras `BOT_JWT_ISSUER`).
5. En el front llama a `/chat` y `/history` del servicio enviando el JWT en `Authorization: Bearer`.
La BD es la misma del proyecto, pero el bot usa su propio schema `bot` (no se mezcla con `public`). Varios proyectos pueden compartirlo: se separan por `project_id`.

## Tests
`pip install -r requirements.txt && pytest`
