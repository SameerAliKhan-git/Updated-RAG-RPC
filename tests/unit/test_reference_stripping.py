"""Corpus — fabricated-bibliography stripping tests.

Regression cover for a real trust bug: llama3.2:1b ignored the prompt rule
forbidding a References section and appended one with invented authors,
invented titles, and invented arXiv IDs — which then passed verification
because the [N] markers inside it were structurally valid.
"""

from __future__ import annotations

from src.agents.rag_graph import _strip_fabricated_references


def test_strips_the_real_world_fabricated_block():
    """The exact shape observed in production: a correct body followed by a
    hallucinated bibliography attributing the wrong authors to the wrong papers."""
    answer = (
        "Agentic RAG refers to recursive self-correction [1].\n\n"
        "In the VEXAIoT paper [2], the VDA uses human corrections.\n\n"
        "## References\n\n"
        '[1] Alzubi, A., et al. "Agent-based recursive architecture." arXiv:2206.05787, 2022.\n'
        '[2] Sun, Yasheng, et al. "Vulnerability detection agent." arXiv:2607.09653, 2022.\n'
    )
    cleaned, stripped = _strip_fabricated_references(answer)

    assert stripped is True
    assert "Alzubi" not in cleaned
    assert "2206.05787" not in cleaned
    assert "## References" not in cleaned
    # The real answer body and its inline citations survive untouched.
    assert "Agentic RAG refers to recursive self-correction [1]." in cleaned
    assert "In the VEXAIoT paper [2]" in cleaned


def test_citation_count_reflects_body_only_after_stripping():
    """The bug's second half: markers inside the fabricated block inflated the
    'N citations verified' badge. After stripping, only body markers remain."""
    import re

    answer = "Body claim [1].\n\n## References\n[1] fake\n[2] fake\n[3] fake\n"
    cleaned, _ = _strip_fabricated_references(answer)
    assert set(re.findall(r"\[(\d+)\]", cleaned)) == {"1"}


def test_strips_common_heading_variants():
    for heading in (
        "## References",
        "### Bibliography",
        "**References**",
        "References:",
        "Works Cited",
        "# Sources",
        "Citations",
    ):
        answer = f"Real body text [1].\n\n{heading}\n\n[1] invented citation\n"
        cleaned, stripped = _strip_fabricated_references(answer)
        assert stripped is True, f"failed to strip variant: {heading!r}"
        assert "invented citation" not in cleaned
        assert "Real body text [1]." in cleaned


def test_leaves_clean_answers_untouched():
    answer = "Attention weighs tokens by query-key similarity [1].\n\nIt scales poorly [2]."
    cleaned, stripped = _strip_fabricated_references(answer)
    assert stripped is False
    assert cleaned == answer


def test_does_not_match_the_word_mid_sentence():
    """'references' inside prose must not trigger a strip — only a heading line."""
    answer = "The paper references prior work on state space models [1]. Sources agree [2]."
    cleaned, stripped = _strip_fabricated_references(answer)
    assert stripped is False
    assert cleaned == answer


def test_never_strips_the_entire_answer():
    """A model that opens with a 'Sources' heading must not be reduced to nothing —
    losing the body would be worse than leaving the bibliography in."""
    answer = "## Sources\n\n[1] something\n"
    cleaned, stripped = _strip_fabricated_references(answer)
    assert stripped is False
    assert cleaned == answer


def test_strips_only_from_the_last_heading():
    """If the word appears as a heading twice, cut at the final one so no real
    content between them is lost."""
    answer = "Intro [1].\n\n## Sources\n\nDiscussion of sources [2].\n\n## References\n\n[1] fake\n"
    cleaned, stripped = _strip_fabricated_references(answer)
    assert stripped is True
    assert "Discussion of sources [2]." in cleaned
    assert "fake" not in cleaned
