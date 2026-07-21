# Corpus — Agentic Research Paper Curator

<p align="center">
  <img src="docs/images/hero-dark.webp" alt="Corpus — ask your papers anything, cited to the exact page, every time. Research papers dissolve into a flowing gradient that resolves into a cited chat answer." width="100%">
</p>

> *Ask your papers anything — cited to the exact page, every time.*

**Corpus** is a production-grade, fully open-source agentic RAG system for research papers. It ingests papers from arXiv (or your own PDFs and Zotero library), and answers technical questions with **every claim cited to the exact page of the exact source** — viewable in an in-app PDF reader with the cited passage highlighted. It runs **100% locally and free**: no paid APIs, no cloud dependencies.

The UI follows the **Google Gemini design language** — light/dark themes, the signature gradient, pill-shaped surfaces, and functional motion.

## From Claim to Page — the Core Promise

Every sentence Corpus generates carries an inline `[N]` that resolves to the exact section and page of the source PDF, with the supporting passage highlighted. Citations the source doesn't actually support are stripped before you ever see them.

<p align="center">
  <img src="docs/images/trust-chain-dark.webp" alt="From Claim to Page: an answer's [2] citation chip links to a citation card (paper title, section, page 7), to the highlighted passage in the source PDF, to a verification badge reading 'claim supported by source' — unsupported citations are stripped, not shown." width="100%">
</p>

---

## Feature Highlights

| Category | Features |
|---|---|
| **Trustworthy answers** | Inline `[N]` citations → exact PDF page with passage highlighting · deterministic + optional LLM claim verification ("deep verify") · honest gap admission · extractive fallback when the LLM is down (retrieval never fails) |
| **Gemini-style chat** | True token streaming (SSE) · live agent-trace timeline · voice input · attach-a-PDF and chat with it · collections (notebook-scoped chat) · semantic answer cache |
| **Research tools** | **Deep Research**: background agent writes a fully-cited literature review · **Research Galaxy**: interactive concept-graph visualization · related-work discovery via Semantic Scholar · audio overviews (local Piper TTS) · figures/tables gallery + visual-only search · reading tracker · Zotero import · export to Markdown + BibTeX |
| **Quality flywheel** | Nightly golden-set evaluation (RAGAS + retrieval hit@k/MRR) with trend charts · thumbs feedback → monthly reranker fine-tuning with an **auto-promotion eval gate** · hourly canary probe |
| **Operations** | Nightly Postgres backups + one-command restore · Prometheus metrics + Grafana dashboard · Langfuse tracing (opt-in) · request correlation IDs · dead-letter view for failed ingestions · lean/full Docker profiles · CI with unit, integration, and browser E2E tests |

---

## System Architecture

<p align="center">
  <img src="docs/images/architecture-dark.webp" alt="Corpus architecture in six layers: Clients (React SPA, Telegram bot) → FastAPI → the LangGraph agentic pipeline (route, plan, retrieve, CRAG grade, rerank, build context, generate, verify citations, with rewrite-query and live-arXiv fallbacks) → local models (Ollama, MiniLM reranker, Piper TTS) → data stores (PostgreSQL, OpenSearch, Redis, PDF cache) → opt-in Airflow offline pipelines." width="100%">
</p>

<details>
<summary>Same diagram as editable Mermaid source</summary>

```mermaid
flowchart TB
    subgraph Clients
        UI["React + Vite SPA<br/>(Gemini design, port 7860)"]
        TG["Telegram Bot<br/>(opt-in, profile: telegram)"]
    end

    subgraph API["FastAPI (port 8000)"]
        ASK["/stream · /ask-agentic"]
        REST["collections · sessions · papers<br/>research · concepts · eval · health"]
        CANARY["hourly canary probe"]
    end

    subgraph Agent["LangGraph Agentic Pipeline"]
        ROUTE["route<br/>(heuristic → LLM)"] --> PLAN["plan"] --> RETRIEVE["retrieve"]
        RETRIEVE --> GRADE["CRAG grade"] --> RERANK["rerank"] --> CTX["build context"]
        CTX --> GEN["generate (streamed)"] --> VERIFY["verify citations"]
        GRADE -.->|insufficient| REWRITE["rewrite query"] -.-> RETRIEVE
        GRADE -.->|exhausted| LIVE["live arXiv lookup"]
    end

    subgraph Models["Local Models (all free)"]
        OLLAMA["Ollama (host)<br/>llama3.2 LLMs + bge-m3 embeddings"]
        RERANKER["MiniLM cross-encoder<br/>(in-process, feedback-tunable)"]
        PIPER["Piper TTS<br/>(audio overviews)"]
    end

    subgraph Data
        PG[("PostgreSQL<br/>papers · chunks · collections<br/>sessions · concept graph")]
        OS[("OpenSearch<br/>BM25 + KNN, RRF fusion")]
        REDIS[("Redis<br/>session memory · semantic cache<br/>rate limits · task queue")]
        PDFS[("PDF cache<br/>./data/arxiv_pdfs")]
    end

    subgraph Offline["Offline Pipelines (Airflow, opt-in)"]
        INGEST["daily arXiv ingestion<br/>(Docling parse → chunk → embed)"]
        EVAL["nightly golden-set eval"]
        CONCEPTS["nightly concept-graph builder"]
        TRAIN["monthly reranker training"]
        BACKUP["nightly pg_dump (always on)"]
    end

    UI --> API --> Agent
    TG --> API
    Agent --> Models
    Agent --> OS & PG & REDIS
    INGEST --> PG & OS & PDFS
    EVAL --> REDIS
    CONCEPTS --> PG
    TRAIN --> RERANKER
```

