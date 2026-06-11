FROM python:3.11-slim

WORKDIR /app

# Install shared-lib
COPY packages/shared-lib /packages/shared-lib
RUN pip install --no-cache-dir /packages/shared-lib

# Install service dependencies
COPY services/data-processor/pyproject.toml /app/
COPY services/data-processor/src /app/src
RUN pip install --no-cache-dir .

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/healthz')"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "2"]
