# Corpus — Start-to-Finish Startup Guide

How to get Corpus running, from a cold machine to a working app at
<http://localhost:7860>. For day-2 operations (backups, restore, reindex,
troubleshooting) see [OPERATIONS.md](OPERATIONS.md); for architecture see the
[README](../README.md).

---

## TL;DR — the daily ritual

Once the one-time setup is done, starting the project is three things:

```powershell
# 1. Docker Desktop must be running (start it from the Start menu, wait for
#    the whale icon to stop animating)

# 2. Ollama must be serving on the host
ollama list                      # any output = it's up

# 3. Start the stack
cd "C:\Users\prane\OneDrive\Desktop\Production Grade RAG Project\Updated Project"
docker compose up -d
```

Then open **<http://localhost:7860>**. First start takes ~60–90s while the API
loads the embedding + reranker models; the page will error until then.

---

## Part 1 — What must be installed (one time only)

| # | Software | Why it's needed | Check it's installed |
|---|---|---|---|
| 1 | **Docker Desktop** | Runs every service except Ollama | `docker --version` |
| 2 | **Ollama** (native install, *not* a container) | Serves the LLM + embeddings | `ollama --version` |
| 3 | **Python 3.12 + uv** | Running tests, reindex, training scripts | `uv --version` |
| 4 | **Node 20+** | Only for frontend dev / E2E tests | `node --version` |

You do **not** need Node or Python just to *run* the app — Docker builds handle
that. They're needed for the maintenance commands in OPERATIONS.md.

### Why Ollama is not in Docker

There is deliberately **no `ollama` service in `docker-compose.yml`**. Ollama runs
natively on the host so it can use host RAM directly and survive container
restarts with models still warm. Containers reach it at
`http://host.docker.internal:11434`.

---

## Part 2 — One-time setup (first run ever)

### 2.1 Pull the models (~3 GB, once)

```powershell
ollama pull llama3.2:1b     # the LLM
ollama pull bge-m3          # embeddings, 1024-dim
```

### 2.2 Set the host environment variables

