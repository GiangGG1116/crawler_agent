FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright & Scrapy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/
COPY configs/ configs/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Install Playwright browsers
RUN playwright install --with-deps chromium

# Create runtime directories
RUN mkdir -p generated_crawlers logs

ENTRYPOINT ["python", "-m"]
CMD ["src.cli"]
