"""Corpus — Golden Evaluation Set CI Gate.

Runs as a pytest suite. Validates the performance, faithfulness, and formatting
of the RAG pipeline on a set of core golden questions.
This behaves as a gate blocking PR merges that regress quality.
"""

from __future__ import annotations

import logging

import pytest

from src.agents.rag_graph import ask_corpus
from src.retrieval.hybrid_search import RetrievedChunk

logger = logging.getLogger(__name__)

# Core Golden Set of 3 questions with expected focus/categories
GOLDEN_SET = [
    {
        "question": "Compare the performance of self-attention versus state-space models.",
        "expected_categories": ["cs.LG", "cs.CL", "cs.AI"],
        "min_citations": 1,
    },
    {
        "question": "What is the primary formula or logic behind Reciprocal Rank Fusion (RRF)?",
        "expected_categories": ["cs.IR", "cs.LG", "cs.AI"],
        "min_citations": 1,
    },
    {
        "question": "What are the limitations of transformers highlighted in the recent papers?",
        "expected_categories": ["cs.CL", "cs.LG", "cs.AI"],
        "min_citations": 1,
    },
]


class MockToolkit:
    """Mock agent toolkit for golden set evaluation without calling real databases/indexes."""

    def __init__(self):
        self.redis = None

    async def hybrid_search(
        self,
        query: str,
        top_k: int = 15,
        filters: dict | None = None,
        *args,
        **kwargs,
    ) -> list[RetrievedChunk]:
        """Return high-quality mocked research paper chunks."""
        return [
            RetrievedChunk(
                chunk_id="chunk_ssm_01",
                arxiv_id="2312.00752",
                paper_id="paper_ssm_uuid",
                section_title="State Space Models vs Attention",
                chunk_type="body",
                text="State Space Models (SSMs) like Mamba scale linearly O(N) with sequence length, whereas Transformers using standard self-attention scale quadratically O(N^2) in sequence length. However, standard SSMs often struggle with factual recall tasks.",
                title="Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
                authors=["Albert Gu", "Tri Dao"],
                abstract="Selective State Space Models perform highly efficiently on sequence modeling.",
                categories=["cs.LG", "cs.CL"],
                published_date="2023-12-01",
                score=0.9,
            ),
            RetrievedChunk(
                chunk_id="chunk_rrf_01",
                arxiv_id="1501.00001",
                paper_id="paper_rrf_uuid",
                section_title="Reciprocal Rank Fusion",
                chunk_type="body",
                text="Reciprocal Rank Fusion (RRF) scores each document d in a set of result lists D by summing the reciprocal of its rank r_m(d) in each list: RRF_score(d) = sum(1 / (k + r_m(d))), where k is a constant parameter (usually set to 60).",
                title="Reciprocal Rank Fusion Outperforms Condorcet and Individual Retrieval Methods",
                authors=["Gordon V. Cormack", "Charles L. A. Clarke"],
                abstract="A simple fusion method RRF works robustly.",
                categories=["cs.IR", "cs.AI"],
                published_date="2015-01-01",
                score=0.85,
            ),
        ]

    async def rerank_chunks(self, query: str, chunks: list[RetrievedChunk], top_k: int = 8) -> list[RetrievedChunk]:
        return chunks[:top_k]

    async def get_paper(self, arxiv_id: str) -> dict | None:
        return {"title": "Mock Paper"}

    async def search_arxiv_live(self, query: str, max_results: int = 5, *args, **kwargs) -> list[dict]:
        return []

    async def trigger_ingestion(self, arxiv_id: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_golden_questions_formatting_gate():
    """Verify that golden questions return answers adhering to strict formatting guidelines."""
    toolkit = MockToolkit()

    for item in GOLDEN_SET:
        question = item["question"]
        min_citations = item["min_citations"]

        result = await ask_corpus(query=question, toolkit=toolkit)

        answer = result.get("answer_markdown", "")
        citations = result.get("citations", [])
        grounding_note = result.get("grounding_note", "")

        assert len(answer) > 50, f"Answer for '{question}' is too short."
        assert len(citations) >= min_citations, f"Expected at least {min_citations} citations."

        # Check inline citation markers [N]
        for c in citations:
            cid = c.get("id")
            assert f"[{cid}]" in answer, f"Citation [{cid}] is missing in inline text."

        # Verify grounding note format
        assert "claims" in grounding_note.lower() or "citations" in grounding_note.lower(), (
            f"Grounding note '{grounding_note}' format is invalid."
        )


@pytest.mark.asyncio
async def test_golden_questions_faithfulness_gate():
    """Verify that there are no hallucinated citation markers in the response."""
    toolkit = MockToolkit()

    for item in GOLDEN_SET:
        result = await ask_corpus(query=item["question"], toolkit=toolkit)
        answer = result.get("answer_markdown", "")
        citations = result.get("citations", [])

        import re

        cited_nums = set(int(num) for num in re.findall(r"\[(\d+)\]", answer))
        valid_nums = set(c.get("id") for c in citations)

        # Hallucinated citation: the answer has [N] where N is not in the citations list
        hallucinated = cited_nums - valid_nums
        assert len(hallucinated) == 0, (
            f"HALLUCINATION: Citations {hallucinated} were cited but not returned in metadata."
        )
