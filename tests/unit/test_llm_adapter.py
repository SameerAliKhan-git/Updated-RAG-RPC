"""Corpus — LLM Adapter Unit Tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services.llm_adapter import call_drafting_llm, call_reasoning_llm, parse_json_response


@pytest.mark.asyncio
@patch("src.services.llm_adapter._call_litellm", new_callable=AsyncMock)
async def test_llm_adapter_routing(mock_call):
    """Verify that reasoning and drafting endpoints route requests to call_litellm."""
    mock_call.return_value = "Response content"

    resp1 = await call_reasoning_llm([{"role": "user", "content": "hello"}])
    resp2 = await call_drafting_llm([{"role": "user", "content": "world"}])

    assert resp1 == "Response content"
    assert resp2 == "Response content"
    assert mock_call.call_count == 2


def test_parse_json_response():
    """Verify JSON block parsing logic handles markdown fences and extracts valid dicts."""
    raw1 = "```json\n{\"query_type\": \"casual\"}\n```"
    raw2 = "Some text before {\"query_type\": \"simple\"} some text after"

    res1 = parse_json_response(raw1)
    res2 = parse_json_response(raw2)

    assert res1 == {"query_type": "casual"}
    assert res2 == {"query_type": "simple"}
