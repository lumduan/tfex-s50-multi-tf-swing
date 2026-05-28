# === Builder stage =========================================================
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# === Runtime stage =========================================================
FROM python:3.11-slim

# Public-mode default: container is read-only and safe to expose. Override
# with `docker build --build-arg TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE=false`
# in owner deployments.
ARG TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE=true

# curl is needed by HEALTHCHECK below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src/ ./src/
COPY --chown=app:app api/ ./api/

ENV TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE=${TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE} \
    PYTHONPATH=/app/src \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
