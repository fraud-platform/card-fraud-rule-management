# =============================================================================
# Card Fraud Rule Management - Production Dockerfile
# Multi-stage build: builder (deps) → runtime (slim)
# =============================================================================

# Stage 1: Builder - install dependencies only
# =============================================================================
FROM python:3.14-slim AS builder

# Install build dependencies for compiling C extensions (psycopg, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager (pinned version for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (layer caching: deps change less than source)
COPY pyproject.toml uv.lock README.md ./

# Install production dependencies only
RUN uv sync --frozen --no-dev

# =============================================================================
# Stage 2: Runtime - minimal image with app + venv only
# =============================================================================
FROM python:3.14-slim AS runtime

# Install curl for health checks + create non-root user (single layer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy only the virtual environment from builder (uv binary NOT needed at runtime)
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appuser app ./app

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
