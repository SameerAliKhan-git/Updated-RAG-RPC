# ═══════════════════════════════════════════════════════════
# Corpus — Developer Workflow Shortcuts
# ═══════════════════════════════════════════════════════════

.PHONY: start stop restart logs test test-cov format lint clean health

# ── Docker Compose ───────────────────────────────────────

start: ## Start all services
	docker compose up --build -d

stop: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose down && docker compose up --build -d

logs: ## Tail service logs
	docker compose logs -f

# ── Testing ──────────────────────────────────────────────

test: ## Run unit tests
	uv run pytest tests/unit/ -v --tb=short

test-all: ## Run all tests (unit + integration)
	uv run pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage report
	uv run pytest tests/ -v --cov=src --cov-report=html --cov-report=term-missing

# ── Code Quality ─────────────────────────────────────────

format: ## Format code with ruff
	uv run ruff format src/ tests/

lint: ## Lint code with ruff + mypy
	uv run ruff check src/ tests/ --fix
	uv run mypy src/ --ignore-missing-imports

# ── Health & Utilities ───────────────────────────────────

health: ## Check system health
	@curl -s http://localhost:8000/api/v1/health | python -m json.tool

clean: ## Remove generated files and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage

# ── Help ─────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
