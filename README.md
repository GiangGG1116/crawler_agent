# 🕷️ Agent Crawler Data

> Intelligent web data crawling platform with AI-agent-driven custom development

## Overview

Agent Crawler Data combines **template-based automation** (Fast Path) with **AI-agent-driven custom development** (Slow Path) to intelligently crawl and extract structured data from any website.

## Architecture

```
Phase 0: Input Analysis    → Classify website type (STATIC/DYNAMIC/API/PAGINATED/AUTH)
Phase 1: Template Fast Path → Use pre-built templates for known patterns
Phase 2: Custom Agent Path  → LangGraph AI agent generates custom crawlers
Phase 3: Data Processing    → Clean, validate, deduplicate, score, and store
```

## Quick Start

### 1. Setup

```bash
# Clone and install
pip install -e ".[dev]"

# Copy environment config
cp .env.example .env
# Edit .env with your API keys

# Start infrastructure
docker-compose up -d
```

### 2. Run a Crawl

```bash
# Simple crawl
crawler crawl https://example.com/products -t products -f name -f price -f url

# With options
crawler crawl https://example.com/articles \
  -t articles \
  -f title -f content -f date \
  --max-pages 20 \
  --format json \
  --destination local_file

# From config file
crawler crawl-from-file configs/example_request.json

# List templates
crawler templates
```

### 3. Python API

```python
import asyncio
from src.orchestrator import CrawlOrchestrator
from src.models.request import CrawlRequest, TargetInfo, DataSpec, DataType

request = CrawlRequest(
    target=TargetInfo(url="https://example.com/products"),
    data_spec=DataSpec(
        data_type=DataType.PRODUCTS,
        required_fields=["name", "price", "url"],
    ),
)

orchestrator = CrawlOrchestrator()
result = asyncio.run(orchestrator.crawl(request))
print(f"Status: {result.status.value}")
print(f"Records: {len(result.clean_records)}")
print(f"Quality: {result.quality.overall_score:.1f}%")
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Static Scraping | requests + BeautifulSoup4 |
| Dynamic Scraping | Playwright |
| AI Agent | LangGraph + Claude/GPT-4 |
| Task Queue | Celery + Redis |
| Data Lake | MinIO (S3-compatible) |
| Output | JSON, CSV, Parquet, Delta |

## Templates

| ID | Web Type | Use Case |
|----|----------|----------|
| TPL-001 | STATIC | Blogs, wikis, news |
| TPL-002 | DYNAMIC | SPAs (React/Vue) |
| TPL-003 | API_BASED | REST API endpoints |
| TPL-004 | PAGINATED | E-commerce listings |
| TPL-005 | AUTHENTICATED | Login-required portals |

## Testing

```bash
pytest tests/ -v
```

## License

MIT
