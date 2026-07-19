"""Corpus — feedback-trained reranker fine-tuning.

The quality flywheel: thumbs-up sessions provide positive (query, passage)
pairs, thumbs-down sessions negatives. Fine-tunes the MiniLM cross-encoder
and writes it to models/reranker-tuned/; set RERANKER__MODEL to that path
to activate. Run monthly (or via the Airflow 'reranker_trainer' DAG) once
you have ≥50 feedback entries — below that, training is skipped.

Usage:
    uv run python scripts/train_reranker.py [--min-samples 50] [--epochs 1]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_reranker")

OUTPUT_DIR = Path("models/reranker-tuned")


def collect_training_pairs(db) -> list[tuple[str, str, float]]:
    """(query, passage, label) triples from feedback joined with session messages."""
    from src.models.paper import ChatMessage, Feedback

    pairs: list[tuple[str, str, float]] = []
    for fb in db.query(Feedback).all():
        label = 1.0 if fb.rating == "up" else 0.0
        # query_id is the session id; find the last user question + cited snippets
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == str(fb.query_id))
            .order_by(ChatMessage.created_at.desc())
            .limit(4)
            .all()
        )
        query = next((m.content for m in messages if m.role == "user"), None)
        assistant = next((m for m in messages if m.role == "assistant"), None)
        if not query or assistant is None:
            continue
        citations = assistant.citations or []
        if isinstance(citations, str):
            citations = json.loads(citations)
        for cite in citations[:4]:
            snippet = (cite.get("snippet") or "").strip()
            if len(snippet) > 40:
                pairs.append((query, snippet, label))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-samples", type=int, default=50)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--base-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    args = parser.parse_args()

    from src.config import get_settings
    from src.db.postgres import create_engine_and_session

    engine, session_factory = create_engine_and_session(get_settings().postgres.database_url)
    db = session_factory()
    try:
        pairs = collect_training_pairs(db)
    finally:
        db.close()
        engine.dispose()

    logger.info(f"Collected {len(pairs)} training pairs from feedback.")
    if len(pairs) < args.min_samples:
        logger.info(
            f"Not enough feedback yet ({len(pairs)} < {args.min_samples}) — skipping training. "
            "Keep using the app and rating answers."
        )
        return 0

    from sentence_transformers import CrossEncoder, InputExample
    from torch.utils.data import DataLoader

    examples = [InputExample(texts=[q, p], label=label) for q, p, label in pairs]
    model = CrossEncoder(args.base_model, num_labels=1, max_length=512)
    loader = DataLoader(examples, shuffle=True, batch_size=8)

    logger.info(f"Fine-tuning {args.base_model} for {args.epochs} epoch(s) on CPU...")
    model.fit(train_dataloader=loader, epochs=args.epochs, warmup_steps=min(50, len(examples) // 4))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(OUTPUT_DIR))
    logger.info(
        f"✓ Saved tuned reranker to {OUTPUT_DIR}. Activate with RERANKER__MODEL={OUTPUT_DIR} "
        "and recreate the api container."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
