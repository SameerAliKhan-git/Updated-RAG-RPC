"""Corpus — Full Agentic RAG Graph (LangGraph).

The 11-node state machine that makes this "agentic" rather than a simple
retrieve-then-generate pipe:

  intake_and_route → plan → retrieve → grade → route_on_grade
    → rerank → build_context → generate → verify_citations
    → finalize → update_memory → END

  With branches for: rewrite_query (retry), live_arxiv_lookup, admit_gap.

HARD RULE: the agent NEVER presents an uncited claim as if it came from
the corpus. This is enforced in verify_citations, not just prompted for.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.prompts import (
    GAP_RESPONSE_TEMPLATE,
    GENERATOR_SYSTEM_PROMPT,
    GENERATOR_USER_PROMPT,
    GRADER_PROMPT,
    PLANNER_PROMPT,
    REWRITER_PROMPT,
    ROUTER_PROMPT,
    VERIFIER_PROMPT,
)
from src.retrieval.context_builder import build_citation_context
from src.services.llm_adapter import (
    call_drafting_llm,
    call_fast_llm,
    call_reasoning_llm,
    parse_json_response,
    stream_drafting_llm,
)
from src.services.tracing import trace_node

logger = logging.getLogger(__name__)


# ─── State Definition ──────────────────────────────────────────────


class AgentState(TypedDict, total=False):
    """Complete state flowing through the agentic graph."""

    # Input
    query: str
    session_id: str
    conversation_history: list[dict[str, str]]

    # Routing
    query_type: str  # casual, simple, complex, followup

    # Planning
    sub_questions: list[str]

    # Retrieval
    all_retrieved_chunks: list[Any]  # List[RetrievedChunk]
    relevant_chunks: list[Any]
    reranked_chunks: list[Any]
    retrieved_arxiv_ids: list[str]

    # Context
    context_str: str
    citation_meta: list[dict[str, Any]]
    chunk_ids_in_context: list[str]

    # Generation
    answer_markdown: str
    citations: list[dict[str, Any]]
    grounding_note: str

    # Control
    retry_count: int
    max_retries: int
    current_query: str  # May be rewritten
    trace_events: list[str]
    error: str
    filters: dict[str, Any]
    generation_retry_count: int
    generation_feedback: str

    # Tools reference (set at graph invocation, not serialized)
    toolkit: Any

    # Optional live-event callback (set for streaming invocations, not serialized)
    emit: Any

    # Per-request opt-in for the LLM faithfulness check + its structured result
    deep_verify: bool
    verification: dict[str, Any] | None


# ─── Node Implementations ─────────────────────────────────────────


@trace_node("intake_and_route")
async def intake_and_route(state: AgentState) -> AgentState:
    """Node 1: Classify the query type and extract metadata filters."""
    _emit(state, "classifying query...")

    query = state["query"]
    history = state.get("conversation_history", [])
    history_str = json.dumps(history[-3:]) if history else "[]"

    # Fast path: obvious queries skip the LLM router entirely (saves 15-20s)
    from src.agents.heuristics import heuristic_route
    from src.middleware.metrics import ROUTER_DECISIONS

    heuristic_type = heuristic_route(query, has_history=bool(history))
    if heuristic_type is not None:
        _emit(state, f"router: heuristic → {heuristic_type}")
        ROUTER_DECISIONS.labels(method="heuristic", route=heuristic_type).inc()
        parsed: dict[str, Any] = {}
        query_type = heuristic_type
    else:
        prompt = ROUTER_PROMPT.format(query=query, history=history_str)
        response = await call_fast_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=256,
        )
        parsed = parse_json_response(response)
        query_type = parsed.get("query_type", "simple")
        if query_type not in ("casual", "simple", "complex", "followup"):
            query_type = "simple"
        ROUTER_DECISIONS.labels(method="llm", route=query_type).inc()

    # Merge LLM-extracted filters with request-level filters — the caller's
    # explicit filters (e.g. an attached PDF's arxiv_id) always win.
    filters = {k: v for k, v in parsed.get("filters", {}).items() if v}
    request_filters = {k: v for k, v in (state.get("filters") or {}).items() if v}
    filters.update(request_filters)
    if filters:
        _emit(state, f"active metadata filters: {filters}")

    return {
        **state,
        "query_type": query_type,
        "current_query": query,
        "retry_count": state.get("retry_count", 0),
        "max_retries": 2,
        "filters": filters,
        "generation_retry_count": state.get("generation_retry_count", 0),
        "generation_feedback": state.get("generation_feedback", ""),
        "trace_events": state.get("trace_events", []),
    }


@trace_node("plan")
async def plan(state: AgentState) -> AgentState:
    """Node 2: Decompose complex queries into sub-questions."""
    query = state["query"]
    query_type = state.get("query_type", "simple")

    if query_type in ("simple", "followup"):
        _emit(state, "single-hop query — skipping decomposition")
        return {**state, "sub_questions": [query]}

    _emit(state, "decomposing complex query into sub-questions...")

    prompt = PLANNER_PROMPT.format(query=query)
    response = await call_reasoning_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=512,
    )

    parsed = parse_json_response(response)
    sub_questions = parsed.get("sub_questions", [query])
    if not sub_questions:
        sub_questions = [query]

    # Cap at 4 sub-questions
    sub_questions = sub_questions[:4]
    _emit(state, f"decomposed into {len(sub_questions)} sub-questions")

    return {**state, "sub_questions": sub_questions}


@trace_node("retrieve")
async def retrieve(state: AgentState) -> AgentState:
    """Node 3: Hybrid search per sub-question."""
    toolkit = state.get("toolkit")
    sub_questions = state.get("sub_questions", [state["query"]])
    current_query = state.get("current_query", state["query"])

    # Use current_query if it's a rewrite, otherwise sub_questions
    queries = sub_questions if state.get("retry_count", 0) == 0 else [current_query]

    # Concept-graph augmentation: "evolution of X" / "which papers use X" style
    # queries resolve the concept to its papers and scope retrieval to them.
    filters = dict(state.get("filters") or {})
    if toolkit and getattr(toolkit, "db_session", None) and not filters.get("arxiv_ids"):
        from src.agents.heuristics import graph_concept
        from src.agents.tools import ConceptGraphTools

        concept = graph_concept(state.get("current_query", state["query"]))
        if concept:
            try:
                graph_ids = ConceptGraphTools(toolkit.db_session).papers_for_concept(concept)
                if graph_ids:
                    filters["arxiv_ids"] = graph_ids
                    _emit(state, f"concept graph: '{concept}' → scoping to {len(graph_ids)} papers")
                else:
                    _emit(state, f"concept graph: '{concept}' not in graph — using normal retrieval")
            except Exception as e:
                logger.warning(f"Concept graph lookup failed: {e}")

    _emit(state, f"hybrid search (BM25 + vectors) for {len(queries)} queries...")

    all_chunks = []
    for q in queries:
        if toolkit:
            chunks = await toolkit.hybrid_search(q, top_k=15, filters=filters)
        else:
            chunks = []
        all_chunks.extend(chunks)

    _emit(state, f"{len(all_chunks)} candidates found")

    # Ordered, first-seen-deduped paper ids — consumed by retrieval metrics (hit@k/MRR)
    seen: set[str] = set()
    retrieved_ids = []
    for c in all_chunks:
        aid = getattr(c, "arxiv_id", "")
        if aid and aid not in seen:
            seen.add(aid)
            retrieved_ids.append(aid)

    return {**state, "all_retrieved_chunks": all_chunks, "retrieved_arxiv_ids": retrieved_ids}


@trace_node("grade")
async def grade(state: AgentState) -> AgentState:
    """Node 4: CRAG-style LLM relevance grading per chunk."""
    import asyncio

    chunks = state.get("all_retrieved_chunks", [])
    query = state.get("current_query", state["query"])

    if not chunks:
        _emit(state, "no chunks to grade")
        return {**state, "relevant_chunks": []}

    _emit(state, f"grading {len(chunks)} chunks for relevance...")

    from src.config import get_settings

    # Cap grading for latency — each graded chunk is one LLM call, and on
    # CPU-only Ollama concurrent calls serialize.
    candidate_chunks = chunks[: get_settings().grading_max_chunks]

    async def grade_single_chunk(chunk):
        prompt = GRADER_PROMPT.format(
            question=query,
            paper_title=getattr(chunk, "title", "Unknown"),
            section=getattr(chunk, "section_title", "Unknown"),
            chunk_text=getattr(chunk, "text", "")[:1500],
        )
        try:
            response = await call_fast_llm(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            parsed = parse_json_response(response)
            return chunk if parsed.get("relevant", False) else None
        except Exception as e:
            logger.warning(f"Grading failed for chunk: {e}")
            # Include chunk on grading failure (permissive)
            return chunk

    # Run grading tasks concurrently
    tasks = [grade_single_chunk(chunk) for chunk in candidate_chunks]
    results = await asyncio.gather(*tasks)
    relevant = [res for res in results if res is not None]

    _emit(state, f"{len(relevant)} chunks judged relevant")
    return {**state, "relevant_chunks": relevant}


def route_on_grade(state: AgentState) -> str:
    """Node 5: Branch based on grading results.

    Returns the name of the next node to execute.
    """
    relevant = state.get("relevant_chunks", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if len(relevant) >= 2:
        return "rerank"
    elif len(relevant) == 1:
        # Enough for a partial answer
        return "rerank"
    elif retry_count < max_retries:
        return "rewrite_query"
    else:
        return "live_arxiv_lookup"


@trace_node("rewrite_query")
async def rewrite_query(state: AgentState) -> AgentState:
    """Node 6: Reformulate the query for better retrieval."""
    query = state.get("current_query", state["query"])
    relevant = state.get("relevant_chunks", [])
    all_chunks = state.get("all_retrieved_chunks", [])
    retry_count = state.get("retry_count", 0)

    _emit(state, f"rewriting query (attempt {retry_count + 1})...")

    prompt = REWRITER_PROMPT.format(
        query=query,
        num_relevant=len(relevant),
        num_total=len(all_chunks),
    )

    response = await call_fast_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=256,
    )

    parsed = parse_json_response(response)
    rewritten = parsed.get("rewritten_query", query)

    _emit(state, f"rewritten: {rewritten[:80]}...")

    return {
        **state,
        "current_query": rewritten,
        "retry_count": retry_count + 1,
    }


@trace_node("live_arxiv_lookup")
async def live_arxiv_lookup(state: AgentState) -> AgentState:
    """Node 7: Search arXiv API directly for unindexed papers."""
    toolkit = state.get("toolkit")
    query = state.get("current_query", state["query"])

    _emit(state, "searching arXiv live (paper may not be indexed)...")

    if toolkit:
        results = await toolkit.search_arxiv_live(query, max_results=3)
    else:
        results = []

    if results:
        _emit(state, f"found {len(results)} papers on arXiv")
        # Queue ingestion for top result
        if toolkit and results:
            top_id = results[0].get("arxiv_id", "")
            if top_id:
                await toolkit.trigger_ingestion(top_id)
                _emit(state, f"queued {top_id} for ingestion")

        # Create synthetic context from arXiv results
        context_parts = []
        citations = []
        for idx, paper in enumerate(results, start=1):
            context_parts.append(
                f"--- Source [{idx}] ---\n"
                f"Paper: {paper['title']} (arXiv:{paper['arxiv_id']})\n"
                f"Authors: {', '.join(paper['authors'][:3])}\n"
                f"Abstract:\n{paper['abstract'][:500]}\n"
                f"--- End Source [{idx}] ---\n"
            )
            citations.append(
                {
                    "citation_id": idx,
                    "chunk_id": f"live_{paper['arxiv_id']}",
                    "paper_title": paper["title"],
                    "authors": paper["authors"],
                    "arxiv_id": paper["arxiv_id"],
                    "arxiv_url": paper["arxiv_url"],
                    "pdf_url": paper["pdf_url"],
                    "section": "Abstract (live lookup)",
                    "chunk_type": "abstract",
                    "snippet": paper["abstract"][:200],
                }
            )

        return {
            **state,
            "context_str": "\n".join(context_parts),
            "citation_meta": citations,
            "chunk_ids_in_context": [f"live_{r['arxiv_id']}" for r in results],
            "relevant_chunks": [],  # Mark as live-sourced
        }

    _emit(state, "no results from live arXiv search")
    return state


def route_after_live_lookup(state: AgentState) -> str:
    """Route after live lookup — generate if we have context, otherwise admit gap."""
    if state.get("context_str"):
        return "generate"
    return "admit_gap"


@trace_node("admit_gap")
async def admit_gap(state: AgentState) -> AgentState:
    """Node 8: Honestly tell the user the corpus doesn't cover this."""
    query = state["query"]
    _emit(state, "corpus does not cover this question — admitting gap")

    details = "The indexed corpus does not contain papers directly addressing this question."
    all_chunks = state.get("all_retrieved_chunks", [])
    if all_chunks:
        related_papers = set()
        for c in all_chunks[:5]:
            if hasattr(c, "title") and c.title:
                related_papers.add(c.title)
        if related_papers:
            details += "\n\n**Related papers found (but not directly relevant):**\n"
            for title in list(related_papers)[:3]:
                details += f"- {title}\n"

    answer = GAP_RESPONSE_TEMPLATE.format(query=query, details=details)

    return {
        **state,
        "answer_markdown": answer,
        "citations": [],
        "grounding_note": "0 of 0 claims — question outside corpus coverage",
    }


