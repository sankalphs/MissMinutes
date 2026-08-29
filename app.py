"""MissMinutes Gradio UI — TVA cathode-amber, Loki at the center of the branches.

HF Space: sankalp/MissMinutes (CPU basic). Runs FastAPI under Gradio via
mount, or standalone. Design tokens in ui/DESIGN_TOKENS.md.
"""
from __future__ import annotations

import logging

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

CSS = """
:root {
  --void: #0B0A14; --panel: #14121F; --amber: #FFB74A;
  --amber-dim: #B87A2A; --chronoline: #8A86B8; --paper: #EDE6D6; --danger: #E4572E;
}
.gradio-container { background: var(--void) !important; font-family: 'IBM Plex Sans', sans-serif !important; }
#chronofile {
  background: linear-gradient(180deg, #1A1626 0%, var(--panel) 100%);
  border: 1px solid var(--amber-dim);
  border-radius: 4px;
  padding: 10px 18px;
  font-family: 'IBM Plex Mono', monospace;
  color: var(--amber);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-size: 12px;
  position: relative;
  overflow: hidden;
}
#chronofile::after {
  content: '';
  position: absolute; inset: 0;
  background: repeating-linear-gradient(0deg, transparent 0 2px, rgba(255,183,74,0.03) 2px 3px);
  pointer-events: none;
}
#hero {
  text-align: center;
  background:
    radial-gradient(ellipse 60% 55% at 50% 42%, rgba(255,183,74,0.14) 0%, transparent 65%),
    var(--void);
  border: 1px solid #2A2440;
  border-radius: 6px;
  padding: 28px 12px 6px;
}
#hero h1 {
  font-family: 'Bungee', cursive;
  color: var(--amber);
  font-size: clamp(28px, 5vw, 44px);
  margin: 0;
  letter-spacing: 0.06em;
}
#hero p { color: var(--chronoline); font-size: 13px; margin: 6px 0 12px; }
#branches svg { width: 100%; height: 210px; display: block; }
#hero .loki-dot { fill: var(--amber); }
.query-box textarea {
  background: var(--panel) !important;
  color: var(--paper) !important;
  border: 1px solid var(--amber-dim) !important;
  font-size: 15px !important;
}
#answer {
  background: var(--panel);
  border: 1px solid #2A2440;
  border-left: 3px solid var(--amber);
  border-radius: 4px;
  padding: 16px 20px;
  color: var(--paper);
  min-height: 120px;
  font-size: 14.5px;
  line-height: 1.55;
}
#answer .src { font-family: 'IBM Plex Mono', monospace; color: var(--amber-dim); font-size: 11px; }
#evidence .chunk {
  background: #100E1A; border: 1px solid #262038; border-radius: 3px;
  padding: 8px 10px; margin: 6px 0; color: var(--chronoline); font-size: 12px;
}
#evidence .chunk b { color: var(--paper); }
.footer { color: #55506E; font-size: 11px; text-align: center; font-family: 'IBM Plex Mono', monospace; }
"""

BRANCHES_SVG = """
<svg id="branches" viewBox="0 0 800 210" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Loki at the center of branching timelines">
  <defs>
    <marker id="arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#8A86B8"/>
    </marker>
  </defs>
  <line x1="400" y1="60" x2="400" y2="180" stroke="#FFB74A" stroke-width="2.5" marker-end="url(#arrow)"/>
  <text x="414" y="72" fill="#B87A2A" font-family="IBM Plex Mono" font-size="11">SACRED TIMELINE</text>
  <path d="M400 90 C 300 100, 220 110, 140 130" stroke="#8A86B8" stroke-width="1.4" fill="none" stroke-dasharray="5 4" marker-end="url(#arrow)"/>
  <path d="M400 90 C 480 105, 560 115, 640 140" stroke="#8A86B8" stroke-width="1.4" fill="none" stroke-dasharray="5 4" marker-end="url(#arrow)"/>
  <path d="M400 120 C 330 135, 290 150, 250 175" stroke="#5B5680" stroke-width="1.2" fill="none" stroke-dasharray="3 5" marker-end="url(#arrow)"/>
  <path d="M400 120 C 470 138, 520 155, 570 180" stroke="#5B5680" stroke-width="1.2" fill="none" stroke-dasharray="3 5" marker-end="url(#arrow)"/>
  <text x="112" y="146" fill="#8A86B8" font-family="IBM Plex Mono" font-size="10">WHAT IF...</text>
  <text x="600" y="156" fill="#8A86B8" font-family="IBM Plex Mono" font-size="10">FOX X-MEN</text>
  <text x="238" y="190" fill="#5B5680" font-family="IBM Plex Mono" font-size="10">SONY</text>
  <text x="548" y="195" fill="#5B5680" font-family="IBM Plex Mono" font-size="10">DEFENDERS</text>
  <circle class="loki-dot" cx="400" cy="58" r="6">
    <animate attributeName="r" values="5;7;5" dur="3s" repeatCount="indefinite"/>
  </circle>
  <circle cx="400" cy="58" r="14" fill="none" stroke="#FFB74A" stroke-opacity="0.35">
    <animate attributeName="r" values="10;22;10" dur="3s" repeatCount="indefinite"/>
    <animate attributeName="stroke-opacity" values="0.5;0;0.5" dur="3s" repeatCount="indefinite"/>
  </circle>
  <text x="400" y="40" fill="#EDE6D6" font-family="Bungee" font-size="14" text-anchor="middle">L OKI</text>
</svg>
"""