</details>

### Self-Correcting Agentic Pipeline

The pipeline doesn't just retrieve-then-answer. When retrieval comes back thin it **rewrites the query and retries**; when the local corpus is exhausted it falls back to a **live arXiv lookup**; when a generated citation isn't supported it's **stripped and re-verified**; and when the corpus genuinely lacks coverage it **admits the gap instead of guessing**.

<p align="center">
  <img src="docs/images/agentic-loop-dark.webp" alt="Agentic RAG pipeline with self-correction: the happy path route → plan → retrieve → grade → rerank → build context → generate → verify citations → finalize, with correction loops — insufficient chunks rewrite the query, exhausted retries trigger a live arXiv lookup, unsupported citations are stripped and re-verified, and genuinely missing coverage yields an honest gap admission." width="100%">
</p>

## End-to-End: What Happens When You Ask a Question

<p align="center">
  <img src="docs/images/sequence-flow-dark.webp" alt="Sequence diagram of a question: browser POSTs to nginx which proxies to FastAPI (SSE, buffering off); FastAPI sanitizes and checks the semantic cache, then calls the LangGraph pipeline, which streams a router trace, runs hybrid BM25+KNN search on OpenSearch, grades chunks on Ollama, reranks and builds cited context, streams generation tokens live, verifies citations, and streams citation and done events; clicking [N] opens the PDF at the cited page with the passage highlighted." width="100%">
</p>

<details>
<summary>Same diagram as editable Mermaid source</summary>

```mermaid
sequenceDiagram
    participant U as User (browser)
    participant N as nginx (7860)
    participant A as FastAPI
    participant G as LangGraph
    participant O as Ollama (host)
    participant S as OpenSearch

    U->>N: POST /api/v1/stream {query, collection_id?, verify?}
    N->>A: proxy (buffering off — SSE)
    A->>A: guardrails sanitize · semantic-cache check
    A->>G: ask_corpus_streaming()
    G-->>U: trace: "router: heuristic → simple"  (live SSE)
    G->>S: hybrid BM25+KNN search (RRF, scoped to collection)
    G->>O: grade chunks (fast model)
    G->>G: rerank (cross-encoder) · build cited context
    loop token streaming
        G->>O: generate
        O-->>U: token events (live, word by word)
    end
    G->>G: verify citations (strip invented [N], deep verify if on)
    G-->>U: citation events (paper, section, page)
    G-->>U: done {verified answer, grounding note}
    U->>U: click [N] → PDF opens at page, passage highlighted
```

</details>

## Ingestion Path

Whether a paper arrives from the daily arXiv DAG or a manual PDF upload, it flows through the same layout-aware pipeline — and the **page number is preserved end to end** so every future citation can point at the exact page.

<p align="center">
  <img src="docs/images/ingestion-dark.webp" alt="Ingestion path: arXiv fetch or PDF upload → Docling layout-aware parse (sections, tables, figures, equations, page numbers) → structure-aware chunking (~500 words, atomic visual blocks) → visual-summary LLM pass → bge-m3 embeddings via Ollama (1024-dim) → dual-write to PostgreSQL (source of truth) and OpenSearch (search index), with the page number preserved throughout." width="100%">
</p>

## Hybrid Retrieval — BM25 + Vector, Fused

Every query runs **both** a BM25 keyword search and a KNN vector search (bge-m3), and the two rankings are merged with **Reciprocal Rank Fusion** — so a passage that keyword search ranks low but vector search ranks high still survives into the context. A cross-encoder reranker then does the final precise scoring down to the top 4 cited chunks.

<p align="center">
  <img src="docs/images/hybrid-retrieval-dark.webp" alt="Hybrid retrieval: a query fans out to BM25 keyword search and KNN vector search (bge-m3, 1024-dim), each producing a ranked list; a document ranked 5th by keywords but 2nd by vectors survives Reciprocal Rank Fusion into the fused top results, which feed a MiniLM cross-encoder reranker that outputs the top 4 chunks injected into the generation prompt." width="100%">
</p>

<p align="center"><sub><i>Document titles and scores above are illustrative.</i></sub></p>

## Quality Flywheel

Corpus gets better the more it's used. Thumbs feedback is stored with the cited passages, monthly fine-tuning trains a candidate reranker, and an **eval gate only promotes it if it beats the current model** on a held-out set — while nightly golden-set evaluation tracks faithfulness, relevancy, and hit@k/MRR over time.

