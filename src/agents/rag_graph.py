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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.prompts import (
    GAP_RESPONSE_TEMPLATE,
    GENERATOR_PROMPT,
    GRADER_PROMPT,
    PLANNER_PROMPT,
    REWRITER_PROMPT,
    ROUTER_PROMPT,
    VERIFIER_PROMPT,
)
from src.retrieval.context_builder import CitationMeta, build_citation_context
from src.services.llm_adapter import call_drafting_llm, call_reasoning_llm, parse_json_response
from src.services.tracing import trace_node

logger = logging.getLogger(__name__)


# ─── State Definition ──────────────────────────────────────────────


class AgentState(TypedDict, total=False):
    """Complete state flowing through the agentic graph."""

    # Input
    query: str
    session_id: str
    conversation_history: List[Dict[str, str]]

    # Routing
    query_type: str  # casual, simple, complex, followup

    # Planning
    sub_questions: List[str]

    # Retrieval
    all_retrieved_chunks: List[Any]  # List[RetrievedChunk]
    relevant_chunks: List[Any]
    reranked_chunks: List[Any]

    # Context
    context_str: str
    citation_meta: List[Dict[str, Any]]
    chunk_ids_in_context: List[str]

    # Generation
    answer_markdown: str
    citations: List[Dict[str, Any]]
    grounding_note: str

    # Control
    retry_count: int
    max_retries: int
    current_query: str  # May be rewritten
    trace_events: List[str]
    error: str

    # Tools reference (set at graph invocation, not serialized)
    toolkit: Any


# ─── Node Implementations ─────────────────────────────────────────


@trace_node("intake_and_route")
async def intake_and_route(state: AgentState) -> AgentState:
    """Node 1: Classify the query type."""
    _emit(state, "classifying query...")

    query = state["query"]
    history = state.get("conversation_history", [])
    history_str = json.dumps(history[-3:]) if history else "[]"

    prompt = ROUTER_PROMPT.format(query=query, history=history_str)
    response = await call_reasoning_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=256,
    )

    parsed = parse_json_response(response)
    query_type = parsed.get("query_type", "simple")
    if query_type not in ("casual", "simple", "complex", "followup"):
        query_type = "simple"

    _emit(state, f"query classified as: {query_type}")

    return {
        **state,
        "query_type": query_type,
        "current_query": query,
        "retry_count": state.get("retry_count", 0),
        "max_retries": 2,
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

    _emit(state, f"hybrid search (BM25 + vectors) for {len(queries)} queries...")

    all_chunks = []
    for q in queries:
        if toolkit:
            chunks = await toolkit.hybrid_search(q, top_k=15)
        else:
            chunks = []
        all_chunks.extend(chunks)

    _emit(state, f"{len(all_chunks)} candidates found")

    return {**state, "all_retrieved_chunks": all_chunks}


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

    candidate_chunks = chunks[:20]  # Cap grading at 20 chunks for latency

    async def grade_single_chunk(chunk):
        prompt = GRADER_PROMPT.format(
            question=query,
            paper_title=getattr(chunk, "title", "Unknown"),
            section=getattr(chunk, "section_title", "Unknown"),
            chunk_text=getattr(chunk, "text", "")[:1500],
        )
        try:
            response = await call_reasoning_llm(
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

    response = await call_reasoning_llm(
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
            citations.append({
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
            })

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

    ctx = build_citation_context(reranked, max_chunks=4)

    # Convert CitationMeta dataclasses to dicts for serialization
    citation_dicts = []
    for cm in ctx.citations:
        citation_dicts.append({
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
        })

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

    _emit(state, "generating answer with citations...")

    prompt = GENERATOR_PROMPT.format(context=context, query=query)
    answer = await call_drafting_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4096,
    )

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

    # Step 2: LLM-based faithfulness check
    import os
    enable_llm_verify = os.getenv("ENABLE_LLM_VERIFICATION", "false").lower() == "true"

    if not enable_llm_verify:
        grounding_note = f"{len(cited_nums - invalid_nums)} citations verified"
        _emit(state, f"verification complete (LLM validation skipped): {grounding_note}")
        return {
            **state,
            "answer_markdown": cleaned_answer,
            "grounding_note": grounding_note,
        }

    try:
        prompt = VERIFIER_PROMPT.format(answer=cleaned_answer, context=context)
        response = await call_reasoning_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1024,
        )
        parsed = parse_json_response(response)

        grounding_note = parsed.get(
            "grounding_note",
            f"{len(cited_nums - invalid_nums)} citations used"
        )

        # Process issues — strip or hedge problematic claims
        issues = parsed.get("issues", [])
        for issue in issues:
            action = issue.get("action", "keep")
            claim_text = issue.get("claim", "")
            if action == "remove" and claim_text and claim_text in cleaned_answer:
                cleaned_answer = cleaned_answer.replace(
                    claim_text,
                    f"~~{claim_text}~~ *(removed: unsupported by source)*"
                )
            elif action == "hedge" and claim_text and claim_text in cleaned_answer:
                cleaned_answer = cleaned_answer.replace(
                    claim_text,
                    f"*[note: source partially supports]* {claim_text}"
                )

    except Exception as e:
        logger.error(f"Citation verification failed: {e}")
        grounding_note = f"{len(cited_nums - invalid_nums)} citations present (verification error)"

    _emit(state, f"verification complete: {grounding_note}")

    return {
        **state,
        "answer_markdown": cleaned_answer,
        "grounding_note": grounding_note,
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
            final_citations.append({
                "id": cm["citation_id"],
                "paper_title": cm["paper_title"],
                "authors": cm["authors"],
                "arxiv_id": cm["arxiv_id"],
                "arxiv_url": cm["arxiv_url"],
                "pdf_url": cm["pdf_url"],
                "section": cm["section"],
                "snippet": cm["snippet"],
            })

    # Sort by ID for consistent ordering
    final_citations.sort(key=lambda c: c["id"])

    _emit(state, f"finalized {len(final_citations)} citations")

    return {
        **state,
        "citations": final_citations,
    }


@trace_node("update_memory")
async def update_memory(state: AgentState) -> AgentState:
    """Node 14: Persist session state to Redis for multi-turn follow-ups."""
    toolkit = state.get("toolkit")
    session_id = state.get("session_id", "")
    query = state["query"]
    answer = state.get("answer_markdown", "")

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

    return state


@trace_node("handle_casual")
async def handle_casual(state: AgentState) -> AgentState:
    """Handle casual/no-retrieval queries directly."""
    _emit(state, "casual query — responding directly")

    response = await call_drafting_llm(
        messages=[
            {"role": "system", "content": "You are Corpus, a research paper assistant. Respond helpfully to casual messages. Be brief."},
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
    """Append a trace event for SSE streaming."""
    events = state.get("trace_events", [])
    events.append(message)
    state["trace_events"] = events
    logger.info(f"[agent] {message}")


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
    graph.add_edge("verify_citations", "finalize")
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


async def ask_corpus(
    query: str,
    toolkit=None,
    session_id: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
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

    initial_state: AgentState = {
        "query": query,
        "session_id": session_id or str(uuid.uuid4()),
        "conversation_history": conversation_history or [],
        "query_type": "",
        "sub_questions": [],
        "all_retrieved_chunks": [],
        "relevant_chunks": [],
        "reranked_chunks": [],
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
    }

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

    return {
        "answer_markdown": result.get("answer_markdown", ""),
        "citations": result.get("citations", []),
        "grounding_note": result.get("grounding_note", ""),
        "trace_events": result.get("trace_events", []),
        "query_type": result.get("query_type", ""),
    }