def search_and_answer(question: str, timeline: str):
    """Orchestrated pipeline: plan -> hybrid retrieval -> grounded synthesis."""
    if not question.strip():
        return "Ask a question about the timelines to begin.", ""
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
        src_html = ""
        if citations:
            rows = []
            for i, c in enumerate(citations[:6], 1):
                title = c.get("title", "?")
                text = c.get("text", "")[:220].replace("<", "&lt;")
                rows.append(
                    f"<div class='chunk'><b>[{i}] {title}</b><br/>{text}...</div>"
                )
            src_html = "<div id='evidence'>" + "".join(rows) + "</div>"

        out = f"<div id='answer'>{result['answer']}"
        if result.get("uncertainty") and result["uncertainty"] != "none":
            out += f"<br/><br/><span class='src'>&#9888; {result['uncertainty']}</span>"
        if result.get("sources"):
            out += (
                "<br/><br/><span class='src'>SOURCES: "
                + ", ".join(result["sources"][:8])
                + "</span>"
            )
        out += "</div>" + src_html
        graph.close()
        return out, f"plan: {result['plan'] if 'plan' in result else 'ok'}"
    except Exception as e:
        logger.exception("pipeline error")
        return f"<div id='answer'>The archivist hit a snag: {type(e).__name__}. Try rephrasing the question.</div>", ""


def build_app() -> gr.Blocks:
    with gr.Blocks(css=CSS, title="MissMinutes — Sacred Timeline Search") as app:
        gr.HTML(
            "<div id='chronofile'>TVA CHRONOFILE // MISSMINUTES ARCHIVE TERMINAL // FOR TIME, ALWAYS.</div>"
        )
        with gr.Column(elem_id="hero"):
            gr.HTML(BRANCHES_SVG)
            gr.HTML("<h1>MISS MINUTES</h1>")
            gr.HTML(
                "<p>Search every branch of the sacred timeline — MCU, Sony, Fox, and the streets where the Defenders walk. Every answer is grounded in subtitle evidence.</p>"
            )
        with gr.Row():
            with gr.Column(scale=3):
                q = gr.Textbox(
                    placeholder="e.g. What happened after Loki escaped with the Tesseract?",
                    label="Question",
                    elem_classes="query-box",
                    lines=1,
                )
            with gr.Column(scale=1):
                tl = gr.Dropdown(
                    choices=["All timelines", "MCU", "WhatIf", "Sony: Rami", "Sony: Webb", "Sony: SSU", "Fox: X-Men", "Defenders"],
                    value="All timelines",
                    label="Timeline filter",
                )
        btn = gr.Button("Search the timeline", variant="primary")
        out = gr.HTML("<div id='answer'>Ask a question about the timelines to begin.</div>")
        status = gr.Textbox(visible=False)

        btn.click(search_and_answer, inputs=[q, tl], outputs=[out, status])
        q.submit(search_and_answer, inputs=[q, tl], outputs=[out, status])
        gr.HTML(
            "<div class='footer'>MISSMINUTES v0.1 — knowledge graph: neo4j aura // vectors: qdrant // "
            "grounding: MiniMax-M3. All claims cite ingested subtitle evidence.</div>"
        )
    return app


if __name__ == "__main__":
    build_app().launch(server_name="0.0.0.0", server_port=7860)
