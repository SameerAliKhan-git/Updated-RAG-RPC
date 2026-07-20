"""Corpus — Deep Research Job Unit Tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.deep_research import _assemble, get_research, new_research_id, run_deep_research


def test_new_research_id_is_short_and_unique():
    a, b = new_research_id(), new_research_id()
    assert a != b
    assert len(a) == 12


def test_assemble_renumbers_citations_globally_across_sections():
    """Each section's citations restart at [1] locally — _assemble must renumber them
    into one continuous sequence and emit a matching References list."""
    sections = [
        {
            "question": "What is attention?",
            "answer_markdown": "Attention lets models weigh tokens [1][2].",
            "citations": [
                {"id": 1, "paper_title": "Attention Is All You Need", "arxiv_id": "1706.03762", "authors": ["Vaswani"]},
                {"id": 2, "paper_title": "Attention Is All You Need", "arxiv_id": "1706.03762", "authors": ["Vaswani"]},
            ],
        },
        {
            "question": "What are state space models?",
            "answer_markdown": "SSMs scale linearly [1].",
            "citations": [
                {"id": 1, "paper_title": "Mamba", "arxiv_id": "2312.00752", "authors": ["Gu"]},
            ],
        },
    ]
    doc = _assemble("Efficient sequence modeling", sections)

    assert "Attention lets models weigh tokens [1][2]." in doc
    # Second section's [1] must be renumbered to [3] — not collide with section 1's citations.
    assert "SSMs scale linearly [3]." in doc
    assert "## References" in doc
    assert "[1] Vaswani" in doc
    assert "[3] Gu" in doc


def test_assemble_with_no_citations_omits_references_section():
    sections = [{"question": "Q1", "answer_markdown": "An uncited answer.", "citations": []}]
    doc = _assemble("Topic", sections)
    assert "## References" not in doc


@pytest.mark.asyncio
async def test_get_research_returns_none_when_missing():
    redis = AsyncMock()
    redis.get.return_value = None
    assert await get_research(redis, "missing-id") is None


@pytest.mark.asyncio
async def test_run_deep_research_happy_path_marks_done_with_result():
    """Planner returns sub-questions, each is answered, and the job ends in status=done
    with a non-empty assembled document."""
    app_state = MagicMock()
    app_state.redis = AsyncMock()
    app_state.db_session_factory = MagicMock()

    with (
        patch("src.services.deep_research.call_fast_llm", new_callable=AsyncMock) as mock_llm,
        patch("src.services.deep_research.parse_json_response") as mock_parse,
        patch("src.agents.rag_graph.ask_corpus", new_callable=AsyncMock) as mock_ask,
        patch("src.agents.tools.AgentToolkit"),
        patch("src.retrieval.hybrid_search.HybridSearchService") as mock_search_cls,
        patch("src.retrieval.reranker.create_reranker") as mock_create_reranker,
    ):
        mock_llm.return_value = '{"sub_questions": ["What is X?"]}'
        mock_parse.return_value = {"sub_questions": ["What is X?"]}
        mock_ask.return_value = {"answer_markdown": "X is a thing [1].", "citations": [{"id": 1}]}
        mock_search_cls.return_value.close = AsyncMock()
        mock_create_reranker.return_value.close = AsyncMock()

        await run_deep_research("rid123", "Topic X", None, app_state)

    # Last stored state must reflect a completed job.
    last_call_payload = app_state.redis.set.call_args_list[-1][0][1]
    import json

    final_state = json.loads(last_call_payload)
    assert final_state["status"] == "done"
    assert final_state["result_markdown"] is not None
    assert "X is a thing" in final_state["result_markdown"]


@pytest.mark.asyncio
async def test_run_deep_research_marks_failed_on_planner_exception():
    """If the planning LLM call itself blows up, the job must land in status=failed
    with the error recorded — never raise out of the background task."""
    app_state = MagicMock()
    app_state.redis = AsyncMock()

    with patch("src.services.deep_research.call_fast_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = RuntimeError("Ollama unreachable")

        await run_deep_research("rid456", "Topic Y", None, app_state)

    import json

    last_call_payload = app_state.redis.set.call_args_list[-1][0][1]
    final_state = json.loads(last_call_payload)
    assert final_state["status"] == "failed"
    assert "Ollama unreachable" in final_state["error"]
