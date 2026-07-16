# Corpus — Comprehensive Setup & Operations Manual

This guide provides end-to-end instructions for starting, configuring, logging into, and running the Corpus Agentic RAG pipeline.

---

## 📋 Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Step-by-Step Starting Guide](#2-step-by-step-starting-guide)
3. [🔐 Services & Access Credentials Directory](#3-services--access-credentials-directory)
4. [🛠️ Environment Configuration (.env)](#4-environment-configuration-env)
5. [🔄 End-to-End Functional Validation](#5-end-to-end-functional-validation)
6. [📈 Ingesting and Processing Papers](#6-ingesting-and-processing-papers)
7. [⚡ Performance Optimization & Troubleshooting](#7-performance-optimization--troubleshooting)

---

## 1. Prerequisites
Ensure the following tools are installed on your host machine before starting:
*   **Docker Desktop** (with Compose v2 and enabled WSL 2 integration)
*   **Ollama CLI** (installed natively on host Windows to utilize hardware GPU acceleration)
*   **Python 3.12** and **uv** (for running local development tasks, tests, or scripts)

---

## 2. Step-by-Step Starting Guide

Follow these steps in order to start all components correctly:

### Step 2.1: Start Local Ollama Server with GPU Acceleration
To leverage your system's integrated or discrete GPU for sub-second model response times, run the native host Ollama server with Vulkan acceleration enabled:
1. Open a **PowerShell** window.
2. Run the following command (which configures the environment variables to bypass ROCm/HIP and forces Vulkan GPU acceleration):
   ```powershell
   $env:HIP_VISIBLE_DEVICES="-1"
   $env:OLLAMA_IGPU_ENABLE="1"
   $env:OLLAMA_VULKAN="1"
   ollama serve
   ```
3. Minimize this window to let the Ollama background daemon listen on host port `11434`.

### Step 2.2: Ensure the Local LLM Model is Downloaded
In another command window, verify that the default model (`llama3.2:1b`) is pulled:
```bash
ollama pull llama3.2:1b
```

### Step 2.3: Launch the Docker Compose Services Stack
Navigate to your project root directory and start all Docker services in detached mode:
```bash
docker compose up -d
```
*Alternatively, you can run the shortcut command:*
```bash
make start
```
This boots up the remaining 15 microservices (API, Gradio UI, OpenSearch, Postgres, Airflow, Prometheus, Grafana, Redis, MinIO, etc.) on the shared container network.

---

## 3. 🔐 Services & Access Credentials Directory

Once the containers are running and reported as healthy, you can access the following web dashboards:

| Service / Interface | Local URL Endpoint | Username | Password |
| :--- | :--- | :--- | :--- |
| **Gradio Web Interface** | 🔗 [http://localhost:7860](http://localhost:7860) | *No credentials required* | *No credentials required* |
| **Langfuse Observability** | 🔗 [http://localhost:3001](http://localhost:3001) | `admin@example.com` | `<LANGFUSE_INIT_USER_PASSWORD_in_compose>` *(check local_credentials.txt)* |
| **Airflow 3 Scheduler** | 🔗 [http://localhost:8080](http://localhost:8080) | `admin` | `<auto_generated_simple_auth_password>` *(check local_credentials.txt)* |
| **MinIO Console** | 🔗 [http://localhost:9090](http://localhost:9090) | `langfuse_minio` | `<LANGFUSE_MINIO_SECRET_KEY_in_env>` *(check local_credentials.txt)* |
| **Grafana Monitoring** | 🔗 [http://localhost:3002](http://localhost:3002) | `admin` | `admin` *(forces update on first login)* |
| **OpenSearch Dashboards** | 🔗 [http://localhost:5601](http://localhost:5601) | *No credentials required* | *No credentials required* |

---

## 4. 🛠️ Environment Configuration (.env)

The environment configuration file (`.env`) resides in the root directory and controls service addresses and feature flags:

```env
# ── Application ──────────────────────────────────────────
DEBUG=true
ENVIRONMENT=development
APP_NAME=corpus
API_HOST=0.0.0.0
API_PORT=8000
API_KEY=change-me-to-a-real-api-key

# ── PostgreSQL System of Record ──────────────────────────
POSTGRES_DATABASE_URL=postgresql+psycopg2://rag_user:rag_password@postgres:5432/corpus_db
POSTGRES_DB=corpus_db
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password

# ── Redis Cache & Queue ──────────────────────────────────
REDIS__HOST=redis
REDIS__PORT=6379
REDIS__PASSWORD=
REDIS__DB=0

# ── Jina AI (Disabled by Default for Offline Run) ────────
JINA_API_KEY=your_jina_api_key_here
JINA__EMBEDDING_MODEL=jina-embeddings-v4
JINA__RERANKER_MODEL=jina-reranker-v2-base-multilingual
RERANKER__BACKEND=noop  # Keeps retrieval fast without external API timeouts

# ── Ollama Local LLM Routing ──────────────────────────────
# Resolves host.docker.internal to access native Vulkan GPU on host
OLLAMA_HOST=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2:1b
OLLAMA_TIMEOUT=300

# ── Langfuse Trace Triggers ──────────────────────────────
LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=pk-lf-723a18e2-17f3-4d48-919b-9c952f8ef243
LANGFUSE_SECRET_KEY=sk-lf-77c86fe3-2b22-4841-a185-df853db518f8
```

---

## 5. 🔄 End-to-End Functional Validation

To test that everything is working:

1. **Verify API Endpoint**: Check that the API backend is healthy and responding to external diagnostic pings:
   ```bash
   make health
   ```
2. **Execute a RAG Query via Gradio**:
   *   Open `http://localhost:7860` in your browser.
   *   Enter a query: `"Compare self-attention vs cross-attention mechanisms"` or click one of the suggestion pills.
   *   Click **Ask →**.
   *   The system will search the database, classify the intent, grade relevance, assemble context, and output a citation-tagged explanation.
3. **Verify Langfuse Tracing**:
   *   Open `http://localhost:3001` and sign in.
   *   Go to **Corpus Agentic RAG** -> **Traces**.
   *   Click the latest trace labeled `agentic_rag_flow` to inspect the tree diagram and latency distribution of all executed graph nodes.

---

## 6. 📈 Ingesting and Processing Papers

You can feed new scientific PDF papers into the RAG vector index using three methods:

### Method A: Automated Batch Ingestion (Airflow)
1. Open the Airflow 3 Dashboard (`http://localhost:8080`) and sign in.
2. Find the DAG named `daily_arxiv_ingestion`.
3. Click the **Play (Trigger DAG)** button to crawl arXiv, fetch the latest papers, parse layouts via Docling, create chunks, embed text, and upsert vectors.

### Method B: MinIO S3 Bucket Upload
1. Open the MinIO Console (`http://localhost:9090`) and sign in.
2. Navigate to **Buckets** -> upload new PDF files directly into the raw ingestion bucket.
3. The background worker container (`arq-worker`) will detect new documents and kick off parsing.

### Method C: Command-Line CLI script
To parse and index a specific arXiv paper immediately, run:
```bash
docker compose exec api python src/run_ingest.py --arxiv-id 2305.18290
```

---

## 7. ⚡ Performance Optimization & Troubleshooting

### Understanding Cold Start (First Query Timeout)
When containers are first spun up, the **first query may display `Error: timed out`** in Gradio.
*   **Why**: Ollama needs to load the 1.2GB model weights into Vulkan VRAM for the first time, and Postgres/OpenSearch connection pools must be initialized.
*   **What to do**: Wait 30 seconds for the model load to complete, reload the browser tab, and resubmit the query. Subsequent warm queries will run in **under 15-20 seconds**.

### Disabling / Enabling Secondary LLM Verification
We added an environment toggle `ENABLE_LLM_VERIFICATION` in the graph nodes to control whether the second-stage heavy LLM verification runs:
*   By default, it is **disabled** to keep response times fast for integrated GPU/CPU systems.
*   To enable strict, multi-step output verification, add the following to your `.env` and restart the API:
    ```env
    ENABLE_LLM_VERIFICATION=true
    ```
    *Restart the service:*
    ```bash
    docker compose restart api
    ```