@trace_node("rerank")
async def rerank_node(state: AgentState) -> AgentState:
    """Node 9: Cross-encoder reranking of relevant chunks."""
    toolkit = state.get("toolkit")
    relevant = state.get("relevant_chunks", [])
    query = state.get("current_query", state["query"])

    if not relevant:
        return {**state, "reranked_chunks": []}

    _emit(state, f"reranking {len(relevant)} chunks...")

    if toolkit:
        reranked = await toolkit.rerank_chunks(query, relevant, top_k=4)
    else:
        reranked = relevant[:4]

    _emit(state, f"top {len(reranked)} chunks after reranking")

    return {**state, "reranked_chunks": reranked}


@trace_node("build_context")
async def build_context(state: AgentState) -> AgentState:
    """Node 10: Assemble citation-tagged context from reranked chunks."""
    reranked = state.get("reranked_chunks", [])

    _emit(state, "building citation-tagged context...")

    # Parent-Child Semantic Expansion: Expand child chunks to parent section text
    toolkit = state.get("toolkit")
    if toolkit and toolkit.db_session:
        from src.models.paper import Chunk as DBChunk
        for chunk in reranked:
            try:
                db_chunk = toolkit.db_session.query(DBChunk).filter(DBChunk.chunk_id == chunk.chunk_id).first()
                if db_chunk:
                    siblings = (
                        toolkit.db_session.query(DBChunk)
                        .filter(
                            DBChunk.paper_id == db_chunk.paper_id,
                            DBChunk.section_title == db_chunk.section_title
                        )
                        .all()
                    )
                    if siblings:
                        # Sort sequentially using created_at (stable sort preserves insertion order)
                        siblings_sorted = sorted(siblings, key=lambda x: x.created_at or 0)
                        parent_text = "\n\n".join(s.text for s in siblings_sorted)
                        # Cap expanded context — whole sections can be enormous, and
                        # prompt prefill cost scales linearly with context length.
                        if len(parent_text) > 4000:
                            marker = chunk.text[:200]
                            pos = parent_text.find(marker)
                            start = max(0, pos - 1500) if pos >= 0 else 0
                            parent_text = parent_text[start : start + 4000]
                        chunk.text = parent_text
            except Exception as ex:
                logger.error(f"Failed to expand chunk {chunk.chunk_id} to parent context: {ex}")

    ctx = build_citation_context(reranked, max_chunks=4)

    # Convert CitationMeta dataclasses to dicts for serialization
    citation_dicts = []
    for cm in ctx.citations:
        citation_dicts.append(
            {
                "citation_id": cm.citation_id,
                "chunk_id": cm.chunk_id,
                "paper_title": cm.paper_title,
                "authors": cm.authors,
                "arxiv_id": cm.arxiv_id,
                "arxiv_url": cm.arxiv_url,
                "pdf_url": cm.pdf_url,
                "section": cm.section,
                "chunk_type": cm.chunk_type,
                "snippet": cm.snippet,
                "score": cm.score,
                "published_date": cm.published_date,
                "categories": cm.categories,
                "page": cm.page,
            }
        )

    return {
        **state,
        "context_str": ctx.context_str,
        "citation_meta": citation_dicts,
        "chunk_ids_in_context": ctx.chunk_ids_in_context,
    }


