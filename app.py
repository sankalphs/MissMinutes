"""MissMinutes — the TVA field terminal.

The real Time Variance Authority world: an amber cathode chrono-monitor
filling the first viewport, cream file-folder paper beneath it, condensed
mid-century signage, and Miss Minutes' voice on every line. The chrono-
scope is inline SVG drawn by ui/chronoscope.py — no iframe, no CDN, no
WebGL; click a branch to scope the search to that timeline.

Design tokens in ui/DESIGN_TOKENS.md; world contract in the HTML seed
comment below (search THESIS:).
"""
from __future__ import annotations

import html
import logging
import time
from pathlib import Path

import gradio as gr

from src.search.hybrid import hybrid_search
from src.search.planner import parse_query
from src.search.synthesis import generate_answer
from src.ui.chronoscope import chronoscope_svg, TIMELINES
from src.ui.clients import get_graph, get_llm, get_store, get_vector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("missminutes.ui")

UI_DIR = Path(__file__).resolve().parent / "ui"
CSS = (UI_DIR / "app.css").read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# World contract (impeccable seed). Audited at finish review.
# THESIS: this is the TVA's own intake terminal — a search engine wearing
#   the Time Variance Authority's amber chronoscope, not a space archive.
#   Refuses: dark-blue cinematic void + generic gold filament hero.
# OWN-WORLD: amber phosphor CRT (#FFB74A on #14121F), scanlines, cream
#   paper (#F0E6D2) stamped file copy, condensed mid-century signage
#   (Oswald), rubber-stamp red accents, one redline threshold on the glass.
# STORY: the visitor is a Variant at intake; Miss Minutes greets them from
#   the screen, they type on the monitor's own input line, file the
#   request, and receive a rubber-stamped ruling whose every claim cites
#   subtitle evidence.
# FIRST VIEWPORT: full-viewport chrono-monitor — CRT bezel, the Sacred
#   Timeline snaking across dark glass with six live branch lines and two
#   pruned stubs, status readouts in condensed caps; the query field is
#   the console strip attached beneath the tube — the TVA's own input
#   line, amber on glass; primary action = FILE REQUEST.
# FORM: TVA field terminal / position 2 of 7 candidates / seed: chronoscope
# FINISH: unreviewed and undocumented is unfinished; this build ends with
#   the finish review, the verdict, DESIGN.md, and every shipping raster
#   carrying its provenance.
# ---------------------------------------------------------------------------

# Inline bridge script — gradio 6's mount(js=…) never executes, so the
# chronoscope interactivity ships inside the hero HTML itself: one place
# for every bridge (branch click -> scope, evidence hover -> highlight).
HERO_JS = """
<script>
(function () {
  if (window.__mmBridge) return; window.__mmBridge = true;
  var selected = null;
  document.addEventListener('click', function (e) {
    var t = e.target, g = null;
    while (t && t !== document) {
      if (t.classList && t.classList.contains('branch-g')) { g = t; break; }
      t = t.parentNode;
    }
    if (!g || !g.closest('#chronoscope')) return;
    if (g.dataset.pruned === '1') return;   // pruned lines hold no files
    selected = (selected === g.dataset.key) ? null : g.dataset.key;
    document.querySelectorAll('#chronoscope .branch-g').forEach(function (el) {
      el.classList.toggle('selected', el.dataset.key === selected);
    });
    var note = document.getElementById('selection-note');
    if (note) note.textContent = selected ? 'SCOPE LOCKED — ' + g.dataset.label.toUpperCase() : '';
    var box = document.querySelector('#scope-tb textarea') || document.querySelector('#scope-tb input');
    if (box) {
      var proto = box.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(box, selected || '');
      box.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  document.addEventListener('mouseover', function (e) {
    var chunk = e.target.closest ? e.target.closest('#evidence .chunk[data-timeline]') : null;
    if (!chunk) return;
    var g = document.querySelector('#chronoscope .branch-g[data-key="' + chunk.dataset.timeline + '"]');
    if (g) g.classList.add('hover');
  });
  document.addEventListener('mouseout', function (e) {
    var chunk = e.target.closest ? e.target.closest('#evidence .chunk[data-timeline]') : null;
    if (!chunk) return;
    var g = document.querySelector('#chronoscope .branch-g[data-key="' + chunk.dataset.timeline + '"]');
    if (g) g.classList.remove('hover');
  });
  // gradio's .pending class marks a request in flight; mirror it on #chrono
  // so the console sweep can retrace (body-level classes are unreachable
  // behind gradio's selector re-scoping)
  if (window.MutationObserver) {
    var sync = function () {
      var chrono = document.getElementById('chrono');
      if (chrono) chrono.classList.toggle('processing', !!document.querySelector('.pending'));
    };
    new MutationObserver(sync).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] });
  }
})();
</script>
"""

# timeline key -> dropdown label (the click-to-scope bridge)
KEY_TO_LABEL = {t["key"]: t["label"] for t in TIMELINES}
LABEL_TO_KEY = {t["label"]: t["key"] for t in TIMELINES}
LABEL_TO_KEY["All timelines"] = None
PRUNED_LABELS = {t["label"] for t in TIMELINES if t.get("pruned")}
DROPDOWN_TIMELINES = ["All timelines"] + [t["label"] for t in TIMELINES if not t.get("pruned")]

