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
import re
import time
from pathlib import Path

import gradio as gr

from src.search.hybrid import hybrid_search
from src.search.planner import parse_query
from src.search.synthesis import EVIDENCE_LIMIT, generate_answer
from src.ui.chronoscope import TIMELINES, chronoscope_svg
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
# for every bridge (branch click <-> scope, evidence hover -> highlight,
# pending mirror, citation markers -> evidence rows).
HERO_JS = """
<script>
(function () {
  if (window.__mmBridge) return; window.__mmBridge = true;
  var selected = null;
  var PRUNED_NOTE = {
    'fox:ff': 'FOX FANTASTIC FOUR — PRUNED (NO FILES ON THIS BRANCH)',
    'sony:spiderverse': 'SPIDER-VERSE — PRUNED (NO FILES ON THIS BRANCH)'
  };
  var LABELS = {
    'mcu': 'MCU / SACRED TIMELINE', 'fox:xmen': 'FOX X-MEN',
    'sony:rami': "TOBEY MAGUIRE'S SPIDER-MAN", 'sony:webb': 'THE AMAZING SPIDER-MAN',
    'sony:ssu': 'VENOM · MORBIUS · KRAVEN · SPIDER-VERSE', 'defenders': 'THE DEFENDERS',
    'whatif': 'WHAT IF...?', 'fox:ff': 'FOX FANTASTIC FOUR',
    'sony:spiderverse': 'SPIDER-VERSE (ANIMATED)'
  };

  function setNote(txt) {
    var note = document.getElementById('selection-note');
    if (note) note.textContent = txt;
  }

  function applySelection(key) {
    selected = key;
    document.querySelectorAll('.chronoscope .branch-g').forEach(function (el) {
      el.classList.toggle('selected', el.dataset.key === selected);
      el.setAttribute('aria-pressed', el.dataset.key === selected ? 'true' : 'false');
    });
    if (selected) {
      var el = document.querySelector('.chronoscope .branch-g[data-key="' + selected + '"]');
      setNote('SCOPE LOCKED — ' + ((el && el.dataset.label) || (LABELS[selected] || selected)).toUpperCase());
    } else {
      setNote('');
    }
  }

  // --- branch click / keyboard -> scope ---------------------------------
  function branchPick(g) {
    if (!g || !g.closest('.chronoscope')) return;
    if (g.dataset.pruned === '1') {
      setNote(PRUNED_NOTE[g.dataset.key] || (g.dataset.label + ' — PRUNED (NO FILES ON THIS BRANCH)'));
      return;
    }
    applySelection(selected === g.dataset.key ? null : g.dataset.key);
    var box = document.querySelector('#scope-tb textarea') || document.querySelector('#scope-tb input');
    if (box) {
      var proto = box.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(box, selected || '');
      box.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  document.addEventListener('click', function (e) {
    var t = e.target, g = null;
    while (t && t !== document) {
      if (t.classList && t.classList.contains('branch-g')) { g = t; break; }
      t = t.parentNode;
    }
    branchPick(g);
  });

  // --- debounce: a second FILE REQUEST while one is in flight joins a
  // 40s queue behind itself — swallow it at capture phase instead.
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('#searchbtn') : null;
    if (b && document.querySelector('.pending')) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var t = e.target;
    if (t.classList && t.classList.contains('branch-g') && t.closest('.chronoscope')) {
      e.preventDefault();
      branchPick(t);
    }
  });

  // --- dropdown -> chronoscope (the reverse bridge) ----------------------
  // the python change handler re-emits the bridge block with the chosen
  // label inside #scope-echo. gradio REPLACES that subtree on every update
  // (killing any observer attached to it), so watch a stable ancestor and
  // look the node up on every mutation. Every path converges here — branch
  // clicks and dropdown picks alike — so the note can never desync: the
  // echo is the single source of truth the scene renders from.
  var echoHost = document.body;  // stable; #searchzone sits inside
  if (window.MutationObserver && echoHost) {
    var lastEcho = null;
    new MutationObserver(function () {
      var echo = document.getElementById('scope-echo');
      if (!echo) return;
      var v = (echo.textContent || '').trim();
      if (v === lastEcho) return;
      lastEcho = v;
      var key = null;
      if (v && v !== 'ALL TIMELINES') {
        for (var k in LABELS) {
          if (LABELS[k].toUpperCase() === v) { key = k; break; }
        }
      }
      applySelection(key);
    }).observe(echoHost, { childList: true, subtree: true, characterData: true });
  }

  // --- evidence hover -> branch highlight --------------------------------
  document.addEventListener('mouseover', function (e) {
    var chunk = e.target.closest ? e.target.closest('#evidence .chunk[data-timeline]') : null;
    if (!chunk) return;
    var g = document.querySelector('.chronoscope .branch-g[data-key="' + chunk.dataset.timeline + '"]');
    if (g) g.classList.add('hover');
  });
  document.addEventListener('mouseout', function (e) {
    var chunk = e.target.closest ? e.target.closest('#evidence .chunk[data-timeline]') : null;
    if (!chunk) return;
    var g = document.querySelector('.chronoscope .branch-g[data-key="' + chunk.dataset.timeline + '"]');
    if (g) g.classList.remove('hover');
  });

  // --- pending mirror: in-flight status note + sweep + a11y fixups ----------
  if (window.MutationObserver) {
    var sync = function () {
      var pending = !!document.querySelector('.pending');
      var chrono = document.getElementById('chrono');
      if (chrono) chrono.classList.toggle('processing', pending);
      var flight = document.getElementById('flight-note');
      if (flight) {
        flight.textContent = pending ? 'REVIEWING FILE — THE ARCHIVIST IS CONSULTING THE RECORD…' : '';
      }
      // a11y fixups (gradio re-renders controls; re-apply idempotently)
      var qb = document.querySelector('.query-box textarea');
      if (qb && !qb.getAttribute('aria-label')) {
        qb.setAttribute('aria-label', 'Ask the archive — type your question about Marvel screen canon');
      }
      var db = document.querySelector('#timeline-filter input');
      if (db && !db.getAttribute('aria-label')) {
        db.setAttribute('aria-label', 'Timeline scope — filter the search to one branch of the multiverse');
      }
      var stb = document.querySelector('#scope-tb textarea') || document.querySelector('#scope-tb input');
      if (stb) { stb.tabIndex = -1; stb.setAttribute('aria-hidden', 'true'); }
      // hidden gradio chrome (0x0 but focusable) must leave the tab order
      document.querySelectorAll('footer a, footer button, gradio-footer a, gradio-footer button').forEach(function (el) {
        el.tabIndex = -1;
      });
    };
    new MutationObserver(sync).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] });
    sync();
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

# timeline key -> in-universe branch name for the evidence badges
KEY_TO_BRANCH = {t["key"]: t["branch"] for t in TIMELINES}

# --- TVA copy ---------------------------------------------------------------

MOTTO = "FOR ALL TIME. ALWAYS."

INTAKE_HEADING = """<div class="intake-heading">
  <p class="mm-line">Welcome to the Time Variance Authority. Settle in, sharpen
  your pencils &mdash; and check this out: everything below is on the record.</p>
