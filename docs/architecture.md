# Corpus — System Architecture

> *Living document — updated with each build phase.*

## Overview

Corpus is a production-grade agentic RAG system for research papers. It ingests papers from arXiv, indexes them with hybrid search (BM25 + vector), and answers technical questions through a multi-step agentic reasoning loop — with every claim cited to a specific source chunk.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                             │
│   ┌──────────┐   ┌──────────────┐   ┌──────────────────────┐   │
│   │ Gradio   │   │ Telegram Bot │   │ Direct API (curl/SDK)│   │
│   └────┬─────┘   └──────┬───────┘   └──────────┬───────────┘   │
│        └────────────┬────┘──────────────────────┘               │
├─────────────────────┼───────────────────────────────────────────┤
│                     ▼                                           │
│              FastAPI Layer                                      │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  POST /ask-agentic   POST /stream   GET /health          │  │
│   │  Rate limiting (Redis)  ·  Auth  ·  OpenAPI docs         │  │
│   └──────────────────────────┬───────────────────────────────┘  │
├──────────────────────────────┼──────────────────────────────────┤
│                              ▼                                  │
│                    Agentic Layer (LangGraph)                     │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  intake_and_route → plan → retrieve → grade →            │  │
│   │  rerank → build_context → generate → verify_citations →  │  │
│   │  finalize → update_memory                                │  │
│   │                                                          │  │
│   │  Tools: hybrid_search, rerank, get_paper,                │  │
│   │         search_arxiv_live, trigger_ingestion,            │  │
│   │         list_recent, compare                             │  │
│   └──────────────┬───────────────────────────────────────────┘  │
├──────────────────┼──────────────────────────────────────────────┤
│                  ▼                                              │
│          Retrieval Pipeline (LlamaIndex)                        │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  BM25 (OpenSearch) + Dense (Jina v4) → RRF Fusion →     │  │
│   │  Metadata Filters → Cross-Encoder Rerank →               │  │
│   │  Citation-Tagged Context Builder                         │  │
│   └──────────────┬───────────────────────────────────────────┘  │
├──────────────────┼──────────────────────────────────────────────┤
│                  ▼                                              │
│          Data Layer                                             │
│   ┌────────────┐  ┌────────────┐  ┌───────┐  ┌──────────┐     │
│   │ PostgreSQL │  │ OpenSearch │  │ Redis │  │  Ollama  │     │
│   │ (SoR)      │  │ (Search)   │  │(Cache)│  │  (LLM)   │     │
│   └────────────┘  └────────────┘  └───────┘  └──────────┘     │
├─────────────────────────────────────────────────────────────────┤
│          Ingestion Pipeline (Apache Airflow)                    │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  daily_sync → fetch_and_parse (Docling) →                │  │
│   │  chunk_and_index → generate_daily_report → cleanup       │  │
│   └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│          Observability                                          │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Langfuse (tracing) · RAGAS (eval) · Structured Logs     │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Citation & Provenance Data Model

### Paper Level
| Field | Type | Description |
|---|---|---|
| `arxiv_id` | string | arXiv identifier (e.g., `2301.12345`) |
| `title` | string | Paper title |
| `authors` | string[] | Author list |
| `abstract` | text | Paper abstract |
| `published_date` | datetime | Publication date |
| `categories` | string[] | arXiv categories |
| `pdf_url` | string | Direct PDF link |

### Chunk Level
| Field | Type | Description |
|---|---|---|
| `chunk_id` | string | Stable content hash |
| `paper_id` | FK → Paper | Parent paper reference |
| `section_title` | string | Source section heading |
| `chunk_type` | enum | `body`, `table`, `figure-caption`, `equation` |
| `text` | text | Chunk content |
| `embedding` | float[] | Jina v4 passage embedding (1024-dim) |

## API Response Schema

```json
{
  "answer_markdown": "... claim [1] ... claim [2] ...",
  "citations": [
    {
      "id": 1,
      "paper_title": "...",
      "authors": ["..."],
      "arxiv_id": "...",
      "arxiv_url": "...",
      "pdf_url": "...",
      "section": "...",
      "snippet": "..."
    }
  ],
  "grounding_note": "2 of 2 claims verified against source"
}
```

## Build Phases

| Phase | Status | Scope |
|---|---|---|
| 0 — Foundations | ✅ Complete | Monorepo, Docker Compose, CI |
| 1 — Ingestion | ✅ Complete | Airflow DAG, Docling, chunking |
| 2 — Retrieval | ✅ Complete | BM25 + vector + RRF + reranker |
| 3 — Agentic Layer | ✅ Complete | LangGraph loop, tools |
| 4 — API Layer | ✅ Complete | /ask-agentic, /stream, auth |
| 5 — Client Interfaces | ✅ Complete | Gradio UI, Telegram bot |
| 6 — Observability | ✅ Complete | Langfuse, RAGAS, CI gate |
| 7 — Production Hardening | ✅ Complete | Resilience, security, docs |
| 8 — Fine-tuning (Future) | ⬜ Optional | Feedback-driven model tuning |
