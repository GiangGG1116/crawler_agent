# Agent Crawler — Intelligent Web Data Crawling Platform

A microservices platform that automatically generates, tests, and deploys web crawlers using AI agents. Submit a URL and data spec — the system decides the best scraping strategy, generates custom code if templates fail, and delivers quality-scored clean data.

## Architecture

```mermaid
flowchart TD
    Client["Client / CLI"] --> Gateway["API Gateway"]
    Gateway --> Queue["Redis Queue"]
    Queue --> Worker["Crawl Worker"]
    Worker --> Crawler["Crawler Service<br/>Analyze URL + try template"]

    Crawler --> Decision{"Template OK?"}
    Decision -- "Yes" --> Processor["Data Processor<br/>Clean + score"]
    Decision -- "No" --> Agent["Agent Service<br/>Generate custom crawler + Bubblewrap Sandbox"]
    Agent --> Processor

    Processor --> Storage["MinIO / Data Lake"]
    Processor --> Result["Redis Job Result"]
    Result --> Gateway
    Gateway --> Client

    %% Observability
    subgraph Observability
        Langfuse["Langfuse Server"] --> DB["PostgreSQL"]
    end
    Gateway -.-> Langfuse
    Crawler -.-> Langfuse
    Agent -.-> Langfuse
    Processor -.-> Langfuse
```

### Pipeline Phases

| Phase       | Service   | Description                                                     |
| ----------- | --------- | --------------------------------------------------------------- |
| **0** | Crawler   | Analyze URL → classify web type (STATIC/DYNAMIC/API/PAGINATED) |
| **1** | Crawler   | Try template fast path → validate output via gate checks       |
| **2** | Agent     | If template fails → LangGraph AI generates custom crawler code |
| **3** | Processor | Clean → deduplicate → quality score → persist to data lake   |

### Multi-Agent Workflow (LangGraph)

When the template fast path fails, the **Agent Service** triggers a resilient Multi-Agent workflow built using **LangGraph** and integrated with a 6-layer memory system (checkpointer, domain memory, conversation buffer, error patterns, vector knowledge base, and human feedback):

```mermaid
flowchart TD
    %% Define the main nodes
    Start["Start crawl request"] --> PreLoad["MemoryManager: Load context from memory"]
  
    subgraph MemoryLayers ["Integrated Memory Layers"]
        direction LR
        DM["Domain Memory: Store past crawling experience"]
        EM["Error Patterns: Common errors to avoid"]
        KB["Vector DB ChromaDB: Similar website structures"]
        HF["Human Feedback: Expert feedback"]
    end
  
    PreLoad -.-> DM
    PreLoad -.-> EM
    PreLoad -.-> KB
    PreLoad -.-> HF
  
    DM -.-> InitState["Initialize AgentGraphState"]
    EM -.-> InitState
    KB -.-> InitState
    HF -.-> InitState
  
    InitState --> NodeAnalyze["Node: analyze_site - Analyze DOM structure and generate scraping suggestions"]
  
    NodeAnalyze --> NodeGen["Node: generate_crawler_code - LLM automatically generates Python crawler code"]
  
    NodeGen --> NodeTest["Node: run_crawler_tests - Run crawler tests in isolated Bubblewrap sandbox"]
  
    NodeTest --> NodeDecide["Node: decide_next - Evaluate test results"]
  
    %% Branch decisions
    NodeDecide -- "Success (PASS)" --> PersistSuccess["Save results and knowledge to memory"]
    PersistSuccess --> EndSuccess["END: Complete and move to Phase 3"]
  
    NodeDecide -- "Failure and attempt < 3" --> NodeAnalyze
  
    NodeDecide -- "Failure and attempt >= 3" --> NodeAlert["Node: alert_human - Trigger manual intervention"]
    NodeAlert --> PersistFail["Save error type to Error Memory"]
    PersistFail --> EndHuman["END: Wait for human handling"]

    %% Checkpointer stores state continuously
    InitState -.-> RedisCheck["Redis Checkpointer"]
    NodeAnalyze -.-> RedisCheck
    NodeGen -.-> RedisCheck
    NodeTest -.-> RedisCheck
    NodeDecide -.-> RedisCheck
    NodeAlert -.-> RedisCheck
```

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — set strong infrastructure secrets and one LLM API key

# 2. Start all services
make dev
# or: docker compose up -d

# 3. Open API docs
open http://localhost:8000/docs

# 4. Submit a crawl job
curl -X POST http://localhost:8000/api/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "target": {"url": "https://example.com"},
    "data_spec": {"data_type": "products", "required_fields": ["name", "price"]}
  }'

# 5. Check status
curl http://localhost:8000/api/v1/crawl/{job_id}/status

# 6. Get result
curl http://localhost:8000/api/v1/crawl/{job_id}/result
```

### CLI

```bash
# Install CLI
pip install -e services/api-gateway

# Submit job with live progress
crawler crawl https://example.com -t products -f name -f price

# Check job status
crawler status <job_id>

# Get result
crawler result <job_id>

# List templates
crawler templates
```

## Development

```bash
# Run tests
make test                  # All services
make test-gateway          # API Gateway only
make test-crawler          # Crawler Service only
make test-processor        # Data Processor only

# Code quality
make lint                  # Ruff linter
make lint-fix              # Auto-fix issues
make format                # Format code

# Infrastructure
make redis-cli             # Redis CLI
make logs                  # Tail all logs
make logs-api-gateway      # Tail specific service
make status                # Show service status
make clean                 # Remove __pycache__
```

## API Reference

### `POST /api/v1/crawl` — Submit Crawl Job

Returns `202 Accepted` immediately. A separate durable worker claims the job
from Redis and recovers unacknowledged jobs after a worker restart.

**Request:**

```json
{
  "target": {"url": "https://example.com"},
  "data_spec": {
    "data_type": "products",
    "required_fields": ["name", "price", "url"]
  },
  "scope": {"max_pages": 50, "max_records": 1000},
  "output": {"format": "json", "destination": "data_lake"}
}
```

**Response (202):**

```json
{
  "job_id": "abc-123-def",
  "status": "queued",
  "status_url": "/api/v1/crawl/abc-123-def/status",
  "result_url": "/api/v1/crawl/abc-123-def/result"
}
```

### `GET /api/v1/crawl/{id}/status` — Job Progress

```json
{
  "job_id": "abc-123-def",
  "status": "running",
  "phase": "phase2_agent",
  "progress": 0.45,
  "created_at": "2026-06-05T02:30:00Z",
  "updated_at": "2026-06-05T02:31:30Z"
}
```

### `GET /api/v1/crawl/{id}/result` — Full Result

```json
{
  "status": "completed",
  "result": {
    "request_id": "abc-123-def",
    "status": "success",
    "phase_used": "template",
    "raw_records": [...],
    "clean_records": [...],
    "quality": {"overall_score": 87.5, "grade": "good"},
    "output_path": "s3://crawler-clean/data/20260605_abc.json"
  }
}
```
