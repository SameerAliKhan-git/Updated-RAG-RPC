"""Corpus — Nightly golden-set evaluation.

Calls the API's eval endpoint in golden mode so answers are produced by the
same warm pipeline users hit. Scores land in Redis (`corpus:eval:history`)
and surface on the System page's trend chart.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow")

API_BASE = "http://api:8000/api/v1"


def trigger_golden_eval():
    """Kick off the golden evaluation on the API and wait for completion."""
    import time

    import httpx

    resp = httpx.post(f"{API_BASE}/eval/run", params={"mode": "golden", "limit": 10}, timeout=30)
    resp.raise_for_status()
    print(f"Triggered: {resp.json()}")

    # Poll status — golden mode runs the full pipeline per question on CPU (slow).
    deadline = time.time() + 3 * 3600
    while time.time() < deadline:
        status = httpx.get(f"{API_BASE}/eval/status", timeout=30).json()
        state = status.get("status")
        print(f"eval status: {state}")
        if state == "COMPLETED":
            print(f"scores: {status.get('scores')}")
            return
        if state == "FAILED":
            raise RuntimeError(f"Golden eval failed: {status}")
        time.sleep(120)

    raise TimeoutError("Golden eval did not complete within 3 hours.")


default_args = {
    "owner": "corpus",
    "depends_on_past": False,
    "start_date": datetime(2026, 1, 1),
    "email_on_failure": False,
    "retries": 0,
}

with DAG(
    "nightly_golden_eval",
    default_args=default_args,
    description="Nightly RAGAS evaluation of the golden question set against the live pipeline.",
    schedule="0 2 * * *",  # 2:00 AM UTC daily
    catchup=False,
    max_active_runs=1,
    tags=["corpus", "evaluation", "ragas"],
) as dag:
    run_eval = PythonOperator(
        task_id="run_golden_eval",
        python_callable=trigger_golden_eval,
    )
