# Multi-stage lightweight Python container for MagicPin Vera AI Bot
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final runtime image
FROM python:3.12-slim AS runner

WORKDIR /app

# Copy installed python dependencies from builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY . .

# Environment defaults
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    LLM_PROVIDER=openai \
    LLM_MODEL=gpt-4o-mini

EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/v1/healthz')" || exit 1

# Launch uvicorn server
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