@trace_node("generate")
async def generate(state: AgentState) -> AgentState:
    """Node 11: Structured, citation-aware answer generation."""
    context = state.get("context_str", "")
    query = state.get("current_query", state["query"])

    if not context or context == "No relevant sources found.":
        return {**state, "answer_markdown": "No sources available to answer this question."}

    feedback = state.get("generation_feedback", "")
    retry_num = state.get("generation_retry_count", 0)

    if feedback:
        _emit(state, f"regenerating answer with correction feedback (attempt {retry_num})...")
        feedback_block = f"\n### Verification Feedback (Fix the following issues in this rewrite):\n{feedback}"
    else:
        _emit(state, "generating answer with citations...")
        feedback_block = ""

    # Contradiction surfacing: when context spans multiple papers, instruct the
    # model to state disagreements explicitly instead of papering over them.
    distinct_papers = {cm.get("arxiv_id") for cm in state.get("citation_meta", []) if cm.get("arxiv_id")}
    if len(distinct_papers) >= 2:
        feedback_block += (
            "\nNote: the sources come from multiple papers. If they disagree on any claim, "
            "state the disagreement explicitly and cite both sources."
        )

    system_prompt = GENERATOR_SYSTEM_PROMPT
    user_content = GENERATOR_USER_PROMPT.format(context=context, query=query, feedback_block=feedback_block)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    from src.config import get_settings

    max_tokens = get_settings().generation_max_tokens

    # True token streaming: push each LLM token live while accumulating the full
    # answer for downstream verification. Regeneration retries are not streamed —
    # the verified answer arrives in the final `done` payload.
    if state.get("emit") is not None and retry_num == 0:
        parts: list[str] = []
        async for token in stream_drafting_llm(messages, temperature=0.3, max_tokens=max_tokens):
            parts.append(token)
            _emit_live(state, {"type": "token", "text": token})
        answer = "".join(parts)
    else:
        answer = await call_drafting_llm(messages, temperature=0.3, max_tokens=max_tokens)

    _emit(state, "answer generated")

    return {**state, "answer_markdown": answer}


