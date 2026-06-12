FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# System dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    bubblewrap \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Browser installation is cached independently from frequently changing app code.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir "playwright>=1.40.0" \
    && playwright install chromium --with-deps \
    && chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"

# Install shared-lib
COPY packages/shared-lib /packages/shared-lib
RUN pip install --no-cache-dir /packages/shared-lib

# Install service dependencies
COPY services/agent-service/pyproject.toml /app/
COPY services/agent-service/src /app/src
RUN pip install --no-cache-dir .

# Bubblewrap needs a narrowly-scoped privileged launcher for nested namespaces.
COPY services/agent-service/sandbox_launcher.c /tmp/sandbox_launcher.c
RUN gcc -O2 -Wall -Wextra -Werror /tmp/sandbox_launcher.c -o /usr/local/bin/agent-sandbox-launcher \
    && chown root:root /usr/local/bin/agent-sandbox-launcher \
    && chmod 4755 /usr/local/bin/agent-sandbox-launcher \
    && rm /tmp/sandbox_launcher.c

# Create dirs for generated code and chroma
ENV SERVICE_ROOT=/app
RUN mkdir -p /app/generated_crawlers /app/chroma_data

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app/generated_crawlers /app/chroma_data
USER appuser

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/healthz')"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
