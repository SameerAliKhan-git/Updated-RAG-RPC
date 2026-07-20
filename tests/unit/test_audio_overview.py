"""Corpus — Audio Overview (Piper TTS) Unit Tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.audio_overview import generate_audio_overview, get_audio_status


@pytest.mark.asyncio
async def test_get_audio_status_not_generated_when_no_redis_key():
    redis = AsyncMock()
    redis.get.return_value = None
    with patch("src.services.audio_overview.AUDIO_DIR") as mock_dir:
        (mock_dir / "col1.wav").exists.return_value = False
        status = await get_audio_status(redis, "col1")
    assert status["status"] == "not_generated"


@pytest.mark.asyncio
async def test_generate_audio_overview_fails_fast_when_collection_missing():
    """An unknown collection_id must not attempt script generation or synthesis."""
    app_state = MagicMock()
    app_state.redis = AsyncMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    app_state.db_session_factory.return_value = db

    await generate_audio_overview("missing-collection", app_state)

    statuses = [json.loads(c[0][1])["status"] for c in app_state.redis.set.call_args_list]
    assert statuses[-1] == "failed"
    detail = json.loads(app_state.redis.set.call_args_list[-1][0][1])["detail"]
    assert "not found" in detail
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_generate_audio_overview_fails_when_collection_has_no_papers():
    app_state = MagicMock()
    app_state.redis = AsyncMock()
    db = MagicMock()
    collection = MagicMock(name="collection")
    collection.name = "Empty Collection"
    db.query.return_value.filter.return_value.first.return_value = collection
    db.query.return_value.join.return_value.filter.return_value.limit.return_value.all.return_value = []
    app_state.db_session_factory.return_value = db

    await generate_audio_overview("empty-collection", app_state)

    last_status = json.loads(app_state.redis.set.call_args_list[-1][0][1])
    assert last_status["status"] == "failed"
    assert "no papers" in last_status["detail"]


@pytest.mark.asyncio
async def test_generate_audio_overview_fails_when_script_llm_errors():
    """call_fast_llm returning the "[LLM Error" sentinel (Ollama down) must be treated
    as a failure, not silently narrated as if it were a real script."""
    app_state = MagicMock()
    app_state.redis = AsyncMock()
    db = MagicMock()
    collection = MagicMock()
    collection.name = "Attention Papers"
    paper = MagicMock(title="Attention Is All You Need", authors=["Vaswani"], abstract="We propose...")
    db.query.return_value.filter.return_value.first.return_value = collection
    db.query.return_value.join.return_value.filter.return_value.limit.return_value.all.return_value = [paper]
    app_state.db_session_factory.return_value = db

    with patch("src.services.audio_overview.call_fast_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "[LLM Error: connection refused]"
        await generate_audio_overview("col-with-papers", app_state)

    last_status = json.loads(app_state.redis.set.call_args_list[-1][0][1])
    assert last_status["status"] == "failed"
    assert "Ollama" in last_status["detail"]


@pytest.mark.asyncio
async def test_generate_audio_overview_happy_path_synthesizes_and_marks_done():
    """Full success path: script written, Piper synthesizes, status ends at done.
    Piper and the HF voice download are mocked — no real model or audio I/O."""
    app_state = MagicMock()
    app_state.redis = AsyncMock()
    db = MagicMock()
    collection = MagicMock()
    collection.name = "Attention Papers"
    paper = MagicMock(title="Attention Is All You Need", authors=["Vaswani"], abstract="We propose a new architecture.")
    db.query.return_value.filter.return_value.first.return_value = collection
    db.query.return_value.join.return_value.filter.return_value.limit.return_value.all.return_value = [paper]
    app_state.db_session_factory.return_value = db

    fake_voice = MagicMock()

    with (
        patch("src.services.audio_overview.call_fast_llm", new_callable=AsyncMock) as mock_llm,
        patch("src.services.audio_overview._voice_model_path", return_value="fake-voice.onnx"),
        patch("piper.PiperVoice") as mock_piper_cls,
        patch("wave.open") as mock_wave_open,
        patch("src.services.audio_overview.AUDIO_DIR") as mock_audio_dir,
    ):
        mock_llm.return_value = "A friendly overview of attention mechanisms in transformers."
        mock_piper_cls.load.return_value = fake_voice
        mock_wave_open.return_value.__enter__.return_value = MagicMock()
        mock_audio_dir.__truediv__.return_value = "fake-path.wav"

        await generate_audio_overview("col-with-papers", app_state)

    statuses = [json.loads(c[0][1])["status"] for c in app_state.redis.set.call_args_list]
    assert statuses[-1] == "done"
    assert "writing_script" in statuses
    assert "synthesizing" in statuses
