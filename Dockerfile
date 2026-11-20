FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 1) dépendances seules (couche en cache tant que uv.lock ne change pas)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) le code, puis installation du projet
COPY src/ ./src/
RUN uv sync --frozen --no-dev

CMD ["python", "-m", "plumes_crm.test_gmail"]
