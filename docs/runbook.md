# Corpus — Operations Runbook

This runbook describes standard operational procedures, health checks, metrics, and troubleshooting guides for the Corpus Agentic RAG curator.

---

## 1. Quick Service Control

To start all services locally:
```bash
make start
```

To stop all services:
```bash
make stop
```

To view logs:
```bash
make logs
```

---

## 2. Infrastructure Service Ports

| Service | Port | Internal Name | Purpose |
|---|---|---|---|
| API Service | `8000` | `api` | Backend REST API & SSE streams |
| Gradio Web UI | `7860` | `gradio` | Main chat web client (zero.xyz theme) |
| Apache Airflow | `8080` | `airflow` | Scheduled batch ingestion DAGs |
| Langfuse Web | `3001` | `langfuse-web` | Trace-level RAG observability |
| Prometheus | `9092` | `prometheus` | Scraping engine for service metrics |
| Grafana | `3002` | `grafana` | Performance monitoring dashboard |
| PostgreSQL | `5432` | `postgres` | Metadata System of Record (SoR) |
| OpenSearch | `9200` | `opensearch` | Dense & sparse hybrid index |
| Redis | `6379` | `redis` | Session, cache, and rate-limiting store |

---

## 3. Health Verification Procedures

### Endpoint Check
Hit the API health checker:
```bash
make health
```
Expected output:
```json
{
    "status": "healthy",
    "version": "0.1.0",
    "environment": "development",
    "services": [
        {"name": "postgres", "status": "healthy", "latency_ms": 1.2},
        {"name": "opensearch", "status": "healthy", "latency_ms": 5.4},
        {"name": "redis", "status": "healthy", "latency_ms": 0.8},
        {"name": "ollama", "status": "healthy", "latency_ms": 12.0}
    ]
}
```

---

## 4. Troubleshooting Guide

### Issue: Rate Limit Exceeded (HTTP 429)
- **Symptom**: User receives `HTTP 429 Too Many Requests`.
- **Cause**: Client hit the 30 RPM limit tracked in Redis.
- **Action**: Check if the client is spamming requests. In dev mode, set `DEBUG=true` in `.env` to bypass limits.

### Issue: Hallucinated / Missing Citations
- **Symptom**: Generated answers contain references to source numbers (e.g., `[5]`) not returned in metadata.
- **Remedy**: The `verify_citations` node intercepts and strips hallucinated citations. If they still slip through, check the `VERIFIER_PROMPT` in `src/agents/prompts.py` and increase LLM reasoning models' capabilities (e.g., route to a stronger model using `LITELLM__REASONING_MODEL`).

### Issue: OpenSearch Index Connection Errors
- **Symptom**: Search fails or falls back to pure BM25.
- **Remedy**: Verify OpenSearch container is up and check index mappings:
  ```bash
  curl -XGET http://localhost:9200/corpus-chunks/_mapping
  ```
  If index mappings are corrupt, run the environment setup task in Airflow DAG to rebuild.
