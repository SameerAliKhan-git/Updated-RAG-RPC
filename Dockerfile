# ═══════════════════════════════════════════════════════════
# Corpus — API Service Dockerfile (multi-stage)
# ═══════════════════════════════════════════════════════════

# Stage 1: Install dependencies with uv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS base

WORKDIR /app

COPY pyproject.toml uv.lock* ./

# Compile bytecode for faster startup; copy mode for cross-filesystem
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_HTTP_TIMEOUT=300

RUN uv sync --frozen --no-dev || uv sync --no-dev

# Copy application source
COPY src /app/src


# Stage 2: Slim runtime image
FROM python:3.12.8-slim AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ARG VERSION=0.1.0
ENV APP_VERSION=$VERSION

WORKDIR /app

# Copy the full app (with venv) from the build stage
COPY --from=base /app /app

# Put the virtual environment on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run with uvicorn — single worker for dev, scale via compose replicas
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
