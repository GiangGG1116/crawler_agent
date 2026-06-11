FROM python:3.11-slim

WORKDIR /app

# System dependencies for Scrapy, lxml, Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Install shared-lib
COPY packages/shared-lib /packages/shared-lib
RUN pip install --no-cache-dir /packages/shared-lib

# Install service dependencies
COPY services/crawler-service/pyproject.toml /app/
COPY services/crawler-service/src /app/src
RUN pip install --no-cache-dir .

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/healthz')"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