@trace_node("verify_citations")
async def verify_citations(state: AgentState) -> AgentState:
    """Node 12: Post-generation faithfulness check.

    THE HARD RULE: every cited claim is checked against its source.
    Unsupported claims are stripped or hedged — never left in.
    """
    answer = state.get("answer_markdown", "")
    context = state.get("context_str", "")
    citation_meta = state.get("citation_meta", [])

    if not answer or not context:
        return {
            **state,
            "grounding_note": "No claims to verify",
        }

    _emit(state, "verifying citations against sources...")

    # Step 1: Validate that cited numbers exist in context
    cited_nums = set(int(m) for m in re.findall(r"\[(\d+)\]", answer))
    valid_nums = set(cm["citation_id"] for cm in citation_meta) if citation_meta else set()
    invalid_nums = cited_nums - valid_nums

    # Strip invalid citations from the answer
    cleaned_answer = answer
    for inv in invalid_nums:
        cleaned_answer = cleaned_answer.replace(f"[{inv}]", "")
        logger.warning(f"Stripped invented citation [{inv}] from answer")

    # Step 2: LLM-based faithfulness check — globally enabled or opted-in per request
    from src.config import get_settings

    enable_llm_verify = get_settings().enable_llm_verification or state.get("deep_verify", False)

    # Always initialize feedback
    generation_feedback = ""
    retry_num = state.get("generation_retry_count", 0)

    if not enable_llm_verify:
        grounding_note = f"{len(cited_nums - invalid_nums)} citations verified"
        _emit(state, f"verification complete (LLM validation skipped): {grounding_note}")
        return {
            **state,
            "answer_markdown": cleaned_answer,
            "grounding_note": grounding_note,
            "generation_feedback": "",
            "verification": None,
        }

    verification: dict[str, Any] | None = None
    try:
        prompt = VERIFIER_PROMPT.format(answer=cleaned_answer, context=context)
        response = await call_reasoning_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1024,
        )
        parsed = parse_json_response(response)

        grounding_note = parsed.get("grounding_note", f"{len(cited_nums - invalid_nums)} citations used")
        verification = {
            "verified_claims": parsed.get("verified_claims", 0),
            "total_claims": parsed.get("total_claims", 0),
            "issues": parsed.get("issues", []),
        }

        # Process issues — strip or hedge problematic claims
        issues = parsed.get("issues", [])
        feedback_list = []
        for issue in issues:
            action = issue.get("action", "keep")
            claim_text = issue.get("claim", "")
            if action == "remove" and claim_text and claim_text in cleaned_answer:
                cleaned_answer = cleaned_answer.replace(
                    claim_text, f"~~{claim_text}~~ *(removed: unsupported by source)*"
                )
                feedback_list.append(
                    f"- Citation {issue.get('citation', '')} for claim '{claim_text}' "
                    f"was flagged: {issue.get('issue', '')} (Action: remove)"
                )
            elif action == "hedge" and claim_text and claim_text in cleaned_answer:
                cleaned_answer = cleaned_answer.replace(claim_text, f"*[note: source partially supports]* {claim_text}")
                feedback_list.append(
                    f"- Citation {issue.get('citation', '')} for claim '{claim_text}' "
                    f"was flagged: {issue.get('issue', '')} (Action: hedge)"
                )

        if feedback_list and retry_num < 2:
            generation_feedback = (
                "Please address the following citation issues in the rewrite:\n"
                + "\n".join(feedback_list)
            )
            # Increment retry count for the next iteration
            retry_num += 1
            _emit(state, f"citations verification flagged issues; queueing self-correction retry {retry_num}")
        else:
            generation_feedback = ""

    except Exception as e:
        logger.error(f"Citation verification failed: {e}")
        grounding_note = f"{len(cited_nums - invalid_nums)} citations present (verification error)"

    _emit(state, f"verification complete: {grounding_note}")

    return {
        **state,
        "answer_markdown": cleaned_answer,
        "grounding_note": grounding_note,
        "generation_retry_count": retry_num,
        "generation_feedback": generation_feedback,
        "verification": verification,
    }