</div>"""

# Machine readouts — drawn on the console strip's own glass, where they are
# always visible. The SVG floor they used to occupy sat behind the strip's
# lap on every desktop size (C1: drawn and never seen).
CONSOLE_READOUTS_HTML = (
    "<div class='console-readouts' aria-hidden='true'>"
    + "".join(
        f"<span class='ro'><span class='ro-k'>{k}</span> <span class='ro-v'>{v}</span></span>"
        for k, v in (
            ("CHRONO BAY 3", "BRANCH SCAN ACTIVE"),
            ("REDLINE", "0.0031 DEVIATION"),
            ("HUNTERS", "STANDBY"),
            ("ANALYSTS", "ON DUTY"),
        )
    )
    + "</div>"
)

EXAMPLES = [
    "What happened after Loki escaped with the Tesseract?",
    "How are the Fox X-Men connected to the multiverse?",
    "Which Spider-Man universes exist?",
]

EXAMPLES_HEADING = "<div class='ex-label'>Recent sequence violations under review</div>"

# mono degradation tiers (DESIGN.md status vocabulary). Every leg reports
# ok / empty / down — "empty" is a healthy branch with no files for this
# query, "down" is a backend the pipeline could not reach. The legs named
# are the legs that actually served evidence for this ruling.
_LEG_OK, _LEG_EMPTY, _LEG_DOWN = "ok", "empty", "down"


def _status_html(legs: dict, used: list[str], latency: float) -> str:
    """One word per leg, always in the same order. A leg is named plain
    when the ruling's citations include evidence it served; a healthy leg
    with nothing for this ruling reads (NO FILES); an unreachable backend
    reads UNREACHABLE — never conflated."""
    order = (("graph", "GRAPH"), ("vector", "VECTOR"), ("lexical", "LEXICAL"))
    parts = []
    for leg, name in order:
        state = legs.get(leg)
        if state == _LEG_DOWN:
            parts.append(name + " UNREACHABLE")
        elif leg in used:
            parts.append(name)
        else:
            parts.append(name + " (NO FILES)")
    down = [legs.get(l) == _LEG_DOWN for l, _ in order]
    prefix = "FILE PROCESSED (DEGRADED)" if any(down) else "FILE PROCESSED"
    if all(down):
        line = "NO BACKENDS REACHABLE — THE ARCHIVE IS DARK"
    elif not used:
        tail = " · ".join(p for p in parts if "UNREACHABLE" in p)
        line = prefix + " — NO EVIDENCE ON THIS BRANCH" + ((" · " + tail) if tail else "")
    else:
        line = prefix + " — " + " · ".join(parts)
    return f"<div id='pipeline-status'>{line} · {latency:.1f}s</div>"


def scope_from_scene(key: str):
    """Chronoscope click -> dropdown value (adapter at the Gradio boundary)."""
    key = (key or "").strip()
    return KEY_TO_LABEL.get(key, "All timelines")


def _ev_row(i: int, c: dict) -> str:
    """One evidence row. The branch badge is the chunk's real timeline_id
    (from the store payload), never guessed from the title. Graph rows
    carry no timeline — they badge KNOWLEDGE GRAPH and light no branch."""
    title = html.escape(c.get("title", "?"))
    text_full = c.get("text", "")
    text = text_full[:220]
    tl = (c.get("timeline_id") or "").strip()
    if tl:
        branch = KEY_TO_BRANCH.get(tl, tl.upper())
        tl_attr = f" data-timeline='{html.escape(tl)}'"
    else:
        branch = "KNOWLEDGE GRAPH"
        tl_attr = ""
    meta = html.escape(c.get("chunk_id", ""))
    quote = html.escape(text) + ("&hellip;" if len(text_full) > 220 else "")
    return (
        f"<div class='chunk' id='ev-{i:02d}'{tl_attr}>"
        f"<span class='num'>{i:02d}</span>"
        f"<span class='ev-body'><b>{title}</b>"
        f"<span class='branch-branch'>{branch}</span>"
        f"<span class='meta'>FILE {meta}</span>"
        f"<span class='quote'>{quote}</span></span></div>"
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


def _flight_note() -> str:
    return "<div id='flight-note' aria-live='polite'></div>"


_CITE_RE = re.compile(r"\[(\d+)\]")


def _answer_html(answer: str) -> str:
    """Ruling text with [n] markers rendered as amber superscript links that
    scroll to the matching evidence row — the citation affordance, live."""
    def _sub(m):
        n = m.group(1)
        if n.isdigit() and 1 <= int(n) <= EVIDENCE_LIMIT:
            return (f"<a class='cite' href='#ev-{int(n):02d}' "
                    f"aria-label='Citation {n} — jump to evidence row {n}'>[{n}]</a>")
        return f"[{n}]"

    parts = []
    for para in answer.split("\n"):
        if not para.strip():
            continue
        escaped = html.escape(para.strip())
        parts.append(_CITE_RE.sub(_sub, escaped))
    return "<br/>".join(parts)


def _evidence_html(citations: list[dict], empty_note: str) -> str:
    rows = [_ev_row(i, c) for i, c in enumerate(citations, 1)]
    if rows:
        return ("<div id='evidence'><p class='ev-heading'>Evidence from the timeline</p>"
                + "".join(rows) + "</div>")
    return ("<div id='evidence'><p class='ev-heading'>Evidence from the timeline</p>"
            f"<p class='ev-sub'>{empty_note}</p></div>")


def search_and_answer(question: str, timeline: str):
    """Orchestrated pipeline: plan -> hybrid retrieval -> grounded synthesis."""
    if not question.strip():
        # no-op on empty submit: the desk stays as it was
        return gr.update(), gr.update(), gr.update()

    t0 = time.perf_counter()
    try:
        store = get_store()
        vs = get_vector()
        graph = get_graph()
        llm = get_llm()
        plan = parse_query(llm, question)
        # a stale/unknown dropdown label must never clobber a timeline the
        # planner inferred from the question
        if timeline and timeline != "All timelines":
            if key := LABEL_TO_KEY.get(timeline):
                plan.timeline = key

        ranked = hybrid_search(store, vs, graph, question, plan)
    except Exception:
        logger.exception("retrieval error")
        status = (
            "<div id='pipeline-status'>FILE REJECTED — THE ARCHIVE IS MOMENTARILY "
            "UNREACHABLE. TRY REPHRASING OR RE-FILE IN A MOMENT.</div>"
        )
        return (
            "<div id='answer-wrap'><p class='stamp'>REQUEST REJECTED</p>"
            "<p>The archivist could not reach the records. Try rephrasing the "
            "question, or file the request again in a moment.</p></div>",
            _evidence_html([], "No passages accompany a rejected request."),
            status,
        )

    # synthesis failures keep the retrieval work: the evidence is in hand,
    # only the ruling is missing
    try:
        result = generate_answer(llm, question, ranked)
    except Exception:
        logger.exception("synthesis error")
        citations = [
            r["data"] for r in ranked.get("results", []) if r["type"] == "chunk"
        ][:EVIDENCE_LIMIT]
        return (
            "<div id='answer-wrap'><p class='stamp'>RULING DEFERRED</p>"
            "<p>Evidence was retrieved but the archivist could not reach the "
            "synthesis engine. The passages below stand on their own — re-file "
            "for a ruling.</p></div>",
            _evidence_html(citations, "No subtitle passages were retrievable for this query."),
            "<div id='pipeline-status'>FILE PROCESSED (DEGRADED) — SYNTHESIS UNREACHABLE"
            f" · {time.perf_counter() - t0:.1f}s</div>",
        )

    citations = result.get("citations", [])
    used = _used_legs(ranked, result.get("answer", ""))
    evidence = _evidence_html(
        citations, "No subtitle passages were retrievable for this query."
    )

    out = (
        "<div id='answer-wrap'>"
        "<p class='stamp'>RULING ISSUED</p>"
        f"<p class='ruling'>{_answer_html(result['answer'])}</p>"
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

    status = _status_html(ranked.get("legs", {}), used, time.perf_counter() - t0)
    return out, evidence, status


def _used_legs(ranked: dict, answer: str) -> list[str]:
    """Legs that actually served rows the answer cites (or the top evidence).

    A graph hit only counts when the answer's citations include a graph row;
    otherwise GRAPH shows as serving when every cited chunk came from FTS5
    or Qdrant."""
    cited = {int(c) for c in _CITE_RE.findall(answer)}
    results = ranked.get("results", [])
    used: list[str] = []

    def _leg_of(r: dict) -> str:
        if r["type"] == "chunk":
            src = r["data"].get("source")
            if src == "fts":
                return "lexical"
            if src == "fts+vector":
                return "vector+lexical"
            return "vector"
        return "graph"

    def _add(leg: str) -> None:
        for part in leg.split("+"):
            if part not in used:
                used.append(part)

    for i, r in enumerate(results[:EVIDENCE_LIMIT], 1):
        if cited and i not in cited:
            continue
        _add(_leg_of(r))
    if not used:
        # answer cites nothing: name every leg that served rows at all
        for r in results[:EVIDENCE_LIMIT]:
            _add(_leg_of(r))
    return used


def echo_scope(timeline: str):
    """Dropdown change -> re-emit the bridge HTML with the new scope echoed.

    The selection-note and scope-echo divs live inside one gr.HTML so the
    JS observer sees the echo; the flight-note div is recreated too.
    Returns the full block so the echoed label lands in #scope-echo."""
    label = (timeline or "ALL TIMELINES").upper()
    return (
        f"<div id='selection-note' aria-live='polite'></div>"
        f"<div id='scope-echo' style='display:none'>{html.escape(label)}</div>"
        f"{_flight_note()}"
    )


