# payment-service: FastAPI on uvicorn. Settings come from the environment (see .env.example).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir poetry==1.8.3
COPY pyproject.toml ./
RUN poetry install --only main --no-root --no-interaction

COPY app ./app
COPY migrations ./migrations

EXPOSE 8001
CMD ["sh", "-c", "uvicorn app.main:app --host \"${APP_HOST:-0.0.0.0}\" --port \"${APP_PORT:-8001}\""]