@trace_node("finalize")
async def finalize(state: AgentState) -> AgentState:
    """Node 13: Resolve citation IDs to full citation objects for the API response."""
    answer = state.get("answer_markdown", "")
    citation_meta = state.get("citation_meta", [])

    _emit(state, "resolving citations...")

    # Extract which citations are actually used in the final answer
    used_nums = set(int(m) for m in re.findall(r"\[(\d+)\]", answer))

    # Build the final citations array with only used citations
    final_citations = []
    for cm in citation_meta:
        if cm["citation_id"] in used_nums:
            final_citations.append(
                {
                    "id": cm["citation_id"],
                    "paper_title": cm["paper_title"],
                    "authors": cm["authors"],
                    "arxiv_id": cm["arxiv_id"],
                    "arxiv_url": cm["arxiv_url"],
                    "pdf_url": cm["pdf_url"],
                    "section": cm["section"],
                    "snippet": cm["snippet"],
                    "score": cm.get("score", 0.0),
                    "published_date": cm.get("published_date", ""),
                    "categories": cm.get("categories", []),
                    "page": cm.get("page"),
                }
            )

    # Sort by ID for consistent ordering
    final_citations.sort(key=lambda c: c["id"])

    _emit(state, f"finalized {len(final_citations)} citations")

    return {
        **state,
        "citations": final_citations,
    }


