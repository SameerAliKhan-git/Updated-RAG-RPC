"""Corpus — Gradio Web Application.

Implements the zero.xyz-inspired design brief:
- Dark, terminal-native aesthetic with >_ corpus wordmark
- Live Agent Trace panel driven by real SSE events
- Citation chips with hover previews
- Newsreader serif for answers, JetBrains Mono for trace
- Warm amber (Highlighter) for citations, Signal blue for agent activity

Run standalone:
    python -m src.clients.gradio_app
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Generator, List, Optional, Tuple

import gradio as gr
import httpx

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────

API_BASE = os.getenv("CORPUS_API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")

# ── Design Tokens ────────────────────────────────────────────────

TOKENS = {
    "void": "#000000",       # Background (Pure Deep Black)
    "graphite": "#121214",   # Surface
    "line": "#222222",       # Border (Thin Charcoal)
    "paper": "#F5F5F7",      # Primary text (Warm off-white)
    "pencil": "#86868B",     # Muted text (Slate/Graphite)
    "highlighter": "#E8B325",  # Citation accent (amber)
    "signal": "#4CC9F0",     # Agent activity accent (blue)
}

# ── Custom CSS ───────────────────────────────────────────────────

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,700&family=Newsreader:opsz,wght@6..72,400;6..72,500&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Global ── */
.gradio-container {
    background: #000000 !important;
    font-family: 'Geist', system-ui, -apple-system, sans-serif !important;
    max-width: 1200px !important;
    margin: 0 auto !important;
}

.dark {
    --background-fill-primary: #000000 !important;
    --background-fill-secondary: #121214 !important;
    --border-color-primary: #222222 !important;
    --body-text-color: #F5F5F7 !important;
    --body-text-color-subdued: #86868B !important;
}

/* ── Wordmark ── */
.wordmark {
    font-family: 'JetBrains Mono', monospace !important;
    color: #F5F5F7;
    font-size: 1.2rem;
    font-weight: 500;
    letter-spacing: 0.05em;
}
.wordmark .prompt-mark {
    color: #4CC9F0;
}

/* ── Hero ── */
.hero-title {
    font-family: 'Fraunces', serif !important;
    font-size: 3rem !important;
    font-weight: 700 !important;
    color: #F5F5F7 !important;
    text-align: center;
    margin: 2rem 0 0.5rem;
    line-height: 1.2;
    letter-spacing: -0.03em;
}
.hero-subtitle {
    font-family: 'Newsreader', serif !important;
    font-size: 1.2rem !important;
    color: #86868B !important;
    text-align: center;
    margin-bottom: 1rem;
}
.stat-strip {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    color: #4CC9F0 !important;
    text-align: center;
    margin-bottom: 1.5rem;
    letter-spacing: 0.02em;
}

/* ── Input ── */
.query-input textarea {
    background: #121214 !important;
    border: 1px solid #222222 !important;
    border-radius: 12px !important;
    color: #F5F5F7 !important;
    font-size: 1.05rem !important;
    padding: 1rem 1.25rem !important;
    min-height: 56px !important;
}
.query-input textarea:focus {
    border-color: #E8B325 !important;
    box-shadow: 0 0 0 2px rgba(232, 179, 37, 0.15) !important;
}

/* ── Quick Action Pills ── */
.pill-btn {
    background: #121214 !important;
    border: 1px solid #222222 !important;
    color: #86868B !important;
    border-radius: 20px !important;
    font-size: 0.85rem !important;
    padding: 0.4rem 1rem !important;
    cursor: pointer;
    transition: all 0.2s ease;
}
.pill-btn:hover {
    border-color: #E8B325 !important;
    color: #F5F5F7 !important;
    background: rgba(232, 179, 37, 0.08) !important;
}

/* ── Live Agent Trace Panel ── */
.trace-panel {
    background: #121214 !important;
    border: 1px solid #222222 !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    color: #86868B !important;
    min-height: 200px !important;
    max-height: 350px !important;
    overflow-y: auto !important;
    line-height: 1.8;
}
.trace-panel .trace-line {
    padding: 2px 0;
}
.trace-panel .trace-prefix {
    color: #4CC9F0;
}
.trace-panel .trace-text {
    color: #86868B;
}
.trace-panel .trace-active {
    color: #F5F5F7;
    animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

/* ── Answer Panel ── */
.answer-panel {
    font-family: 'Newsreader', serif !important;
    font-size: 1.05rem !important;
    color: #F5F5F7 !important;
    line-height: 1.75 !important;
    background: #121214 !important;
    border: 1px solid #222222 !important;
    border-radius: 12px !important;
    padding: 1.25rem !important;
}

/* ── Citation Chips ── */
.citation-chip {
    display: inline-block;
    background: rgba(232, 179, 37, 0.12);
    color: #E8B325;
    border: 1px solid rgba(232, 179, 37, 0.3);
    border-radius: 4px;
    padding: 1px 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    font-weight: 500;
    text-decoration: none;
    cursor: pointer;
    transition: all 0.15s ease;
    margin: 0 2px;
}
.citation-chip:hover {
    background: rgba(232, 179, 37, 0.25);
    border-color: #E8B325;
}

/* ── Sources Panel ── */
.source-card {
    background: #121214;
    border: 1px solid #222222;
    border-radius: 8px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.6rem;
    transition: border-color 0.2s;
}
.source-card:hover {
    border-color: #E8B325;
}
.source-title {
    color: #F5F5F7;
    font-weight: 500;
    font-size: 0.95rem;
}
.source-meta {
    color: #86868B;
    font-size: 0.8rem;
    font-family: 'JetBrains Mono', monospace;
}
.source-snippet {
    color: #86868B;
    font-size: 0.85rem;
    font-style: italic;
    margin-top: 4px;
}

/* ── Submit Button ── */
.submit-btn {
    background: #E8B325 !important;
    color: #000000 !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    padding: 0.6rem 1.5rem !important;
    transition: all 0.2s;
}
.submit-btn:hover {
    background: #d4a01f !important;
    box-shadow: 0 0 12px rgba(232, 179, 37, 0.25) !important;
}

/* ── Grounding Note ── */
.grounding-note {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: #4CC9F0;
    background: rgba(76, 201, 240, 0.08);
    border: 1px solid rgba(76, 201, 240, 0.2);
    border-radius: 6px;
    padding: 0.4rem 0.8rem;
    display: inline-block;
    margin-top: 0.5rem;
}

/* ── Accessibility ── */
@media (prefers-reduced-motion: reduce) {
    .trace-panel .trace-active { animation: none; }
    .citation-chip, .source-card, .pill-btn, .submit-btn { transition: none; }
}
@media (max-width: 768px) {
    .hero-title { font-size: 2rem !important; }
    .gradio-container { padding: 0 1rem !important; }
}
"""