# evidence title -> timeline key, longest match wins; unmatched = MCU spine.
# The corpus taxonomy: spiderverse films are filed under sony:ssu.
BRANCH_KEYS = {
    "what if": "whatif", "what if...?": "whatif", "marvel zombies": "whatif",
    "x-men": "fox:xmen", "x2 ": "fox:xmen", "x2:": "fox:xmen",
    "deadpool": "fox:xmen", "logan": "fox:xmen", "wolverine": "fox:xmen",
    "new mutants": "fox:xmen", "dark phoenix": "fox:xmen",
    "spider-man": "sony:rami", "spider-man 2": "sony:rami", "spider-man 3": "sony:rami",
    "amazing spider-man": "sony:webb",
    "venom": "sony:ssu", "morbius": "sony:ssu", "kraven": "sony:ssu",
    "madame web": "sony:ssu", "spider-verse": "sony:ssu",
    "daredevil": "defenders", "jessica jones": "defenders", "luke cage": "defenders",
    "iron fist": "defenders", "punisher": "defenders", "defenders": "defenders",
}

# timeline key -> in-universe branch name for the evidence badges
KEY_TO_BRANCH = {t["key"]: t["branch"] for t in TIMELINES}


def _branch_key(title: str) -> str:
    t = (title or "").lower()
    best, best_len = "", 0
    for frag, key in BRANCH_KEYS.items():
        if frag in t and len(frag) > best_len:
            best, best_len = key, len(frag)
    return best or "mcu"


# --- TVA copy ---------------------------------------------------------------

MOTTO = "FOR ALL TIME. ALWAYS."

INTAKE_HEADING = """<div class="intake-heading">
  <p class="mm-line">Welcome to the Time Variance Authority. Settle in, sharpen
  your pencils &mdash; and check this out: everything below is on the record.</p>
</div>"""

EXAMPLES = [
    "What happened after Loki escaped with the Tesseract?",
    "How are the Fox X-Men connected to the multiverse?",
    "Which Spider-Man universes exist?",
]

EXAMPLES_HEADING = "<div class='ex-label'>Recent sequence violations under review</div>"

STATUS_TEMPLATES = {
    "ok": "FILE PROCESSED — GRAPH · VECTOR · LEXICAL",
    "graph_down": "FILE PROCESSED (DEGRADED) — VECTOR · LEXICAL ONLY, GRAPH UNREACHABLE",
    "vector_down": "FILE PROCESSED (DEGRADED) — GRAPH · LEXICAL ONLY, VECTOR UNREACHABLE",
    "both_down": "FILE PROCESSED (MINIMAL) — LEXICAL ONLY",
}


def scope_from_scene(key: str):
    """Chronoscope click -> dropdown value (adapter at the Gradio boundary)."""
    key = (key or "").strip()
    return KEY_TO_LABEL.get(key, "All timelines")


def _ev_row(i: int, c: dict) -> str:
    title = html.escape(c.get("title", "?"))
    text = html.escape(c.get("text", "")[:220])
    key = _branch_key(c.get("title", ""))
    branch = KEY_TO_BRANCH.get(key, key)
    meta = html.escape(c.get("chunk_id", ""))
    return (
        f"<div class='chunk' data-timeline='{key}'>"
        f"<span class='num'>{i:02d}</span>"
        f"<span class='ev-body'><b>{title}</b>"
        f"<span class='branch-branch'>{branch}</span>"
        f"<span class='meta'>FILE {meta}</span>"
        f"<span class='quote'>{text}&hellip;</span></span></div>"
    )


def _empty_answer() -> str:
    return (
        "<div id='answer-wrap'>"
        "<p class='stamp'>PENDING FILE REQUEST</p>"
        "<p>Ask the archive and the ruling appears here &mdash; grounded in "
        "ingested subtitle evidence, every claim cited, sources stamped.</p>"
        "</div>"
    )


def _empty_evidence() -> str:
    return (
        "<div id='evidence'><p class='ev-heading'>Evidence from the timeline</p>"
        "<p class='ev-sub'>Cited passages arrive here after a search.</p></div>"
    )


def _status_html(legs: dict, latency: float) -> str:
    g, v = legs.get("graph"), legs.get("vector")
    if g and v:
        code = "ok"
    elif not g and not v:
        code = "both_down"
    elif not g:
        code = "graph_down"
    else:
        code = "vector_down"
    return f"<div id='pipeline-status'>{STATUS_TEMPLATES[code]} · {latency:.1f}s</div>"

