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
ACTIVE_POINTER = Path("models/reranker-active.txt")
# Tuned must beat base AUC by at least this margin on held-out pairs to promote.
PROMOTION_MARGIN = 0.02


def _rank_auc(scores: list[float], labels: list[float]) -> float:
    """ROC-AUC via the Mann-Whitney rank statistic (no sklearn dependency).

    Fraction of (positive, negative) pairs the model ranks correctly; 0.5 is
    random. Returns 0.5 when either class is absent (uninformative eval)."""
    pos = [s for s, y in zip(scores, labels, strict=True) if y >= 0.5]
    neg = [s for s, y in zip(scores, labels, strict=True) if y < 0.5]
    if not pos or not neg:
        return 0.5
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def _score_pairs(model, pairs: list[tuple[str, str, float]]) -> list[float]:
    return [float(s) for s in model.predict([(q, p) for q, p, _ in pairs], batch_size=8)]


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

    import random

    from sentence_transformers import CrossEncoder, InputExample
    from torch.utils.data import DataLoader

    # Hold out 20% for an eval gate so we only promote a model that actually helps.
    random.Random(42).shuffle(pairs)
    split = max(1, int(len(pairs) * 0.2))
    eval_pairs, train_pairs = pairs[:split], pairs[split:]

    examples = [InputExample(texts=[q, p], label=label) for q, p, label in train_pairs]
    base = CrossEncoder(args.base_model, num_labels=1, max_length=512)
    base_auc = _rank_auc(_score_pairs(base, eval_pairs), [label for *_, label in eval_pairs])

    model = CrossEncoder(args.base_model, num_labels=1, max_length=512)
    loader = DataLoader(examples, shuffle=True, batch_size=8)
    logger.info(f"Fine-tuning {args.base_model} for {args.epochs} epoch(s) on {len(train_pairs)} pairs (CPU)...")
    model.fit(train_dataloader=loader, epochs=args.epochs, warmup_steps=min(50, len(examples) // 4))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(OUTPUT_DIR))

    tuned_auc = _rank_auc(_score_pairs(model, eval_pairs), [label for *_, label in eval_pairs])
    logger.info(f"Eval-gate AUC on {len(eval_pairs)} held-out pairs — base={base_auc:.3f} tuned={tuned_auc:.3f}")

    if tuned_auc >= base_auc + PROMOTION_MARGIN:
        ACTIVE_POINTER.write_text(str(OUTPUT_DIR), encoding="utf-8")
        logger.info(
            f"✓ Promoted: tuned model beat base by >= {PROMOTION_MARGIN}. Wrote {ACTIVE_POINTER}. "
            "Recreate the api/arq-worker containers to load it."
        )
    else:
        logger.info(
            f"✗ Not promoted: tuned did not beat base by {PROMOTION_MARGIN}. "
            f"Model saved to {OUTPUT_DIR} but the active pointer is unchanged."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
