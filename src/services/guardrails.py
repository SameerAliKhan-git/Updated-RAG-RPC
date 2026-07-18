"""Corpus — Input guardrails.

Lightweight, fully-local input sanitation: length caps, control-character
stripping, and prompt-injection heuristics. Suspicious queries are tagged
(not blocked) — the prompts wrap user input in <user_query> delimiters and
instruct the model to treat it as data, so tagging exists for logging and
metrics, not censorship.
"""

from __future__ import annotations

import logging
import re

from src.config import get_settings

logger = logging.getLogger(__name__)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions", re.compile(r"\bignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions?\b", re.I)),
    ("disregard_instructions", re.compile(r"\bdisregard\s+(all\s+|any\s+)?(previous|prior|above|your)\b", re.I)),
    ("role_override", re.compile(r"\byou\s+are\s+now\s+(a|an|the)\b", re.I)),
    ("system_prompt_probe", re.compile(r"\b(reveal|show|print|repeat)\b.{0,40}\bsystem\s+prompt\b", re.I)),
    ("new_instructions", re.compile(r"\b(new|updated)\s+instructions?\s*:", re.I)),
    ("base64_blob", re.compile(r"[A-Za-z0-9+/=]{200,}")),
]


def sanitize_query(query: str) -> tuple[str, list[str]]:
    """Sanitize a user query.

    Returns (cleaned_query, flags) where flags names any triggered heuristics.
    """
    settings = get_settings()
    flags: list[str] = []

    cleaned = _CONTROL_CHARS_RE.sub("", query).strip()

    max_chars = settings.guardrails_max_query_chars
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
        flags.append("truncated")

    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            flags.append(name)

    if flags:
        logger.warning(f"Guardrails flagged query ({', '.join(flags)}): {cleaned[:120]!r}")
        try:
            from src.middleware.metrics import GUARDRAIL_FLAGS

            for flag in flags:
                GUARDRAIL_FLAGS.labels(flag=flag).inc()
        except Exception:  # noqa: BLE001 — metrics must never break the request path
            pass

    return cleaned, flags