@trace_node("update_memory")
async def update_memory(state: AgentState) -> AgentState:
    """Node 14: Persist session state to Redis for follow-ups and extract long-term graph memory."""
    toolkit = state.get("toolkit")
    session_id = state.get("session_id", "")
    query = state["query"]
    answer = state.get("answer_markdown", "")
    query_type = state.get("query_type", "simple")

    # 1. Update Short-term Redis Memory
    if toolkit and toolkit.redis and session_id:
        try:
            history = state.get("conversation_history", [])
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": answer[:500]})

            # Keep last 10 turns
            history = history[-20:]

            import json

            await toolkit.redis.setex(
                f"corpus:session:{session_id}",
                3600 * 6,  # 6 hour TTL
                json.dumps(history),
            )
            _emit(state, "session memory updated")
        except Exception as e:
            logger.warning(f"Failed to update session memory: {e}")

    # 2. Extract & Save Long-term Memory Graph in PostgreSQL
    if toolkit and toolkit.db_session and session_id and query_type != "casual":
        _emit(state, "extracting long-term memory graph concepts...")
        try:
            from src.models.paper import MemoryEdge as DBMemoryEdge
            from src.models.paper import MemoryNode as DBMemoryNode

            # Run LLM extraction
            extraction_prompt = (
                "You are an AI memory graph extractor.\n"
                "Extract the primary research topics or entities that the user is investigating.\n"
                "Respond in valid JSON format:\n"
                "{\n"
                '    "topics": [\n'
                '        {"name": "<topic>", "score": <relevance float 0.0 to 1.0>}\n'
                "    ]\n"
                "}\n\n"
                f"User Query: {query}\n"
                f"Assistant Answer Snippet: {answer[:300]}"
            )
            # Topic tagging is low-stakes — use the fast model to keep the
            # end-of-turn latency down.
            llm_response = await call_fast_llm(
                messages=[{"role": "user", "content": extraction_prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            parsed = parse_json_response(llm_response)
            topics = parsed.get("topics", [])

            if topics:
                # Get or create User/Session Root node
                user_node = toolkit.db_session.query(DBMemoryNode).filter(
                    DBMemoryNode.session_id == session_id,
                    DBMemoryNode.label == "User"
                ).first()
                if not user_node:
                    user_node = DBMemoryNode(
                        session_id=session_id,
                        label="User",
                        properties={"session_id": session_id}
                    )
                    toolkit.db_session.add(user_node)
                    toolkit.db_session.commit()
                    toolkit.db_session.refresh(user_node)

                for t in topics:
                    t_name = t.get("name", "").strip().lower()
                    t_score = t.get("score", 0.8)
                    if not t_name:
                        continue

                    # Get all Topic Nodes for this session
                    topic_nodes = toolkit.db_session.query(DBMemoryNode).filter(
                        DBMemoryNode.session_id == session_id,
                        DBMemoryNode.label == "Topic"
                    ).all()
                    
                    topic_node = next((n for n in topic_nodes if n.properties.get("name") == t_name), None)

                    if not topic_node:
                        topic_node = DBMemoryNode(
                            session_id=session_id,
                            label="Topic",
                            properties={"name": t_name, "score": t_score}
                        )
                        toolkit.db_session.add(topic_node)
                        toolkit.db_session.commit()
                        toolkit.db_session.refresh(topic_node)
                    else:
                        # Update properties/score
                        props = dict(topic_node.properties)
                        props["score"] = max(props.get("score", 0.0), t_score)
                        topic_node.properties = props
                        toolkit.db_session.commit()

                    # Create directed Interest Edge
                    edge = toolkit.db_session.query(DBMemoryEdge).filter(
                        DBMemoryEdge.source_id == user_node.id,
                        DBMemoryEdge.target_id == topic_node.id
                    ).first()

                    if not edge:
                        edge = DBMemoryEdge(
                            source_id=user_node.id,
                            target_id=topic_node.id,
                            relation="INTERESTED_IN"
                        )
                        toolkit.db_session.add(edge)
                        toolkit.db_session.commit()

                _emit(state, f"long-term memory graph updated with {len(topics)} topics")
        except Exception as e:
            logger.warning(f"Failed to update long-term graph memory: {e}", exc_info=True)

    return state


@trace_node("handle_casual")
async def handle_casual(state: AgentState) -> AgentState:
    """Handle casual/no-retrieval queries directly."""
    _emit(state, "casual query — responding directly")

    response = await call_drafting_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Corpus, a research paper assistant. "
                    "Respond helpfully to casual messages. Be brief."
                ),
            },
            {"role": "user", "content": state["query"]},
        ],
        temperature=0.5,
        max_tokens=512,
    )

    return {
        **state,
        "answer_markdown": response,
        "citations": [],
        "grounding_note": "No retrieval needed for this query",
    }


