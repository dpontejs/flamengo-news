# syntax=docker/dockerfile:1

# Subscription page (flanews.web). The newsletter itself runs on GitHub Actions, not here.

# ---- build: uv only exists in this stage
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer is reused while only the code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime
FROM python:3.14-slim
# Links the GHCR package to this repo (README and source link on the package page).
LABEL org.opencontainers.image.source="https://github.com/dpontejs/flamengo-news"
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app:app /data
COPY --from=build /app/.venv /app/.venv
ARG GIT_SHA=dev
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SUBSCRIBERS_DB=/data/subscribers.db \
    GIT_SHA=${GIT_SHA}
WORKDIR /app
USER app
# SQLite lives here; mount a volume so subscribers survive new images.
VOLUME /data
EXPOSE 8000
# The deploy agent waits for "healthy" and rolls back otherwise; /health also opens the database.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# Only reachable through Caddy, so the forwarded client IP (used by the rate limit) is trusted.
CMD ["uvicorn", "flanews.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
