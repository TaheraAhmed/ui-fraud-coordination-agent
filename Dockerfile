# Multi-stage Dockerfile for the UI Fraud Coordination Agent.
#
# Stage 1 (builder): Install uv, sync dependencies into a venv.
# Stage 2 (runtime): Copy the venv and source into a slim image, run Streamlit.
#
# Designed for Cloud Run: reads $PORT from environment, binds 0.0.0.0.

# ---------- Stage 1: Builder ----------
FROM python:3.11-slim AS builder

# Install uv (lightweight, fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy only dependency files first for layer caching
COPY pyproject.toml uv.lock README.md ./

# Create venv and install dependencies (no editable install yet — we'll do that after copying source)
RUN uv sync --frozen --no-dev

COPY src/ ./src/
COPY data/samples/ ./data/samples/
COPY data/state_a_legacy.dat ./data/state_a_legacy.dat
COPY data/state_a_claims.json ./data/state_a_claims.json
COPY src/data/copybook_layout.txt ./src/data/copybook_layout.txt
COPY src/agent/prompts/ ./src/agent/prompts/
COPY .streamlit/ ./.streamlit/

# Install the project itself in editable mode so src/ imports resolve
RUN uv pip install --no-deps -e .

# ---------- Stage 2: Runtime ----------
FROM python:3.11-slim

# Install runtime essentials only (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the venv and source from builder
COPY --from=builder /app /app

# Make the venv's binaries the default
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8501

EXPOSE 8501

# Cloud Run injects $PORT — exec form + sh -c expands env vars and forwards signals to Streamlit
CMD ["sh", "-c", "exec streamlit run src/ui/app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