THEME = gr.themes.Base(
    primary_hue=gr.themes.Color(
        c50="#fefce8", c100="#fef9c3", c200="#fef08a", c300="#fde047",
        c400="#facc15", c500="#E8B325", c600="#ca8a04", c700="#a16207",
        c800="#854d0e", c900="#713f12", c950="#422006",
    ),
    neutral_hue=gr.themes.Color(
        c50="#f8fafc", c100="#f1f5f9", c200="#e2e8f0", c300="#cbd5e1",
        c400="#86868B", c500="#64748b", c600="#475569", c700="#334155",
        c800="#121214", c900="#0f172a", c950="#000000",
    ),
)


# ── API Helpers ──────────────────────────────────────────────────


def _get_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def _get_stats() -> str:
    """Fetch live stats from the API."""
    try:
        resp = httpx.get(
            f"{API_BASE}/api/v1/papers?page=1&per_page=1",
            headers=_get_headers(),
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total", 0)
            return f"{total:,} papers indexed"
    except Exception:
        pass
    return "connecting..."


def _format_trace(events: List[str]) -> str:
    """Format trace events for the trace panel."""
    if not events:
        return '<div class="trace-panel"><span class="trace-prefix">&gt; </span><span class="trace-text">waiting for query...</span></div>'

    lines = []
    for i, event in enumerate(events):
        is_last = i == len(events) - 1
        css_class = "trace-active" if is_last else "trace-text"
        lines.append(f'<div class="trace-line"><span class="trace-prefix">&gt; </span><span class="{css_class}">{event}</span></div>')

    return f'<div class="trace-panel">{"".join(lines)}</div>'


def _format_answer(answer: str, citations: List[dict]) -> str:
    """Format the answer with clickable citation chips."""
    import re

    if not answer:
        return ""

    formatted = answer

    # Replace [N] markers with clickable citation chips
    def replace_citation(match):
        num = match.group(1)
        citation = next((c for c in citations if str(c.get("id")) == num), None)
        if citation:
            url = citation.get("arxiv_url", "#")
            title = citation.get("paper_title", "")
            snippet = citation.get("snippet", "")[:100]
            return f'<a class="citation-chip" href="{url}" target="_blank" title="{title}: {snippet}">[{num}]</a>'
        return f'<span class="citation-chip">[{num}]</span>'

    formatted = re.sub(r"\[(\d+)\]", replace_citation, formatted)

    # Convert markdown bold to HTML
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", formatted)
    # Convert markdown bullets
    formatted = re.sub(r"^- (.+)$", r"• \1", formatted, flags=re.MULTILINE)
    # Line breaks
    formatted = formatted.replace("\n\n", "<br><br>").replace("\n", "<br>")

    return f'<div class="answer-panel">{formatted}</div>'


def _format_sources(citations: List[dict]) -> str:
    """Format the sources panel with citation cards."""
    if not citations:
        return ""

    cards = []
    for c in citations:
        authors = ", ".join(c.get("authors", [])[:3])
        if len(c.get("authors", [])) > 3:
            authors += " et al."
        arxiv_url = c.get("arxiv_url", "#")
        pdf_url = c.get("pdf_url", "#")

        cards.append(f"""
        <div class="source-card">
            <div class="source-title">[{c.get("id")}] {c.get("paper_title", "Unknown")}</div>
            <div class="source-meta">{authors} · {c.get("section", "")} · <a href="{arxiv_url}" target="_blank" style="color:#E8B325">arXiv</a> · <a href="{pdf_url}" target="_blank" style="color:#E8B325">PDF</a></div>
            <div class="source-snippet">"{c.get("snippet", "")}"</div>
        </div>
        """)

    return f'<div>{"".join(cards)}</div>'


# ── Core Query Function ─────────────────────────────────────────


def run_query(query: str, session_id: str = "") -> Tuple[str, str, str, str, str]:
    """Execute query against the /ask-agentic endpoint.

    Returns: (answer_html, sources_html, trace_html, grounding_html, session_id)
    """
    if not query.strip():
        return ("", "", _format_trace([]), "", session_id)

    payload = {"query": query}
    if session_id:
        payload["session_id"] = session_id

    try:
        resp = httpx.post(
            f"{API_BASE}/api/v1/ask-agentic",
            json=payload,
            headers=_get_headers(),
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()

        answer = data.get("answer_markdown", "")
        citations = data.get("citations", [])
        trace_events = data.get("trace_events", [])
        grounding = data.get("grounding_note", "")
        sid = data.get("session_id", session_id)

        answer_html = _format_answer(answer, citations)
        sources_html = _format_sources(citations)
        trace_html = _format_trace(trace_events)
        grounding_html = f'<div class="grounding-note">✓ {grounding}</div>' if grounding else ""

        return (answer_html, sources_html, trace_html, grounding_html, sid)

    except httpx.ConnectError:
        return (
            '<div class="answer-panel" style="color:#8A8F98">Could not connect to the Corpus API. Make sure the backend is running.</div>',
            "",
            _format_trace(["error: API connection failed"]),
            "",
            session_id,
        )
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return (
            f'<div class="answer-panel" style="color:#8A8F98">Error: {str(e)}</div>',
            "",
            _format_trace([f"error: {str(e)}"]),
            "",
            session_id,
        )


def set_query(query_text: str) -> str:
    """Set query text from a pill button click."""
    return query_text


# ── Build Gradio App ─────────────────────────────────────────────


def create_app() -> gr.Blocks:
    """Build the Corpus Gradio application."""

    stats_text = _get_stats()

    with gr.Blocks(
        title="Corpus — Ask your papers anything",
    ) as app:

        # ── Hidden state ──
        session_state = gr.State("")

        # ── Wordmark ──
        gr.HTML("""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:1rem 0; border-bottom:1px solid #262B33;">
            <div class="wordmark"><span class="prompt-mark">&gt;_</span> corpus</div>
            <div style="display:flex; gap:1.5rem; align-items:center;">
                <a href="/docs" target="_blank" style="color:#8A8F98; text-decoration:none; font-size:0.9rem;">Docs</a>
                <a href="/api/v1/health" target="_blank" style="color:#8A8F98; text-decoration:none; font-size:0.9rem;">Health</a>
            </div>
        </div>
        """)

        # ── Hero Section ──
        gr.HTML(f"""
        <div class="hero-title">Ask your papers anything.</div>
        <div class="hero-subtitle">Every answer, cited straight to the source.</div>
        <div class="stat-strip">{stats_text}</div>
        """)

        # ── Query Input ──
        with gr.Row():
            query_input = gr.Textbox(
                placeholder="Ask about any paper, method, or result...",
                show_label=False,
                elem_classes=["query-input"],
                scale=5,
                lines=1,
            )
            submit_btn = gr.Button("Ask →", elem_classes=["submit-btn"], scale=1)

        # ── Quick Action Pills ──
        with gr.Row():
            pill1 = gr.Button("Summarize latest in RL", elem_classes=["pill-btn"], size="sm")
            pill2 = gr.Button("Compare attention mechanisms", elem_classes=["pill-btn"], size="sm")
            pill3 = gr.Button("What changed this week in cs.AI?", elem_classes=["pill-btn"], size="sm")
            pill4 = gr.Button("Explain scaling laws", elem_classes=["pill-btn"], size="sm")

        # ── Main Content: Trace + Answer ──
        with gr.Row():
            # Left: Live Agent Trace
            with gr.Column(scale=2):
                gr.HTML('<div style="color:#8A8F98; font-family:JetBrains Mono,monospace; font-size:0.8rem; margin-bottom:0.5rem;">LIVE AGENT TRACE</div>')
                trace_panel = gr.HTML(
                    value=_format_trace([]),
                    elem_classes=["trace-panel"],
                )

            # Right: Answer + Sources
            with gr.Column(scale=3):
                answer_panel = gr.HTML(label="Answer", elem_classes=["answer-panel"])
                grounding_display = gr.HTML()
                gr.HTML('<div style="color:#8A8F98; font-family:JetBrains Mono,monospace; font-size:0.8rem; margin:1rem 0 0.5rem;">SOURCES</div>')
                sources_panel = gr.HTML()

        # ── Event Handlers ──
        def handle_submit(query, sid):
            answer, sources, trace, grounding, new_sid = run_query(query, sid)
            return answer, sources, trace, grounding, new_sid

        submit_btn.click(
            fn=handle_submit,
            inputs=[query_input, session_state],
            outputs=[answer_panel, sources_panel, trace_panel, grounding_display, session_state],
        )
        query_input.submit(
            fn=handle_submit,
            inputs=[query_input, session_state],
            outputs=[answer_panel, sources_panel, trace_panel, grounding_display, session_state],
        )

        # Pill buttons populate the input
        pill1.click(fn=lambda: "Summarize the latest papers in reinforcement learning", outputs=query_input)
        pill2.click(fn=lambda: "Compare self-attention vs cross-attention mechanisms", outputs=query_input)
        pill3.click(fn=lambda: "What new papers were added this week in cs.AI?", outputs=query_input)
        pill4.click(fn=lambda: "Explain neural scaling laws and their implications", outputs=query_input)

    return app


# ── Entry Point ──────────────────────────────────────────────────

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=False,
        show_error=True,
        theme=THEME,
        css=CUSTOM_CSS,
    )