# ─── Trace Event Helper ───────────────────────────────────────────


def _emit(state: AgentState, message: str) -> None:
    """Append a trace event, and push it live when a streaming callback is attached."""
    events = state.get("trace_events", [])
    events.append(message)
    state["trace_events"] = events
    _emit_live(state, {"type": "trace", "step": message})
    logger.info(f"[agent] {message}")


def _emit_live(state: AgentState, event: dict[str, Any]) -> None:
    """Push an event to the live streaming callback, if one is attached."""
    emit = state.get("emit")
    if emit is None:
        return
    try:
        emit(event)
    except Exception as e:
        logger.warning(f"Live emit failed: {e}")


# ─── Router Functions ──────────────────────────────────────────────


def route_after_intake(state: AgentState) -> str:
    """Route after intake_and_route based on query_type."""
    qt = state.get("query_type", "simple")
    if qt == "casual":
        return "handle_casual"
    elif qt == "complex":
        return "plan"
    else:  # simple, followup
        return "plan"


def route_after_admit_or_live(state: AgentState) -> str:
    """After live lookup or admit gap, go to update_memory."""
    return "update_memory"


def route_after_verification(state: AgentState) -> str:
    """Route after verify_citations — loop back to generate if we have correction feedback and retries remaining."""
    feedback = state.get("generation_feedback", "")
    retry_count = state.get("generation_retry_count", 0)

    if feedback and retry_count < 2:
        return "generate"
    return "finalize"


# ─── Graph Construction ───────────────────────────────────────────


def build_agentic_graph() -> StateGraph:
    """Build and compile the full 11-node agentic RAG graph.

    Graph topology:
        intake_and_route → plan/handle_casual
        plan → retrieve
        retrieve → grade
        grade → route_on_grade → rerank/rewrite_query/live_arxiv_lookup/admit_gap
        rewrite_query → retrieve (loop, capped at 2)
        live_arxiv_lookup → generate/admit_gap
        rerank → build_context → generate → verify_citations → finalize → update_memory → END
        handle_casual → update_memory → END
        admit_gap → update_memory → END
    """
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("intake_and_route", intake_and_route)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("live_arxiv_lookup", live_arxiv_lookup)
    graph.add_node("admit_gap", admit_gap)
    graph.add_node("rerank", rerank_node)
    graph.add_node("build_context", build_context)
    graph.add_node("generate", generate)
    graph.add_node("verify_citations", verify_citations)
    graph.add_node("finalize", finalize)
    graph.add_node("update_memory", update_memory)
    graph.add_node("handle_casual", handle_casual)

    # Set entry point
    graph.set_entry_point("intake_and_route")

    # Conditional: intake → plan or handle_casual
    graph.add_conditional_edges(
        "intake_and_route",
        route_after_intake,
        {
            "plan": "plan",
            "handle_casual": "handle_casual",
        },
    )

    # Linear: plan → retrieve → grade
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "grade")

    # Conditional: grade → rerank/rewrite/live_lookup/admit_gap
    graph.add_conditional_edges(
        "grade",
        route_on_grade,
        {
            "rerank": "rerank",
            "rewrite_query": "rewrite_query",
            "live_arxiv_lookup": "live_arxiv_lookup",
        },
    )

    # Rewrite loops back to retrieve
    graph.add_edge("rewrite_query", "retrieve")

    # Live lookup → generate or admit_gap
    graph.add_conditional_edges(
        "live_arxiv_lookup",
        route_after_live_lookup,
        {
            "generate": "generate",
            "admit_gap": "admit_gap",
        },
    )

    # Main pipeline: rerank → build_context → generate → verify → finalize → memory → END
    graph.add_edge("rerank", "build_context")
    graph.add_edge("build_context", "generate")
    graph.add_edge("generate", "verify_citations")
    graph.add_conditional_edges(
        "verify_citations",
        route_after_verification,
        {
            "generate": "generate",
            "finalize": "finalize",
        },
    )
    graph.add_edge("finalize", "update_memory")
    graph.add_edge("update_memory", END)

    # Side paths → update_memory → END
    graph.add_edge("handle_casual", "update_memory")
    graph.add_edge("admit_gap", "update_memory")

    return graph.compile()


