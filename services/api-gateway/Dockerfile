FROM python:3.11-slim

WORKDIR /app

# Install shared-lib first (path relative to build context root ".")
COPY packages/shared-lib /packages/shared-lib
RUN pip install --no-cache-dir /packages/shared-lib

# Install service dependencies (paths relative to build context root ".")
COPY services/api-gateway/pyproject.toml /app/
COPY services/api-gateway/src /app/src
RUN pip install --no-cache-dir .

# Non-root user for security
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
