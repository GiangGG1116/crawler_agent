# ==========================================================================
# Agent Crawler — Development Commands
# ==========================================================================
# Usage:
#   make help        — Show all available commands
#   make dev         — Start all services in development mode
#   make test        — Run all unit tests
#   make build       — Build all Docker images
#   make lint        — Run linter on all services
# ==========================================================================

.PHONY: help dev down build test lint clean logs status

PYTHON ?= python3

# Default target
help: ## Show this help
	@echo "🕷️  Agent Crawler — Available Commands"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Docker Compose ──────────────────────────────────────────────────────────

dev: ## Start all services (development mode)
	docker compose up -d
	@echo "\n✅ Services started. API Gateway: http://localhost:8000/docs"

down: ## Stop all services
	docker compose down

build: ## Build all Docker images (no cache)
	docker compose build --no-cache

build-fast: ## Build all Docker images (with cache)
	docker compose build

logs: ## Tail logs from all services
	docker compose logs -f --tail=50

logs-%: ## Tail logs from a specific service (e.g., make logs-api-gateway)
	docker compose logs -f --tail=100 $*

status: ## Show service status
	docker compose ps

restart-%: ## Restart a specific service (e.g., make restart-api-gateway)
	docker compose restart $*

# ── Testing ─────────────────────────────────────────────────────────────────

test: test-gateway test-crawler test-agent test-processor ## Run all unit tests

test-gateway: ## Run api-gateway tests
	@echo "🧪 Testing api-gateway..."
	cd services/api-gateway && $(PYTHON) -m pytest tests/ -v --tb=short

test-crawler: ## Run crawler-service tests
	@echo "🧪 Testing crawler-service..."
	cd services/crawler-service && $(PYTHON) -m pytest tests/ -v --tb=short

test-agent: ## Run agent-service tests
	@echo "🧪 Testing agent-service..."
	cd services/agent-service && $(PYTHON) -m pytest tests/ -v --tb=short

test-processor: ## Run data-processor tests
	@echo "🧪 Testing data-processor..."
	cd services/data-processor && $(PYTHON) -m pytest tests/ -v --tb=short

# ── Code Quality ────────────────────────────────────────────────────────────

lint: ## Run ruff linter on all Python code
	ruff check services/ packages/ --config pyproject.toml

lint-fix: ## Auto-fix linting issues
	ruff check services/ packages/ --fix --config pyproject.toml

format: ## Format all Python code
	ruff format services/ packages/

syntax: ## Verify all Python files parse correctly
	$(PYTHON) -m compileall -q services packages

# ── Infrastructure ──────────────────────────────────────────────────────────

redis-cli: ## Open Redis CLI
	docker compose exec redis sh -lc 'redis-cli -a "$$REDIS_PASSWORD"'

minio-ui: ## Open MinIO console URL
	@echo "MinIO Console: http://localhost:9001 (credentials are read from .env)"

langfuse-ui: ## Open Langfuse URL
	@echo "Langfuse: http://localhost:3000"

# ── Cleanup ─────────────────────────────────────────────────────────────────

clean: ## Remove __pycache__, .pytest_cache, etc.
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cleaned"

clean-all: clean down ## Clean + stop all services + remove volumes
	docker compose down -v
	@echo "✅ All cleaned (volumes removed)"