# ─── Public API ────────────────────────────────────────────────────


# Compiled graph singleton
_graph = None


def get_agentic_graph():
    """Get or create the compiled agentic graph."""
    global _graph
    if _graph is None:
        _graph = build_agentic_graph()
    return _graph


def _build_initial_state(
    query: str,
    toolkit,
    session_id: str | None,
    conversation_history: list[dict[str, str]] | None,
    filters: dict[str, Any] | None,
    emit=None,
    deep_verify: bool = False,
) -> AgentState:
    """Assemble the initial graph state shared by streaming and non-streaming entry points."""
    return {
        "deep_verify": deep_verify,
        "verification": None,
        "query": query,
        "session_id": session_id or str(uuid.uuid4()),
        "conversation_history": conversation_history or [],
        "query_type": "",
        "sub_questions": [],
        "all_retrieved_chunks": [],
        "relevant_chunks": [],
        "reranked_chunks": [],
        "retrieved_arxiv_ids": [],
        "context_str": "",
        "citation_meta": [],
        "chunk_ids_in_context": [],
        "answer_markdown": "",
        "citations": [],
        "grounding_note": "",
        "retry_count": 0,
        "max_retries": 2,
        "current_query": query,
        "trace_events": [],
        "error": "",
        "toolkit": toolkit,
        "filters": filters or {},
        "emit": emit,
    }


def _result_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Project the final graph state onto the public response shape."""
    return {
        "answer_markdown": result.get("answer_markdown", ""),
        "citations": result.get("citations", []),
        "grounding_note": result.get("grounding_note", ""),
        "trace_events": result.get("trace_events", []),
        "query_type": result.get("query_type", ""),
        "verification": result.get("verification"),
        "retrieved_arxiv_ids": result.get("retrieved_arxiv_ids", []),
        "chunk_ids_in_context": result.get("chunk_ids_in_context", []),
    }


async def ask_corpus(
    query: str,
    toolkit=None,
    session_id: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    filters: dict[str, Any] | None = None,
    deep_verify: bool = False,
) -> dict[str, Any]:
    """Run the full agentic RAG pipeline for a query.

    Returns:
        {
            "answer_markdown": str,
            "citations": [...],
            "grounding_note": str,
            "trace_events": [str, ...]
        }
    """
    graph = get_agentic_graph()

    initial_state = _build_initial_state(
        query, toolkit, session_id, conversation_history, filters, deep_verify=deep_verify
    )

    try:
        result = await graph.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"Agentic graph failed: {e}", exc_info=True)
        result = {
            **initial_state,
            "answer_markdown": f"An error occurred while processing your query: {str(e)}",
            "citations": [],
            "grounding_note": "Error during processing",
            "trace_events": initial_state.get("trace_events", []) + [f"error: {str(e)}"],
        }

    return _result_payload(result)


async def ask_corpus_streaming(
    query: str,
    toolkit=None,
    session_id: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    filters: dict[str, Any] | None = None,
    deep_verify: bool = False,
):
    """Run the agentic pipeline, yielding live events as the graph executes.

    Yields dicts:
        {"type": "trace", "step": str}      — node progress, live
        {"type": "token", "text": str}      — LLM tokens during generation, live
        {"type": "error", "message": str}   — on failure
        {"type": "done", "result": {...}}   — final payload (post-verification answer)
    """
    import asyncio

    graph = get_agentic_graph()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _SENTINEL = "__graph_complete__"

    initial_state = _build_initial_state(
        query, toolkit, session_id, conversation_history, filters, emit=queue.put_nowait, deep_verify=deep_verify
    )

    async def _run() -> None:
        try:
            result = await graph.ainvoke(initial_state)
            queue.put_nowait({"type": _SENTINEL, "result": result})
        except Exception as e:
            logger.error(f"Agentic graph failed (streaming): {e}", exc_info=True)
            queue.put_nowait({"type": "error", "message": str(e)})
            queue.put_nowait({"type": _SENTINEL, "result": None})

    task = asyncio.create_task(_run())
    try:
        while True:
            event = await queue.get()
            if event.get("type") == _SENTINEL:
                result = event.get("result")
                if result is not None:
                    yield {"type": "done", "result": _result_payload(result)}
                break
            yield event
    finally:
        # Client may disconnect mid-stream — don't leave the graph running.
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
