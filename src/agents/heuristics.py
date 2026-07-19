"""Corpus — Heuristic query router.

Skips the 15-20s LLM routing call for queries whose type is obvious from
surface features. Conservative by design: the only dangerous misroute is
casual (it swallows a real question), so casual matches are anchored
full-string patterns only. Anything filter-shaped falls through to the LLM
router, which also extracts metadata filters.
"""

from __future__ import annotations

import re

_CASUAL_RE = re.compile(
    r"^(hi|hello|hey|yo|thanks?( you)?|thank you|good (morning|afternoon|evening)"
    r"|bye|goodbye|ok(ay)?|cool|nice|great)[\s!.]*$",
    re.IGNORECASE,
)

_COMPLEX_RE = re.compile(
    r"\bcompare\b|\bvs\.?\b|\bversus\b|difference between|trade-?offs?",
    re.IGNORECASE,
)

_FOLLOWUP_START_RE = re.compile(r"^(what about|and |how about|why |so )", re.IGNORECASE)
_ANAPHOR_RE = re.compile(r"\b(it|its|they|their|that|this one)\b", re.IGNORECASE)

_SIMPLE_START_RE = re.compile(r"^(what|who|when|where|which|how)\b", re.IGNORECASE)
# Filter-shaped tokens (years, author markers, category codes) need the LLM's extraction
_FILTERISH_RE = re.compile(r"\b(19|20)\d{2}\b|\bby [A-Z]|cs\.[A-Z]{2}")


_GRAPH_PATTERNS = [
    re.compile(r"\bevolution of ([\w\s-]{3,50})", re.IGNORECASE),
    re.compile(r"\btrends? (?:in|of) ([\w\s-]{3,50})", re.IGNORECASE),
    re.compile(r"\bwhich papers (?:use|evaluate|compare|apply) ([\w\s-]{3,50})", re.IGNORECASE),
    re.compile(r"\bpapers (?:about|on|using) ([\w\s-]{3,50}?) over time", re.IGNORECASE),
]


def graph_concept(query: str) -> str | None:
    """Detect concept-graph-shaped queries; return the concept term or None."""
    for pattern in _GRAPH_PATTERNS:
        m = pattern.search(query)
        if m:
            return m.group(1).strip().rstrip("?.!,")
    return None


def heuristic_route(query: str, has_history: bool) -> str | None:
    """Classify a query without an LLM call. Returns None when unsure."""
    q = query.strip()
    words = q.split()

    if len(words) <= 4 and "?" not in q and _CASUAL_RE.match(q):
        return "casual"

    if _COMPLEX_RE.search(q) or q.count("?") >= 2:
        return "complex"

    if has_history and (_FOLLOWUP_START_RE.match(q) or (len(words) < 8 and _ANAPHOR_RE.search(q))):
        return "followup"

    if len(words) < 12 and _SIMPLE_START_RE.match(q) and not _FILTERISH_RE.search(q):
        return "simple"

    return None
