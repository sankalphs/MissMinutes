"""MissMinutes Gradio UI — TVA cathode-amber, Loki at the center of the branches.

HF Space: sankalp/MissMinutes (CPU basic). The hero is a Three.js temporal-void
scene served by src/ui/scene_server.py at /scene and embedded as an iframe.
Design tokens in ui/DESIGN_TOKENS.md.
"""
from __future__ import annotations

import logging
from pathlib import Path

import gradio as gr

from src.config import settings
from src.graph.schema import Graph
from src.ingestion.store import Store
from src.llm.client import GMIClient
from src.search.hybrid import hybrid_search
from src.search.planner import parse_query
from src.search.synthesis import generate_answer
from src.vector.qdrant import VectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("missminutes.ui")

UI_DIR = Path(__file__).resolve().parent / "ui"
CSS = (UI_DIR / "app.css").read_text(encoding="utf-8")
HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bungee&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
"""

SCENE_IFRAME = """
<div id="hero-frame">
  <iframe src="/scene" title="The sacred timeline — a 3D view of the branching timelines"
          loading="lazy" allow="fullscreen"></iframe>
  <div class="hero-title">
    <h1>MISS MINUTES</h1>
    <p>ARCHIVE TERMINAL — EVERY BRANCH, EVERY TIMELINE, ALL EVIDENCE</p>
  </div>
</div>
"""

TIMELINES = [
    "All timelines", "MCU", "WhatIf", "Sony: Rami", "Sony: Webb",
    "Sony: SSU", "Fox: X-Men", "Defenders",
]


def search_and_answer(question: str, timeline: str):
    """Orchestrated pipeline: plan -> hybrid retrieval -> grounded synthesis."""
    if not question.strip():
        return (
            "<div id='answer'>Ask a question about the timelines to begin.</div>",
            "<div id='evidence'><div class='ev-heading'>CASE FILE — EVIDENCE</div>"
            "<div class='chunk'>Cited subtitle passages will appear here after a search.</div></div>",
            "",
        )
    try:
        store = Store()
        vs = VectorStore()
        graph = Graph()
        llm = GMIClient()

        plan = parse_query(llm, question)
        if timeline and timeline != "All timelines":
            plan.timeline = timeline.lower()

        ranked = hybrid_search(store, vs, graph, question, plan)
        result = generate_answer(llm, question, ranked)

        citations = result.get("citations", [])
        ev_rows = []
        for i, c in enumerate(citations[:6], 1):
            title = c.get("title", "?")
            text = c.get("text", "")[:220].replace("<", "&lt;")
            ev_rows.append(f"<div class='chunk'><b>[{i}] {title}</b><br/>{text}...</div>")
        evidence = (
            "<div id='evidence'><div class='ev-heading'>CASE FILE — EVIDENCE</div>"
            + "".join(ev_rows) + "</div>"
            if ev_rows
            else "<div id='evidence'><div class='ev-heading'>CASE FILE — EVIDENCE</div>"
                 "<div class='chunk'>No subtitle passages were retrievable for this query.</div></div>"
        )

        out = f"<div id='answer'>{result['answer']}"
        if result.get("uncertainty") and result["uncertainty"] != "none":
            out += f"<span class='warn'>&#9888; {result['uncertainty']}</span>"
        if result.get("sources"):
            out += (
                "<span class='src'>SOURCES: "
                + ", ".join(result["sources"][:8])
                + "</span>"
            )
        out += "</div>"

        graph.close()
        return out, evidence, f"plan: {result['plan'] if 'plan' in result else 'ok'}"
    except Exception as e:
        logger.exception("pipeline error")
        return (
            f"<div id='answer'>The archivist hit a snag: {type(e).__name__}. "
            "Try rephrasing the question.</div>",
            "",
            "",
        )


def build_app() -> gr.Blocks:
    with gr.Blocks(title="MissMinutes — Sacred Timeline Search", head=HEAD) as app:
        gr.HTML(
            "<div id='chronofile'>"
            "<span>TVA CHRONOFILE // MISSMINUTES ARCHIVE TERMINAL // FOR TIME, ALWAYS.</span>"
            "<span class='cf-right'>BRANCH STATUS: <b>STABLE</b> &nbsp;//&nbsp; ARCHIVIST: <b>ON DUTY</b></span>"
            "</div>"
        )
        gr.HTML(SCENE_IFRAME)

        with gr.Column(elem_id="query-dock"):
            gr.HTML("<div class='dock-label'>QUERY THE TIMELINE</div>")
            with gr.Row():
                q = gr.Textbox(
                    placeholder="e.g. What happened after Loki escaped with the Tesseract?",
                    label="",
                    show_label=False,
                    elem_classes="query-box",
                    lines=1,
                )
                tl = gr.Dropdown(
                    choices=TIMELINES,
                    value="All timelines",
                    label="Timeline",
                    elem_id="timeline-filter",
                )
                btn = gr.Button("Search the timeline", variant="primary")

        with gr.Row(elem_id="results-row"):
            with gr.Column(scale=3, elem_id="answer-col"):
                out = gr.HTML(
                    "<div id='answer'>Ask a question about the timelines to begin.</div>"
                )
            with gr.Column(scale=2, elem_id="evidence-col"):
                ev = gr.HTML(
                    "<div id='evidence'><div class='ev-heading'>CASE FILE — EVIDENCE</div>"
                    "<div class='chunk'>Cited subtitle passages will appear here after a search.</div></div>"
                )
        status = gr.Textbox(visible=False)

        btn.click(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        q.submit(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        gr.HTML(
            "<div class='footer'>MISSMINUTES v0.2 — knowledge graph: <b>neo4j aura</b> // "
            "vectors: <b>qdrant</b> // grounding: <b>MiniMax-M3</b> // "
            "all claims cite ingested subtitle evidence</div>"
        )
    return app


if __name__ == "__main__":
    import uvicorn

    from src.ui.scene_server import scene_app

    blocks = build_app()
    blocks.queue()
    gr.mount_gradio_app(scene_app, blocks, path="/", css=CSS, head=HEAD)
    uvicorn.run(scene_app, host="0.0.0.0", port=7860)
