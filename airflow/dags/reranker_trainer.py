"""Corpus — monthly reranker fine-tuning from user feedback (quality flywheel)."""

from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="reranker_trainer",
    description="Fine-tune the cross-encoder reranker on accumulated thumbs feedback",
    schedule_interval="0 4 1 * *",  # 04:00 UTC on the 1st of each month
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=["corpus", "training"],
) as dag:
    train = BashOperator(
        task_id="train_reranker",
        bash_command="cd /opt/corpus && python scripts/train_reranker.py --min-samples 50",
    )
