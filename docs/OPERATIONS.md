# Corpus — Operations & Troubleshooting

The single operational reference for running Corpus day to day. Architecture,
features, and quickstart live in the [README](../README.md); design tokens in
[frontend/DESIGN.md](../frontend/DESIGN.md). Real secrets belong in `.env` /
`local_credentials.txt` (both gitignored) — never in this file.

---

## 1. Start / Stop

```powershell
# Host Ollama first (auto-starts on login normally)
ollama list                                    # sanity: models present

docker compose up -d                           # lean stack (6 containers)
docker compose --profile observability up -d   # + Prometheus/Grafana/Langfuse
docker compose --profile airflow up -d         # + scheduled DAGs
docker compose down                            # stop (add --remove-orphans after profile changes)
```

**Required host environment variables** (User scope — set once):

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Newer Ollama defaults to the model's full 131K context → 14GB KV cache → OOM crash |
| `OLLAMA_KEEP_ALIVE` | `30m` | Avoid model reload between pipeline steps |
| `OLLAMA_VULKAN` | `0` | The Vulkan backend crashes llama-server on AMD iGPUs (NTSTATUS 0xe06d7363) |

`C:\Users\<you>\.wslconfig` caps Docker's VM (`[wsl2]` → `memory=7GB`) so the host LLM keeps enough RAM.

## 2. Service Directory

| Service | URL | Notes |
|---|---|---|
| **Corpus app** | http://localhost:7860 | The React UI (nginx) |
| API + OpenAPI docs | http://localhost:8000/docs | FastAPI |
| Grafana | http://localhost:3002 | profile: observability |
| Prometheus | http://localhost:9092 | profile: observability |
| Langfuse | http://localhost:3001 | profile: observability |
| OpenSearch Dashboards | http://localhost:5601 | profile: observability |
| Airflow | http://localhost:8080 | profile: airflow |
| OpenSearch | http://localhost:9200 | direct index access |

Login credentials for Grafana/Langfuse/Airflow: see `local_credentials.txt` (gitignored).

## 3. Routine Operations

| Task | How |
|---|---|
| Ingest recent arXiv papers | `docker exec corpus-api python -m src.run_ingest` (or the daily Airflow DAG) |
| Ingest one specific paper | UI → Library → Upload, or `POST /api/v1/papers/{arxiv_id}/ingest` |
| Re-embed / rebuild search index | `uv run python -m src.run_reindex` (**required after changing `EMBEDDING__BACKEND`**; flushes semantic cache) |
| Manual backup | `docker exec corpus-backup sh -c 'pg_dump -h postgres -U rag_user -Fc corpus_db > /backups/manual.dump'` (nightly is automatic → `./backups/`) |
| **Disaster restore** | `.\scripts\restore.ps1` — drops DB, restores latest dump, rebuilds the index |
| Golden-set evaluation | System page → Run evaluation, or `POST /api/v1/eval/run?mode=golden&limit=10` |
| Train reranker on feedback | `uv run python scripts/train_reranker.py` (needs ≥50 rated answers), then set `RERANKER__MODEL=models/reranker-tuned` and recreate api |
| Concept graph rebuild | Airflow DAG `concept_graph_builder` (nightly when airflow profile is up) |

**Config changes:** `docker restart` does **not** re-read `.env` — use
`docker compose up -d --force-recreate api arq-worker`.

## 4. Health & Monitoring

- `GET /api/v1/health` — per-service connectivity + latency (Postgres, OpenSearch, Redis, Ollama)
- `GET /api/v1/health/canary` — hourly synthetic probe that *actually* runs retrieval and a 1-token generation; `"status": "failing"` means users are impacted even if /health looks green
- `GET :8000/metrics` — Prometheus (request latency, pipeline stage timings, cache hit rate, router decisions, guardrail flags, LLM tokens)
- Answer-quality trend: System page (faithfulness, relevancy, hit@k/MRR across eval runs)

## 5. Validation After Changes

```powershell
uv run pytest tests/unit tests/integration tests/eval     # 19 backend tests
cd frontend; npx playwright test                           # browser E2E (mock API, ports 8001/5174)
# Real-stack smoke: ask a question at :7860 — expect live tokens, citations with page numbers,
# repeat the same question — expect the ⚡ cached badge.
```

## 6. Troubleshooting

| Symptom | Cause → Fix |
|---|---|
| Every model errors `NTSTATUS 0xe06d7363` | Ollama Vulkan on AMD iGPU → set `OLLAMA_VULKAN=0` (user env) and restart Ollama |
| Model OOM at load, huge KV cache in `%LOCALAPPDATA%\Ollama\server.log` | Unset context cap → `OLLAMA_CONTEXT_LENGTH=8192` |
| Answers show "generation unavailable — showing passages" | Extractive fallback fired: Ollama is down/OOM. Retrieval still works; restart Ollama, close RAM-heavy apps |
| Vector search returns nothing after switching embedding backend | Query/index embedding mismatch → run `src.run_reindex` |
| `.env` change has no effect | Containers keep creation-time env → `docker compose up -d --force-recreate <svc>` |
| Docker builds fail with DNS errors | WSL2 DNS flake → `wsl --shutdown`, restart Docker Desktop, rebuild |
| 413 on PDF upload | nginx body limit — already set to 210m in `frontend/nginx.conf`; rebuild frontend image if reverted |
| Streaming appears all-at-once through :7860 | nginx buffering — `proxy_buffering off` must be present in the `/api/` location |
| Zotero import: connection refused | Zotero desktop app must be running (its local API listens on 23119) |
| `tests/unit/test_parser.py` fails locally with a blocked DLL | Windows Smart App Control blocking scipy in the venv — environment issue, not code; excluded from local runs |

## 7. Performance Tuning (CPU-only machines)

| Knob (.env) | Effect |
|---|---|
| `LITELLM__*_MODEL` | Biggest lever — upgrade to `llama3.2:3b`+ when ≥16GB free RAM |
| `MODEL_AUTOSELECT=true` | Startup probe picks the best loadable model automatically |
| `GRADING_MAX_CHUNKS` (8) | Each graded chunk = one LLM call |
| `GENERATION_MAX_TOKENS` (1024) | Caps answer length / generation time |
| `ENABLE_LLM_VERIFICATION=false` | Deep verify only on demand via the UI shield toggle |
| `SEMANTIC_CACHE_ENABLED=true` | Near-duplicate questions answered instantly |
| Observability profile stopped | Frees ~4-6GB RAM for the LLM |