<p align="center">
  <img src="docs/images/flywheel-dark.webp" alt="Quality flywheel: users rate answers → feedback stored with cited passages → monthly reranker fine-tuning (needs ≥50 rated answers) → eval gate comparing held-out AUC against the base model; a pass auto-promotes the model to production for better answers, a fail keeps collecting; a side branch runs nightly golden-set RAGAS evaluation tracking faithfulness, relevancy, and hit@k/MRR over time." width="100%">
</p>

---

## Quick Start

**Prerequisites:** Docker Desktop, [Ollama](https://ollama.com) installed natively on the host, Node 20+, Python 3.12 + [uv](https://docs.astral.sh/uv/).

```powershell
# 1. Models (one-time, ~3GB total)
ollama pull llama3.2:1b        # LLM (use llama3.2:3b+ with ≥16GB free RAM)
ollama pull bge-m3             # embeddings (1024-dim)

# 2. On low-RAM machines, cap Ollama's context (prevents OOM):
#    set user env vars: OLLAMA_CONTEXT_LENGTH=8192, OLLAMA_KEEP_ALIVE=30m
#    AMD iGPU on Windows: also OLLAMA_VULKAN=0

# 3. Configure
copy .env.example .env         # defaults work out of the box

# 4. Start the lean stack (6 containers)
docker compose up -d

# 5. Ingest some papers
docker exec corpus-api python -m src.run_ingest

# 6. Open the app
#    http://localhost:7860
```

**Optional profiles:**

```powershell
docker compose --profile observability up -d   # Prometheus, Grafana, Langfuse
docker compose --profile airflow up -d          # scheduled DAGs (ingestion, eval, concepts, training)
docker compose --profile telegram up -d         # Telegram bot (needs TELEGRAM__BOT_TOKEN in .env)
```

---

## Key Configuration (.env)

| Variable | Default | Purpose |
|---|---|---|
| `LITELLM__DRAFTING_MODEL` etc. | `ollama/llama3.2:1b` | LLM per role (reasoning/drafting/fast) — one line to upgrade |
| `MODEL_AUTOSELECT` | `true` | Probe-and-pick the best loadable model at startup |
| `EMBEDDING__BACKEND` | `ollama` | `ollama` (bge-m3, fast) or `local` (sentence-transformers) — **changing requires `uv run python -m src.run_reindex`** |
| `RERANKER__MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Point at `models/reranker-tuned` after feedback training |
| `ENABLE_LLM_VERIFICATION` | `false` | Always-on LLM claim checking (the UI shield toggles it per-question) |
| `SEMANTIC_CACHE_ENABLED` | `true` | Serve near-duplicate questions instantly |
| `GRADING_MAX_CHUNKS` / `GENERATION_MAX_TOKENS` | `8` / `1024` | CPU latency budget knobs |
| `API_KEY` + `ENVIRONMENT` | — | Auth is enforced outside `development`. nginx injects the key for the SPA, so the UI keeps working and the key never reaches the browser |
| `CORS_ALLOW_ORIGINS` | `localhost:7860,5173,5174` | Only needed for browser clients on a *different* origin than the API |
| `RERANKER__AUTO_PROMOTE` | `true` | Load a feedback-tuned reranker that passed its eval gate, without an `.env` edit |

## Operations

| Task | Command |
|---|---|
| Backup now (nightly is automatic) | `docker exec corpus-backup sh -c 'pg_dump -h postgres -U rag_user -Fc corpus_db > /backups/manual.dump'` |
| **Restore from disaster** | `.\scripts\restore.ps1` (latest dump; rebuilds the index) |
| Re-embed everything | `uv run python -m src.run_reindex` |
| Run the golden evaluation | System page → *Run evaluation*, or `POST /api/v1/eval/run?mode=golden` |
| Train the reranker on feedback | `uv run python scripts/train_reranker.py` |
| Health / canary | `GET /api/v1/health` · `GET /api/v1/health/canary` |
| Metrics | `GET :8000/metrics` (Prometheus) · Grafana at `:3002` |

## Testing

```powershell
uv run pytest tests/unit tests/integration tests/eval    # backend (19 tests)
cd frontend; npx playwright test                          # browser E2E vs mock API
```

CI runs lint (ruff), types (mypy), unit + golden eval, integration (service containers), and the Playwright browser suite on every push.

## Project Structure

```
src/
  agents/        LangGraph pipeline, heuristic router, prompts, tools
  ingestion/     arXiv fetch · Docling parsing · chunking · orchestrator
  retrieval/     hybrid search (BM25+KNN+RRF) · reranker · context builder
  services/      embeddings · LLM adapter · deep research · audio overviews ·
                 canary · guardrails · Zotero · concept extractor · resilience
  routers/       ask/stream · collections · sessions · research · concepts ·
                 integrations · eval · health
  db/ models/    Postgres models + idempotent startup migrations
frontend/        React + Vite + TS (Gemini design system, see DESIGN.md)
airflow/dags/    daily ingestion · nightly eval · concept graph · reranker training
scripts/         restore.ps1 · train_reranker.py
```

## License

MIT — every component in the stack (models, databases, frameworks) is free and open source.
