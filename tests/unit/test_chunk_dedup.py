"""Corpus — retrieval chunk-dedup unit tests."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents.rag_graph import _dedup_chunks


def _chunk(text: str):
    return SimpleNamespace(text=text)


def test_dedup_drops_near_identical_passages():
    a = _chunk("state space models scale linearly with sequence length unlike transformers")
    b = _chunk("state space models scale linearly with sequence length unlike transformers today")
    c = _chunk("reciprocal rank fusion merges ranked lists by summing reciprocal ranks")
    result = _dedup_chunks([a, b, c])
    # a and b are near-identical — only the first is kept; c is distinct.
    assert a in result
    assert b not in result
    assert c in result


def test_dedup_keeps_all_when_distinct():
    a = _chunk("attention weighs tokens by query-key similarity")
    b = _chunk("convolution applies a sliding kernel over local windows")
    result = _dedup_chunks([a, b])
    assert len(result) == 2


def test_dedup_preserves_order_and_keeps_first():
    a = _chunk("identical passage about mamba selective state spaces")
    b = _chunk("identical passage about mamba selective state spaces")
    result = _dedup_chunks([a, b])
    assert result == [a]


def test_dedup_handles_empty_text_without_dropping():
    a = _chunk("")
    b = _chunk("")
    result = _dedup_chunks([a, b])
    # Empty-text chunks aren't treated as duplicates of each other.
    assert len(result) == 2
