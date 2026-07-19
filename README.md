# Corpus — Agentic Research Paper Curator

> *Ask your papers anything — cited, every time.*

**Corpus** is a production-grade, agentic Retrieval-Augmented Generation (RAG) system that curates research papers from arXiv and answers technical questions by reasoning over them. Every claim in every answer is traceable to a specific cited source chunk with a working link back to the paper.

It integrates state-of-the-art layout-aware document parsing, asymmetric vector and keyword search, a stateful 11-node LangGraph orchestration agent, pluggable model routing, structured citation output verification, and multi-client streaming delivery interfaces.

---

## Table of Contents

1. [Key Features](#key-features)
2. [System Architecture](#system-architecture)
3. [Project Directory Structure](#project-directory-structure)
4. [Environment Configuration Reference](#environment-configuration-reference)
5. [Quick Start & Setup Guide](#quick-start--setup-guide)
6. [Running the Application](#running-the-application)
7. [Developer Workflow & Makefile](#developer-workflow--makefile)
8. [Automated Testing & CI Gates](#automated-testing--ci-gates)
9. [Claude Code Bot](#claude-code-bot)
10. [API Endpoint Reference](#api-endpoint-reference)
11. [Observability & Evaluation](#observability--evaluation)
12. [License](#license)

---

## Key Features

*   **Ingestion Pipeline (Apache Airflow):** Layout-aware document parsing powered by **Docling** (with Granite-Docling support). Chunks are created along structural section boundaries. Mathematical equations, figures, and tables are preserved as atomic, untruncated blocks.
*   **Dual-Write Storage Split:** Metadata and complete chunk provenance are recorded in **PostgreSQL** (the System of Record), while text and embeddings are stored in **OpenSearch** for retrieval.
*   **Hybrid Search & Reranking:** OpenSearch BM25 (sparse) and **Jina Embeddings v4** (dense) merged using **Reciprocal Rank Fusion (RRF)**. Results are reranked using a pluggable reranker interface (defaulting to **Jina Reranker v2**).
*   **Central Agentic Layer (LangGraph):** A stateful 11-node orchestration graph manages intake routing, query planning, parallel retrieval, CRAG-style chunk relevance grading, query rewriting, live arXiv fallback retrieval, on-demand task queue ingestion, and structured citation verification.
*   **LiteLLM Model Router:** Routes reasoning-heavy nodes (planning, grading, verification) to stronger models and bulk drafting to cheaper models.
*   **Strict Citation & Provenance System:** Answers are returned with inline `[N]` citation tokens. A second-pass verification node compares every claim in the generated text against its cited chunk and strips or hedges unsupported assertions.
*   **Multi-Client Interfaces:**
    *   **Gradio Web App:** A zero.xyz-inspired dark, terminal-native command interface with clickable inline citation chips, hover preview snippets, and a live Signal-blue **Agent Trace** panel streaming LangGraph nodes in real-time.
    *   **Telegram Bot:** Secondary channel allowing queries and retrieval via commands.
*   **Redis Multi-Purpose Store:** Handles session conversational history, semantic cache, rate limiting, and runs the **Arq** asynchronous task queue for single-paper live ingestion.
*   **Observability & Evaluator:** Visualizes complete execution traces with **Langfuse** and evaluates RAG metrics (faithfulness, relevance) using **RAGAS**.

---

## System Architecture

### Information Flow Diagram

```
                 ┌────────────────────────────────────────────────────────┐
                 │                      Client Layer                      │
                 │   ┌──────────┐  ┌──────────────┐  ┌────────────────┐   │
                 │   │  Gradio  │  │ Telegram Bot │  │ API (curl/SDK) │   │
                 │   └────┬─────┘  └──────┬───────┘  └────────┬───────┘   │
                 └────────┼───────────────┼───────────────────┼───────────┘
                          │               │                   │
                          ▼               ▼                   ▼
                 ┌────────────────────────────────────────────────────────┐
                 │                 FastAPI REST API Server                │
                 │  - POST /ask-agentic     - POST /stream  (SSE)         │
                 │  - Rate Limiting (Redis) - API Key Authentication      │
                 └────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
                 ┌────────────────────────────────────────────────────────┐
                 │                Agentic Layer (LangGraph)               │
                 │  intake_and_route ──► plan ──► retrieve ──► grade     │
                 │                                               │        │
                 │  admit_gap ◄── admit_gap_branch ◄── grade_br ◄┘        │
                 │                                      │                 │
                 │  rewrite_query ◄── rewrite_branch ◄──┤                 │
                 │                                      ▼                 │
                 │  generate ◄── build_context ◄── rerank ◄── live_arxiv  │
                 │     │                                                  │
                 │     ▼                                                  │
                 │  verify_citations ──► finalize ──► update_memory       │
                 └────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
                 ┌────────────────────────────────────────────────────────┐
                 │            Retrieval Pipeline (LlamaIndex)             │
                 │  - BM25 (OpenSearch) + Jina v4 Dense (OpenSearch)      │
                 │  - RRF Fusion + Recency/Category Metadata Filters      │
                 │  - Jina Reranker Cross-Encoder Rerank Pass             │
                 └────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
                 ┌────────────────────────────────────────────────────────┐
                 │                   Infrastructure Layer                 │
                 │  ┌────────────┐ ┌────────────┐ ┌─────────┐ ┌────────┐  │
                 │  │ PostgreSQL │ │ OpenSearch │ │  Redis  │ │ Ollama │  │
                 │  │ (Metadata) │ │  (Search)  │ │ (Cache) │ │ (LLMs) │  │
                 │  └────────────┘ └────────────┘ └─────────┘ └────────┘  │
                 └────────────────────────────────────────────────────────┘
```

---

## Project Directory Structure

```
corpus/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI workflow
├── airflow/
│   ├── dags/
│   │   └── daily_arxiv_ingestion.py  # Scheduled bulk ingestion DAG
│   ├── plugins/                # Custom Airflow plugin directories
│   ├── Dockerfile              # Airflow custom worker Docker image
│   └── requirements-airflow.txt # Ingestion dependencies
├── docs/
│   ├── architecture.md         # Detailed architectural layout specification
│   └── runbook.md              # Operations runbook, ports list, & troubleshooting
├── grafana/
│   └── provisioning/           # Grafana dashboards provision configuration
├── prometheus/
│   └── prometheus.yml          # Prometheus scrape and targets configuration
├── src/                        # Main Application Code
│   ├── agents/
│   │   ├── prompts.py          # Structured templates for graph LLM prompts
│   │   ├── rag_graph.py        # 11-node LangGraph orchestration state machine
│   │   └── tools.py            # Custom toolkit utilities bound to the agent
│   ├── clients/
│   │   ├── gradio_app.py       # Gradio UI client (custom void/graphite tokens)
│   │   └── telegram_bot.py     # Secondary Telegram lookup channel bot
│   ├── db/
│   │   ├── opensearch.py       # OpenSearch clients and RRF registration scripts
│   │   ├── opensearch_mapping.py # Search index templates and settings mappings
│   │   └── postgres.py         # SQLAlchemy postgres engine connection factory
│   ├── ingestion/
│   │   ├── arxiv_source.py     # arXiv API client with keyless queries throttling
│   │   ├── chunker.py          # Structure-aware chunk parsing class
│   │   ├── interfaces.py       # Abstract definitions for document extractors
│   │   ├── orchestrator.py     # orchestrates fetch -> parse -> chunk -> embed -> write
│   │   └── pdf_parser.py       # Docling document parsing service wrapper
│   ├── middleware/
│   │   ├── auth.py             # Simple API key authentication middleware
│   │   └── rate_limiter.py     # Sliding window rate limiter over Redis
│   ├── models/
│   │   └── paper.py            # PostgreSQL SQLAlchemy SoR schemas
│   ├── routers/
│   │   ├── ask.py              # Main POST endpoints (/ask-agentic, /stream, /search)
│   │   ├── feedback.py         # POST /api/v1/feedback (thumbs up/down logging)
│   │   └── health.py           # GET /api/v1/health (degraded connection checks)
│   ├── schemas/
│   │   ├── ask.py              # Pydantic schemas for queries and responses
│   │   └── health.py           # Pydantic schemas for health statuses
│   ├── services/
│   │   ├── arq_worker.py       # Arq background Redis task worker
│   │   ├── jina_client.py      # Embeddings and rerank API gateway client
│   │   ├── llm_adapter.py      # LiteLLM router adapter class
│   │   ├── ragas_sampler.py    # RAGAS sampled trace quality assessment job
│   │   ├── redis_client.py     # Redis engine core connections pool
│   │   ├── redis_services.py   # Cache, session history, and task enqueuer wrapper
│   │   ├── resilience.py       # Tenacity retries and HTTP backoffs configuration
│   │   └── tracing.py          # Langfuse traces mapping decorators
│   ├── config.py               # Aggregated Pydantic settings loading
│   └── main.py                 # FastAPI application assembly factory
├── tests/
│   ├── eval/
│   │   └── eval_golden.py      # pytest quality evaluation gate
│   ├── integration/
│   │   ├── test_api_stream.py  # SSE endpoint integration check
│   │   ├── test_ingestion.py   # In-memory SQLite ingestion parser check
│   │   └── test_rag_graph.py   # State machine routing integration check
│   └── unit/
│       ├── test_context_builder.py
│       ├── test_health.py
│       ├── test_llm_adapter.py
│       ├── test_parser.py
│       ├── test_rate_limiter.py
│       ├── test_redis_services.py
│       └── test_reranker.py
├── Dockerfile                  # Core FastAPI application image
├── Dockerfile.gradio           # Standalone Gradio client image
├── Makefile                    # Developer execution commands wrapper
├── pyproject.toml              # Ruff, mypy, and UV package manager settings
└── README.md                   # Complete developer guide and overview
```

---

## Environment Configuration Reference

The application is configured using variables declared in a `.env` file. These map directly to typed schemas in `src/config.py`.

### Application Configurations
| Environment Variable | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `DEBUG` | `bool` | `true` | Enables console output renderer and disables rate limits. |
| `ENVIRONMENT` | `str` | `development` | Environment label (`development`, `staging`, `production`). |
| `API_HOST` | `str` | `0.0.0.0` | Host IP address of the FastAPI backend. |
| `API_PORT` | `int` | `8000` | Port of the FastAPI backend. |
| `API_KEY` | `str` | `""` | Restricts access to backend endpoints if set. |

### PostgreSQL & OpenSearch Settings
| Environment Variable | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `POSTGRES_DATABASE_URL` | `str` | `postgresql+psycopg2://rag_user:rag_password@localhost:5432/corpus_db` | Connection string for Postgres SoR database. |
| `OPENSEARCH__HOST` | `str` | `http://localhost:9200` | Host connection URL of the OpenSearch database cluster. |
| `OPENSEARCH__INDEX_NAME` | `str` | `corpus-papers` | Target index for raw metadata documents. |
| `OPENSEARCH__CHUNK_INDEX_NAME` | `str` | `corpus-chunks` | Target index for hybrid search chunks. |

### Redis & arq Task Queue Settings
| Environment Variable | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `REDIS__HOST` | `str` | `localhost` | Host connection URL of the Redis server. |
| `REDIS__PORT` | `int` | `6379` | Connection port of the Redis server. |
| `REDIS__PASSWORD` | `str` | `""` | Connection password of the Redis server. |

### API Embeddings & LLM Settings
| Environment Variable | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `JINA_API_KEY` | `str` | `""` | **Required.** Jina API Key used to embed passages and rerank chunks. |
| `OLLAMA_HOST` | `str` | `http://localhost:11434` | Endpoint of the Ollama server serving local models. |
| `LITELLM__DEFAULT_MODEL` | `str` | `ollama/llama3.2:1b` | Default LLM routed for normal queries. |
| `LITELLM__REASONING_MODEL` | `str` | `ollama/llama3.2:1b` | Directed LLM routed for planning, grading, and verifying. |
| `LITELLM__DRAFTING_MODEL` | `str` | `ollama/llama3.2:1b` | Directed LLM routed for text answers drafting. |

### Observability & Third-party Integrations
| Environment Variable | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `LANGFUSE_ENABLED` | `bool` | `true` | Enables/disables telemetry to Langfuse panel. |
| `LANGFUSE_HOST` | `str` | `http://localhost:3001` | Langfuse dashboard collection server address. |
| `LANGFUSE_PUBLIC_KEY` | `str` | `""` | Public API authorization key for Langfuse dashboard. |
| `LANGFUSE_SECRET_KEY` | `str` | `""` | Private API authorization key for Langfuse dashboard. |
| `TELEGRAM__ENABLED` | `bool` | `false` | Enables/disables secondary Telegram bot client. |
| `TELEGRAM__BOT_TOKEN` | `str` | `""` | Telegram authentication token key (issued by BotFather). |

---

## Quick Start & Setup Guide

### 1. Prerequisites
Ensure you have the following installed on your system:
*   **Docker Desktop** (with Compose v2+)
*   **Python 3.12+**
*   **uv** package manager ([Installation Guide](https://docs.astral.sh/uv/getting-started/installation/))
*   **Ollama CLI** (installed natively on host Windows to utilize hardware GPU acceleration)

---

### 2. Configure Local Environment
Clone the repository and copy the environment template:
```bash
git clone https://github.com/SameerAliKhan-git/Updated-RAG-RPC.git
cd Updated-RAG-RPC

# Scaffolding configuration files
cp .env.example .env
```
Open `.env` and fill in your keys (especially generate a new encryption key using `openssl rand -hex 32` for `LANGFUSE_ENCRYPTION_KEY`). Set `RERANKER__BACKEND=noop` to skip external Jina AI API timeouts.

---

### 3. Native Host Ollama GPU Startup
To leverage your system's hardware GPU/VRAM for sub-second text generation speeds:
1. Open a **PowerShell** window on the host.
2. Run the environment toggles to bypass HIP/ROCm and force Vulkan GPU compute:
   ```powershell
   $env:HIP_VISIBLE_DEVICES="-1"
   $env:OLLAMA_IGPU_ENABLE="1"
   $env:OLLAMA_VULKAN="1"
   ollama serve
   ```
3. In another terminal, pull the default RAG model:
   ```bash
   ollama pull llama3.2:1b
   ```

---

### 4. Build and Start Services
Start the infrastructure services in the background using docker compose:
```bash
docker compose up --build -d
```
This spins up PostgreSQL, OpenSearch, Redis, Airflow, Clickhouse, Langfuse, Prometheus, and Grafana containers.

---

### 🔐 Master Services Credentials Directory

Once the containers are running and healthy, you can access the following web dashboards:

| Service / Interface | Local URL Endpoint | Username | Password |
| :--- | :--- | :--- | :--- |
| **Gradio Web Interface** | 🔗 [http://localhost:7860](http://localhost:7860) | *No credentials* | *No credentials* |
| **Langfuse Observability** | 🔗 [http://localhost:3001](http://localhost:3001) | `admin@example.com` | `<LANGFUSE_INIT_USER_PASSWORD_in_compose>` *(check local_credentials.txt)* |
| **Airflow 3 Scheduler** | 🔗 [http://localhost:8080](http://localhost:8080) | `admin` | `<auto_generated_simple_auth_password>` *(check local_credentials.txt)* |
| **MinIO S3 Console** | 🔗 [http://localhost:9090](http://localhost:9090) | `langfuse_minio` | `<LANGFUSE_MINIO_SECRET_KEY_in_env>` *(check local_credentials.txt)* |
| **Grafana Monitoring** | 🔗 [http://localhost:3002](http://localhost:3002) | `admin` | `admin` *(change on first login)* |
| **OpenSearch Dashboards** | 🔗 [http://localhost:5601](http://localhost:5601) | *No credentials* | *No credentials* |

---

---

## Running the Application

### Running Backend Service
Start the FastAPI server on localhost:
```bash
uv run uvicorn src.main:create_app --factory --reload --host 0.0.0.0 --port 8000
```
API Documentation is automatically generated and accessible at [http://localhost:8000/docs](http://localhost:8000/docs).

### Running Gradio client (Web App)
Start the zero.xyz-themed web interface:
```bash
uv run python -m src.clients.gradio_app
```
Open [http://localhost:7860](http://localhost:7860) to access the client web panel.

### Running Telegram Bot client
Start the secondary channel bot listener:
```bash
uv run python -m src.clients.telegram_bot
```

### Running Ingestion Worker (Arq)
Start the background worker to parse and embed on-demand single-paper requests:
```bash
uv run arq src.services.arq_worker.WorkerSettings
```

---

## Developer Workflow & Makefile

The project includes a `Makefile` to speed up common operations:

```bash
# Start all docker compose containers
make start

# Stop all docker compose containers
make stop

# Run unit tests only
make test

# Run the complete test suite (unit + integration)
make test-all

# Run lint checks and code auto-formatting (Ruff)
make lint
make format

# Clean cache directories and python temporary files
make clean

# Verify application backend health status
make health
```

---

## Automated Testing & CI Gates

The codebase contains a comprehensive automated testing suite structured in `tests/`:

*   **Unit Tests (`tests/unit/`):** Fast, mocked validation of components.
    *   `test_context_builder.py`: Formats chunk structures into prompt injection text blocks.
    *   `test_health.py`: Validates graceful health fallback statuses if dependencies go down.
    *   `test_redis_services.py`: Asserts cache validation logic and semantic threshold mappings.
*   **Integration Tests (`tests/integration/`):** Exercises integration points:
    *   `test_rag_graph.py`: Validates routing, query decomposition, and verification nodes in the LangGraph state machine.
    *   `test_ingestion.py`: Verifies database migrations and index schemas creation during document indexing.
    *   `test_api_stream.py`: Tests the server-side EventStream formats for API streams.
*   **Golden Quality Gate (`tests/eval/eval_golden.py`):** Acts as a CI release gate. Runs standard queries against a mock index and asserts output markdown formatting, minimum citations threshold counts, and prevents hallucinated citations before merging pull requests.

To run all checks:
```bash
uv run pytest tests/ -v
```

---

## Claude Code Bot

The repository now includes a dedicated GitHub Actions workflow at:

* `.github/workflows/claude-code.yml`

This enables the **Claude Code Bot** for issue comments, PR review comments, issue assignment/labeling, and PR reviews.

### Required Secret

Set the following repository secret before using the bot:

* `ANTHROPIC_API_KEY`

By default, users can trigger the bot in supported events with `@claude`.

---

## API Endpoint Reference

### 1. Run Complete Agent Query
*   **Endpoint:** `POST /api/v1/ask-agentic`
*   **Request Headers:**
    *   `Content-Type: application/json`
    *   `X-API-Key: <your-key>` (if configured)
*   **Request Payload:**
    ```json
    {
      "query": "Compare standard transformers with state-space models.",
      "session_id": "session_uuid_123"
    }
    ```
*   **Response Payload (200 OK):**
    ```json
    {
      "answer_markdown": "Based on selective state-space models [1], they scale linearly compared to self-attention mechanisms [2] which scale quadratically.",
      "citations": [
        {
          "id": 1,
          "paper_title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
          "authors": ["Albert Gu", "Tri Dao"],
          "arxiv_id": "2312.00752",
          "arxiv_url": "https://arxiv.org/abs/2312.00752",
          "pdf_url": "https://arxiv.org/pdf/2312.00752.pdf",
          "section": "Introduction",
          "snippet": "We present selective state-space models showing linear time scale complexity..."
        }
      ],
      "grounding_note": "1 of 1 claims verified against source"
    }
    ```

### 2. Stream Agent Output (Server-Sent Events)
*   **Endpoint:** `POST /api/v1/stream`
*   *Streams SSE events:*
    *   `event: trace` — Streams state updates, e.g. `{"event": "classifying query..."}`
    *   `event: token` — Streams answer text tokens incrementally, e.g. `{"text": "Based"}`
    *   `event: citation` — Streams completed citation blocks as they are verified.
    *   `event: done` — Streams final payload matching the `/ask-agentic` structure.

---

## Observability & Evaluation

### Langfuse Tracing
Telemetry is gathered for every single node in the LangGraph graph execution.
*   Access the Langfuse dashboard at [http://localhost:3001](http://localhost:3001).
*   View latency timelines, LLM token metrics, and input/output payloads per node.
*   Manage and version LLM prompts inside the Langfuse Prompt Registry.

### RAGAS Evaluator
*   `src/services/ragas_sampler.py` periodically fetches traces from Langfuse, samples them, and evaluates them using RAGAS metrics (**Faithfulness**, **Answer Relevancy**).
*   Logs warning alerts and metrics data directly to Prometheus/Grafana dashboard monitors.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.