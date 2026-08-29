"""MissMinutes — a cinematic multiverse archive.

Deep-blue void, warm paper text, one white-gold timeline filament. The
hero is a Three.js scene served by src/ui/scene_server.py at /scene and
embedded full-bleed; search + editorial content sit in a centered
readable column. Design tokens in ui/DESIGN_TOKENS.md.
"""
from __future__ import annotations

import html
import logging
from pathlib import Path

import gradio as gr

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
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@200..800&family=Instrument+Serif:ital@0;1&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
"""

SCENE_IFRAME = """
<div id="hero" aria-label="The Sacred Timeline, with branch timelines diverging into deep space">
  <iframe src="/scene" title="The Sacred Timeline — a cinematic view of the branching timelines"
          loading="eager" allow="fullscreen"></iframe>
  <div class="brandblock">
    <h1>MISS<br/>MINUTES</h1>
    <p class="tagline">the multiverse archive</p>
    <p class="lede">Search every timeline, branch, event and universe.</p>
  </div>
</div>
"""

TIMELINES = [
    "All timelines", "MCU", "WhatIf", "Sony: Rami", "Sony: Webb",
    "Sony: SSU", "Fox: X-Men", "Defenders",
]

TOPBAR = """
<div id="topbar">
  <span class="brand">MISS MINUTES</span>
  <span class="status"><span class="dot"></span>SACRED TIMELINE · STABLE</span>
</div>
"""

SEARCHZONE_HEADING = """
<div class="ask">Ask <em>the timeline</em></div>
"""

EXAMPLES = [
    "What happened after Loki escaped with the Tesseract?",
    "How are the Fox X-Men connected to the multiverse?",
    "Which Spider-Man universes exist?",
]

# evidence title -> 3D branch key (kept at this adapter boundary)
BRANCH_KEYS = {
    "whatif": "whatif", "what if": "whatif",
    "fox": "fox", "x-men": "fox", "xmen": "fox",
    "sony": "sony", "spider": "sony", "spider-man": "sony", "spiderman": "sony",
    "defenders": "defenders", "daredevil": "defenders", "jessica jones": "defenders",
    "luke cage": "defenders", "iron fist": "defenders", "punisher": "defenders",
    "mcu": "mcu",
}


def _branch_key(title: str) -> str:
    t = title.lower()
    for frag, key in BRANCH_KEYS.items():
        if frag in t:
            return key
    return ""


def _ev_row(i: int, c: dict) -> str:
    title = html.escape(c.get("title", "?"))
    text = html.escape(c.get("text", "")[:200])
    key = _branch_key(c.get("title", ""))
    data = f' data-timeline="{key}"' if key else ""
    meta = c.get("chunk_id", "")
    return (
        f"<div class='chunk'{data}>"
        f"<span class='num'>{i:02d}</span>"
        f"<span><b>{title}</b>"
        f"<span class='meta'>{html.escape(meta)}</span>"
        f"<span class='quote'>{text}&hellip;</span></span></div>"
    )


def _empty_answer() -> str:
    return (
        "<div id='answer'><p>Search the archive and the answer will appear here "
        "&mdash; grounded in ingested subtitle evidence, sources cited.</p></div>"
    )


def _empty_evidence() -> str:
    return (
        "<div id='evidence'><p class='ev-heading'>Evidence from the timeline</p>"
        "<p class='ev-sub'>Cited passages arrive here after a search.</p></div>"
    )


def search_and_answer(question: str, timeline: str):
    """Orchestrated pipeline: plan -> hybrid retrieval -> grounded synthesis."""
    if not question.strip():
        return _empty_answer(), _empty_evidence(), ""
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
        ev_rows = [_ev_row(i, c) for i, c in enumerate(citations[:6], 1)]
        evidence = (
            "<div id='evidence'><p class='ev-heading'>Evidence from the timeline</p>"
            + "".join(ev_rows) + "</div>"
            if ev_rows
            else "<div id='evidence'><p class='ev-heading'>Evidence from the timeline</p>"
                 "<p class='ev-sub'>No subtitle passages were retrievable for this query.</p></div>"
        )

        answer_html = "<br/>".join(
            html.escape(p) for p in result["answer"].split("\n") if p.strip()
        )
        out = f"<div id='answer'><p>{answer_html}</p>"
        if result.get("uncertainty") and result["uncertainty"] != "none":
            out += f"<span class='warn'>&#9888; {html.escape(result['uncertainty'])}</span>"
        if result.get("sources"):
            out += (
                "<span class='src'>Sources — "
                + html.escape(", ".join(result["sources"][:8]))
                + "</span>"
            )
        out += "</div>"

        graph.close()
        return out, evidence, f"plan: {result.get('plan', 'ok')}"
    except Exception as e:
        logger.exception("pipeline error")
        return (
            "<div id='answer'><p>The archivist hit a snag: "
            f"{type(e).__name__}. Try rephrasing the question.</p></div>",
            "",
            "",
        )


def run_example(question: str, timeline: str):
    """Fill-and-run: echo the query into the input, then answer it."""
    return question, *search_and_answer(question, timeline)


def build_app() -> gr.Blocks:
    with gr.Blocks(title="MissMinutes — the multiverse archive", head=HEAD) as app:
        gr.HTML(TOPBAR)
        gr.HTML(SCENE_IFRAME)

        with gr.Column(elem_id="searchzone"):
            gr.HTML(SEARCHZONE_HEADING)
            with gr.Row(elem_id="searchrow"):
                q = gr.Textbox(
                    placeholder="Search across every branch and universe…",
                    label="",
                    show_label=False,
                    elem_classes="query-box",
                    lines=1,
                )
                btn = gr.Button("Search", variant="primary", elem_id="searchbtn")
            tl = gr.Dropdown(
                choices=TIMELINES,
                value="All timelines",
                label="",
                show_label=False,
                elem_id="timeline-filter",
            )

        with gr.Column(elem_id="examples"):
            gr.HTML("<div class='ex-label'>Try exploring</div>")
            ex_buttons = []
            for ex in EXAMPLES:
                ex_buttons.append(gr.Button(ex, variant="secondary"))

        gr.HTML("<div id='read'><div class='divider'></div></div>")
        out = gr.HTML(_empty_answer())
        ev = gr.HTML(_empty_evidence())
        status = gr.Textbox(visible=False)

        gr.HTML(
            "<div id='colophon'>MISSMINUTES &mdash; knowledge graph: <b>neo4j aura</b> &nbsp;&middot;&nbsp; "
            "vectors: <b>qdrant</b> &nbsp;&middot;&nbsp; grounding: <b>MiniMax-M3</b> &nbsp;&middot;&nbsp; "
            "every claim cites subtitle evidence</div>"
        )

        btn.click(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        q.submit(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        for i, (exb, ex_text) in enumerate(zip(ex_buttons, EXAMPLES)):
            exb.click(
                run_example,
                inputs=[gr.Textbox(value=ex_text, visible=False), tl],
                outputs=[q, out, ev, status],
            )
    return app


if __name__ == "__main__":
    import uvicorn

    from src.ui.scene_server import scene_app

    blocks = build_app()
    blocks.queue()
    gr.mount_gradio_app(scene_app, blocks, path="/", css=CSS, head=HEAD)
    uvicorn.run(scene_app, host="0.0.0.0", port=7860)