def build_app() -> gr.Blocks:
    with gr.Blocks(title="MissMinutes — TVA field terminal") as app:
        gr.HTML(f"""
        <a id="skip-link" href="#searchzone">Skip to the request line</a>
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
        <div id="chrono" role="group" aria-label="Chrono-monitor: the Sacred Timeline with branch timelines">
          <div id="chrono-desktop">{chronoscope_svg(compact=False)}</div>
          <div id="chrono-mobile">{chronoscope_svg(compact=True)}</div>
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
            gr.HTML(CONSOLE_READOUTS_HTML)
            with gr.Row(elem_id="searchrow"):
                q = gr.Textbox(
                    placeholder="TYPE QUERY — the archive is listening",
                    label="Ask the archive",
                    show_label=False,
                    elem_classes="query-box",
                    lines=1,
                )
                btn = gr.Button("File request", variant="primary", elem_id="searchbtn")
            gr.HTML(INTAKE_HEADING)
            tl = gr.Dropdown(
                choices=DROPDOWN_TIMELINES,
                value="All timelines",
                label="Timeline scope",
                show_label=False,
                elem_id="timeline-filter",
            )
            # gradio 6 drops visible=False components from the DOM entirely;
            # render it and let #scope-tb CSS collapse it to nothing instead
            scope_tb = gr.Textbox(value="", elem_id="scope-tb", show_label=False,
                                  container=False)
            scope_note = gr.HTML(
                f"<div id='selection-note' aria-live='polite'></div>"
                f"<div id='scope-echo' style='display:none'></div>"
                f"{_flight_note()}"
            )

        with gr.Column(elem_id="examples"):
            gr.HTML(EXAMPLES_HEADING)
            ex_buttons = []
            for ex in EXAMPLES:
                ex_buttons.append(gr.Button(ex, variant="secondary"))

        gr.HTML("<div id='read'><div class='divider'></div></div>")
        out = gr.HTML(_empty_answer(), elem_id="answer-shell")
        ev = gr.HTML(_empty_evidence(), elem_id="evidence-shell")
        status = gr.HTML("<div id='pipeline-status' aria-live='polite'></div>", elem_id="status-shell")

        gr.HTML(
            "<div id='colophon'>MISSMINUTES &mdash; knowledge graph: <b>neo4j aura</b> "
            "&nbsp;&middot;&nbsp; vectors: <b>qdrant</b> &nbsp;&middot;&nbsp; "
            "grounding: <b>MiniMax-M3</b> &nbsp;&middot;&nbsp; every claim cites "
            "subtitle evidence</div>"
        )

        btn.click(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        q.submit(search_and_answer, inputs=[q, tl], outputs=[out, ev, status])
        scope_tb.change(scope_from_scene, inputs=[scope_tb], outputs=[tl])
        tl.change(echo_scope, inputs=[tl], outputs=[scope_note])
        for exb, ex_text in zip(ex_buttons, EXAMPLES):
            # the question is a constant of this button — a closure, not a
            # hidden Textbox component wired into the graph
            exb.click(
                lambda tl_val, _ex=ex_text: (_ex, *search_and_answer(_ex, tl_val)),
                inputs=[tl],
                outputs=[q, out, ev, status],
            )
    return app


if __name__ == "__main__":
    import os

    import uvicorn
    from starlette.applications import Starlette

    blocks = build_app()
    blocks.queue(default_concurrency_limit=1)
    scene = gr.mount_gradio_app(Starlette(), blocks, path="/", css=CSS, head=HERO_JS)
    uvicorn.run(
        scene,
        host=os.getenv("MM_HOST", "127.0.0.1"),
        port=int(os.getenv("MM_PORT", "7860")),
    )
