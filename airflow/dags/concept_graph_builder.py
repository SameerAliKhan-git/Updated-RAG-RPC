"""Corpus — Nightly concept-graph builder.

Extracts research concepts (methods/datasets/tasks/metrics) and their
relations from papers that haven't been processed yet, one fast-LLM call
per paper. Checkpointed via papers.concepts_extracted_at, so restarts and
partial runs are safe.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow")


def build_graph():
    import asyncio

    from src.services.concept_extractor import build_concept_graph

    stats = asyncio.run(build_concept_graph(limit=50))
    print(f"Concept graph build: {stats}")
    if stats["errors"] and not stats["papers"]:
        raise RuntimeError(f"All extractions failed: {stats}")


default_args = {
    "owner": "corpus",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="concept_graph_builder",
    description="Nightly extraction of the research concept graph",
    schedule="0 3 * * *",  # 3AM UTC, after ingestion and before eval
    start_date=datetime(2026, 7, 1),
    catchup=False,
    default_args=default_args,
    tags=["corpus", "graph"],
) as dag:
    PythonOperator(
        task_id="build_concept_graph",
        python_callable=build_graph,
    )