def search_and_answer(question: str, timeline: str):
    """Orchestrated pipeline: plan -> hybrid retrieval -> grounded synthesis."""
    if not question.strip():
        return _empty_answer(), _empty_evidence(), ""
    t0 = time.perf_counter()
    try:
        store = get_store()
        vs = get_vector()
        graph = get_graph()
        llm = get_llm()
        plan = parse_query(llm, question)
        if timeline and timeline != "All timelines":
            plan.timeline = LABEL_TO_KEY.get(timeline)

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
        out = (
            "<div id='answer-wrap'>"
            "<p class='stamp'>RULING ISSUED</p>"
            f"<p>{answer_html}</p>"
        )
        if result.get("uncertainty") and result["uncertainty"] != "none":
            out += (
                "<span class='warn'><svg class='warn-ic' viewBox='0 0 24 24' aria-hidden='true'>"
                "<path d='M12 3 22 20H2Z' fill='none' stroke='currentColor' stroke-width='2' "
                "stroke-linejoin='round'/><path d='M12 9.5v4.5' stroke='currentColor' "
                "stroke-width='2' stroke-linecap='round'/><circle cx='12' cy='16.8' r='1.15' "
                "fill='currentColor' stroke='none'/></svg>"
                f"{html.escape(result['uncertainty'])}</span>"
            )
        if result.get("sources"):
            out += (
                "<span class='src'>Sources — "
                + html.escape(", ".join(result["sources"][:8]))
                + "</span>"
            )
        out += "</div>"

        status = _status_html(ranked.get("legs", {}), time.perf_counter() - t0)
        return out, evidence, status
    except Exception as e:
        logger.exception("pipeline error")
        return (
            "<div id='answer-wrap'><p class='stamp'>REQUEST REJECTED</p>"
            "<p>The archivist hit a snag: "
            f"{type(e).__name__}. Try rephrasing the question.</p></div>",
            "",
            "",
        )


def run_example(question: str, timeline: str):
    """Fill-and-run: echo the query into the input, then answer it."""
    return question, *search_and_answer(question, timeline)


def build_app() -> gr.Blocks:
    with gr.Blocks(title="MissMinutes — TVA field terminal") as app:
        gr.HTML(f"""
        <div id="crt-topbar">
          <span class="brand">
            <svg class="tva-mark" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 2 22 12 12 22 2 12Z" fill="none" stroke="currentColor"
                    stroke-width="2.4" stroke-linejoin="round"/>
              <path d="M12 7.5 16.5 12 12 16.5 7.5 12Z" fill="currentColor" stroke="none"/>
            </svg>
            TIME VARIANCE AUTHORITY
          </span>
          <span class="status"><span class="dot"></span>SACRED TIMELINE · STABLE</span>
        </div>
        <div id="chrono" aria-label="Chrono-monitor: the Sacred Timeline with branch timelines diverging">
          {chronoscope_svg()}
          <div class="crt-overlay" aria-hidden="true"></div>
          <div class="sweep" aria-hidden="true"></div>
          <div class="brandblock">
            <h1>Miss Minutes</h1>
            <p class="lede">Hey there! I&rsquo;m the TVA&rsquo;s archivist, and it&rsquo;s my job to
            catch you up. Ask the archive &mdash; every answer cites its evidence.</p>
          </div>
          <div class="hero-hint">CLICK A BRANCH TO SCOPE YOUR SEARCH TO THAT TIMELINE</div>
        </div>
        """)

        with gr.Column(elem_id="searchzone"):
            with gr.Row(elem_id="searchrow"):
                q = gr.Textbox(
                    placeholder="TYPE QUERY — the archive is listening",
                    label="",
                    show_label=False,
                    elem_classes="query-box",
                    lines=1,
                )
                btn = gr.Button("File request", variant="primary", elem_id="searchbtn")
            gr.HTML(INTAKE_HEADING)
            tl = gr.Dropdown(
                choices=DROPDOWN_TIMELINES,
                value="All timelines",
                label="",
                show_label=False,
                elem_id="timeline-filter",
            )
            # gradio 6 drops visible=False components from the DOM entirely;
            # render it and let #scope-tb CSS collapse it to nothing instead
            scope_tb = gr.Textbox(value="", elem_id="scope-tb", show_label=False, container=False)
            gr.HTML("<div id='selection-note'></div>")

        with gr.Column(elem_id="examples"):
            gr.HTML(EXAMPLES_HEADING)
            ex_buttons = []
            for ex in EXAMPLES:
                ex_buttons.append(gr.Button(ex, variant="secondary"))

        gr.HTML("<div id='read'><div class='divider'></div></div>")
        out = gr.HTML(_empty_answer())
        ev = gr.HTML(_empty_evidence())
        status = gr.HTML("<div id='pipeline-status'></div>", elem_id="status-shell")

        gr.HTML(
            "<div id='colophon'>MISSMINUTES &mdash; knowledge graph: <b>neo4j aura</b> "
            "&nbsp;&middot;&nbsp; vectors: <b>qdrant</b> &nbsp;&middot;&nbsp; "
            "grounding: <b>MiniMax-M3</b> &nbsp;&middot;&nbsp; every claim cites "
            "subtitle evidence</div>"
        )

        btn.click(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        q.submit(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        scope_tb.change(scope_from_scene, inputs=[scope_tb], outputs=[tl])
        for exb, ex_text in zip(ex_buttons, EXAMPLES):
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
    gr.mount_gradio_app(scene_app, blocks, path="/", css=CSS, head=HERO_JS)
    uvicorn.run(scene_app, host="0.0.0.0", port=7860)
