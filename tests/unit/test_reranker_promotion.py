"""Corpus — reranker auto-promotion pointer resolution tests."""

from __future__ import annotations

from types import SimpleNamespace

from src.retrieval import reranker


def _settings(model: str, auto_promote: bool):
    return SimpleNamespace(reranker=SimpleNamespace(model=model, auto_promote=auto_promote))


def test_uses_base_model_when_no_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(reranker, "RERANKER_ACTIVE_POINTER", tmp_path / "reranker-active.txt")
    assert reranker.resolve_reranker_model(_settings("base-model", True)) == "base-model"


def test_uses_promoted_model_when_pointer_valid(tmp_path, monkeypatch):
    tuned = tmp_path / "reranker-tuned"
    tuned.mkdir()
    pointer = tmp_path / "reranker-active.txt"
    pointer.write_text(str(tuned), encoding="utf-8")
    monkeypatch.setattr(reranker, "RERANKER_ACTIVE_POINTER", pointer)

    assert reranker.resolve_reranker_model(_settings("base-model", True)) == str(tuned)


def test_ignores_pointer_when_auto_promote_disabled(tmp_path, monkeypatch):
    tuned = tmp_path / "reranker-tuned"
    tuned.mkdir()
    pointer = tmp_path / "reranker-active.txt"
    pointer.write_text(str(tuned), encoding="utf-8")
    monkeypatch.setattr(reranker, "RERANKER_ACTIVE_POINTER", pointer)

    assert reranker.resolve_reranker_model(_settings("base-model", False)) == "base-model"


def test_falls_back_when_pointer_path_is_stale(tmp_path, monkeypatch):
    """A pointer to a deleted model directory must fall back to base, not crash."""
    pointer = tmp_path / "reranker-active.txt"
    pointer.write_text(str(tmp_path / "gone"), encoding="utf-8")
    monkeypatch.setattr(reranker, "RERANKER_ACTIVE_POINTER", pointer)

    assert reranker.resolve_reranker_model(_settings("base-model", True)) == "base-model"
