FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8090
# Render/Railway inyectan PORT. Al arrancar se aplica el esquema "bot" (idempotente) y luego se levanta el servicio.
CMD ["sh", "-c", "python -m bot_core.migrate && uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