These are **required on this machine** — without them Ollama crashes or OOMs.
Set them as **User** environment variables (Start → "Edit environment variables
for your account"), then **sign out and back in**, or restart Ollama.

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Newer Ollama defaults to the model's full 131K context → ~14 GB KV cache → OOM crash |
| `OLLAMA_KEEP_ALIVE` | `30m` | Keeps the model loaded between pipeline steps instead of reloading each call |
| `OLLAMA_VULKAN` | `0` | The Vulkan backend crashes llama-server on AMD iGPUs (`NTSTATUS 0xe06d7363`) |

Verify they took effect:

```powershell
$env:OLLAMA_CONTEXT_LENGTH; $env:OLLAMA_VULKAN; $env:OLLAMA_KEEP_ALIVE
```

### 2.3 Cap the Docker VM's memory

Create/edit `C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
memory=7GB
```

This leaves enough host RAM for Ollama on a 15 GB machine. Apply with
`wsl --shutdown`, then restart Docker Desktop.

### 2.4 Create your `.env`

```powershell
copy .env.example .env
```

The defaults work as-is for local development. The values that matter most:

| Key | Local default | Notes |
|---|---|---|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Host-native Ollama, reached from containers |
| `EMBEDDING__BACKEND` | `ollama` | Uses bge-m3 via Ollama. **Changing this requires a full reindex** |
| `DEBUG` / `ENVIRONMENT` | `true` / `development` | Auth is skipped in this mode. See "Production mode" below |
| `LITELLM__*_MODEL` | `ollama/llama3.2:1b` | One line per role — upgrade here when you have RAM |
| `MODEL_AUTOSELECT` | `true` | Probes and picks the best model that will actually load |

### 2.5 Build and start

```powershell
docker compose up -d --build
```

First build takes 10–20 minutes (Docling + ML dependencies). Later starts are seconds.

### 2.6 Get some papers in

The corpus is empty on a fresh install — ingest before asking anything:

```powershell
docker exec corpus-api python -m src.run_ingest
```

Or upload a PDF through the UI: **Library → Upload PDF**.

---

## Part 3 — What's actually running

`docker compose up -d` starts the **lean stack — 7 containers**:

| Service | Container | Port | Role |
|---|---|---|---|
| **frontend** | `corpus-frontend` | **7860** | The app you open (nginx + React build) |
| **api** | `corpus-api` | 8000 | FastAPI — the agentic pipeline |
| **postgres** | `corpus-postgres` | 5432 | Source of truth: papers, chunks, collections, sessions |
| **opensearch** | `corpus-opensearch` | 9200, 9600 | Hybrid BM25 + KNN search index |
| **redis** | `corpus-redis` | 6379 | Session memory, semantic cache, rate limits, job queue |
| **arq-worker** | `corpus-arq-worker` | — | Background ingestion jobs |
| **backup** | `corpus-backup` | — | Nightly `pg_dump` into `./backups/` |

Plus **Ollama on the host** at port 11434 — not a container, but the stack does
not work without it.

**Startup order is automatic.** The API waits for Postgres, OpenSearch, and Redis
to report *healthy*; the frontend waits for the API. You do not need to start
anything in a particular order.

### Optional profiles (off by default)

```powershell
docker compose --profile observability up -d   # Prometheus, Grafana, Langfuse, OpenSearch Dashboards
docker compose --profile airflow up -d         # scheduled DAGs (ingestion, eval, concept graph, training)
docker compose --profile telegram up -d        # Telegram bot
```

| URL | What |
|---|---|
| <http://localhost:3002> | Grafana (observability) |
| <http://localhost:9092> | Prometheus (observability) |
| <http://localhost:3001> | Langfuse tracing (observability) |
| <http://localhost:5601> | OpenSearch Dashboards (observability) |
| <http://localhost:8080> | Airflow (airflow) |

Credentials for these: `local_credentials.txt` (gitignored).

⚠️ The observability profile costs ~4–6 GB RAM. On this machine, leave it off
unless you're actively debugging — it competes with Ollama for memory.

**The Research Galaxy stays empty until the `airflow` profile has run the nightly
concept-graph DAG at least once**, or you click "Build now" on the Galaxy page.

---

## Part 4 — Verify it's actually working

```powershell
# 1. All containers up and healthy
docker compose ps

# 2. Every dependency reachable (Postgres, OpenSearch, Redis, Ollama)
curl http://localhost:8000/api/v1/health

# 3. Does retrieval + generation genuinely work right now?
curl http://localhost:8000/api/v1/health/canary

# 4. Any background ingestion jobs failed?
curl http://localhost:8000/api/v1/health/dead-letter
```

Then the real end-to-end check: open <http://localhost:7860>, ask a question, and
confirm you get **live streaming tokens**, **inline `[N]` citations**, and that
**clicking a citation opens the PDF at the cited page** with the passage
highlighted. Ask the same question again — it should return instantly with a ⚡
cached badge.

---

## Part 5 — Shutting down

```powershell
docker compose down                    # stop the stack, keep all data
docker compose down --remove-orphans   # after turning a profile off
```

Your data lives in Docker **named volumes** and survives `down` — papers, chunks,
sessions, and the search index are all still there next time. Ollama keeps
running in the background on the host; quit it from the system tray if you want
the RAM back.

**Never use `docker compose down -v`** unless you intend to erase the entire
corpus — `-v` deletes the volumes, which means re-ingesting and re-embedding
everything from scratch.

---

## Part 6 — Running in production mode

Local development runs with auth disabled (`DEBUG=true`,
`ENVIRONMENT=development`). To run it for real:

1. Set `ENVIRONMENT=production` and a strong random `API_KEY` in `.env`.
   The API **refuses to start** with a missing or placeholder key outside
   development — that's intentional.
2. Recreate the containers so they pick up the new values:

   ```powershell
   docker compose up -d --force-recreate api arq-worker frontend
   ```

The web UI keeps working: nginx injects the key as `X-API-Key` when proxying, so
it never ships in the browser bundle. External clients (curl, the Telegram bot)
must send the header themselves.

> **`docker restart` does NOT re-read `.env`.** Containers keep their
> creation-time environment. Always use `docker compose up -d --force-recreate`
> after editing `.env`.

---

## Part 7 — If something's wrong

Quick triage:

```powershell
docker compose ps                  # who's down or unhealthy?
docker compose logs -f api         # follow API logs
docker compose logs --tail=100 arq-worker
```

| Symptom | Most likely cause |
|---|---|
| Page won't load at :7860 | API still booting (models load for ~60–90s) — check `docker compose logs api` |
| "generation unavailable — showing passages" | Ollama is down or OOM. Run `ollama list`; close RAM-heavy apps |
| Answers have no sources | Corpus is empty — run the ingest command in §2.6 |
| `.env` change did nothing | Use `--force-recreate`, not `docker restart` |
| Galaxy page is blank | Concept graph not built yet — click "Build now", or enable the airflow profile |

The full troubleshooting table — including the Ollama crash codes, embedding
backend mismatches, WSL DNS failures, and PDF upload limits — is in
**[OPERATIONS.md §6](OPERATIONS.md#6-troubleshooting)**. Don't duplicate fixes
here; that table is the single source of truth.
