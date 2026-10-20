# Gantry: one container serves the broadcast page, its API and the live match feed.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
# Azure AI Speech needs OpenSSL and ALSA libraries even when it never touches a sound card
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libssl3 libasound2 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
ENV GANTRY_STATIC=/app/frontend/dist \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "gantry.server:app", "--host", "0.0.0.0", "--port", "8000"]
