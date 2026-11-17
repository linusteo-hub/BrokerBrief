"""
modules/ui.py

HTML builders for the BrokerBrief design system (https://claude.ai/artifact/JmCcpdfzRerjgwtWi6RS6K).

Every function returns ONE line of HTML that uses the classes in styles/components.css.
One line matters: st.markdown treats a blank line inside an HTML block as the end of
the block, and anything after it is parsed as Markdown (indented lines become code).

Callers pass plain values, never engine objects, so this module imports nothing from
modules/decision and can be reused by the morning brief.
"""

import re
from html import escape
from pathlib import Path

STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"
# Order matters: tokens first, then component classes, then the Streamlit glue that uses both.
STYLESHEETS = ("tokens.css", "components.css", "streamlit.css", "app.css")

ANCHOR_SVG = (
    '<svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="13" r="5"/>'
    '<path d="M32 18v34"/><path d="M23 26h18"/><path d="M13 37c2 9 9 15 19 15s17-6 19-15"/>'
    '<path d="M8 41l5-4 5 3"/><path d="M56 41l-5-4-5 3"/></svg>'
)

# Direction words -> colour class. Read from the buyer's side: a rising price is red.
DIRECTION_CLASS = {
    "Up": "dir-up", "Down": "dir-down", "Flat": "dir-flat",
    "Rising": "dir-rising", "Easing": "dir-easing", "Stable": "dir-stable",
    "Unknown": "dir-unknown", "MISSING": "dir-unknown",
}


# Literal hex for the pandas Styler in the signal table: Streamlit draws data frames on a
# canvas, which cannot read CSS variables. Values mirror the red/green/blue/amber tokens.
DIRECTION_HEX = {
    "Up": "#ff6b6b", "Down": "#3fb950", "Flat": "#58a6ff",
    "Rising": "#f0a500", "Easing": "#3fb950", "Stable": "#58a6ff",
}


def stylesheet_html() -> str:
    """All three stylesheets as separate <style> tags. Each is its own tag so the
    @import of Google Fonts stays first in components.css, where CSS requires it.

    Every <style> and </style> sits on a line of its own: Markdown ends a <style> HTML
    block at the first line containing </style>, so a second <style> opened on that same
    line would be parsed as plain text and printed on the page.

    Blank lines are removed for the same reason: Streamlit ends the block at a blank line.

    @import lines are lifted out into <link> tags. Streamlit's Markdown turns any bare URL
    into a link, even inside <style>, which cuts the stylesheet off at the URL. A URL in a
    tag attribute (href) is left alone."""
    links, blocks = [], []
    for name in STYLESHEETS:
        css = (STYLES_DIR / name).read_text(encoding="utf-8")
        for url in re.findall(r"@import url\('([^']+)'\);", css):
            links.append(f'<link rel="stylesheet" href="{url}">')
        css = re.sub(r"@import url\('[^']+'\);\n?", "", css)
        # Streamlit's Markdown ends a <style> block at the first blank line, so drop them.
        css = re.sub(r"\n\s*\n", "\n", css)
        assert "://" not in css, f"{name} contains a URL that Streamlit would turn into a link"
        blocks.append(f"<style>\n{css}\n</style>")
    return "\n".join(links + blocks)


def _clamp(value) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def sidebar_brand(tagline: bool = True) -> str:
    brand = f'<div class="sidebar-brand"><span class="brand-tile">{ANCHOR_SVG}</span>BrokerBrief</div>'
    if not tagline:
        return brand
    return brand + '<div class="sidebar-tagline">Know the market · <em>decide what\'s next</em></div>'


def page_header(title: str, subtitle: str) -> str:
    return (f'<div class="page-title bb-reveal">{escape(title)}</div>'
            f'<div class="page-subtitle">{escape(subtitle)}</div>')


def sig(word: str) -> str:
    """The capitalised status word that opens a line (WARNING, MISSING, REMOVED...)."""
    return f'<span class="sig-label">{escape(word)}</span>'


def warn_strip(message: str, word: str = "Warning") -> str:
    return f'<div class="warn-strip">{sig(word)}{escape(message)}</div>'


def sample_chip(text: str = "sample data · illustrative") -> str:
    """Pinned bottom-right on every page while any sample row is loaded."""
    return f'<span class="sample-chip is-pinned">{escape(text)}</span>'


def stat_pill(label: str, value: str, direction: str | None = None) -> str:
    """direction colours the value; it defaults to the value itself (for 'Up', 'Rising'...)."""
    cls = DIRECTION_CLASS.get(direction or value, "")
    return (f'<div class="stat-pill"><div class="stat-pill-label">{escape(label)}</div>'
            f'<div class="stat-pill-value {cls}">{escape(value)}</div></div>')


def criterion_bars(rows, alt: bool = False) -> str:
    """rows: [(label, score 0-100), ...]. Amber for the recommendation, blue (alt) for the rest."""
    fill = "conf-bar-fill is-alt" if alt else "conf-bar-fill"
    out = []
    for i, (label, score) in enumerate(rows):
        v = _clamp(score)
        out.append(
            f'<div class="conf-row"><span class="conf-label">{escape(label)}</span>'
            f'<div class="conf-bar-wrap" role="meter" aria-label="{escape(label)}" aria-valuemin="0" '
            f'aria-valuemax="100" aria-valuenow="{v:.0f}"><div class="{fill}" style="width:{v:.0f}%;--i:{i}"></div></div>'
            f'<span class="conf-val">{v:.0f}</span></div>')
    return "".join(out)


def option_card(*, label: str, route: str, score: float, bars, recommended: bool,
                rank: int | None = None, description: str = "", warning: str = "", i: int = 0,
                selected: bool = False, animate: bool = True) -> str:
    """Recommended option (amber edge and bars) or an alternative (blue bars)."""
    if recommended:
        head = ('<div class="rec-label">Recommended · strongest overall balance on current information</div>'
                f'<div class="opt-head"><div class="rec-title">{escape(label)}</div><div class="score-big">{score:.0f}</div></div>')
        cls = "rec-card"
    else:
        prefix = f"#{rank} · " if rank else ""
        head = f'<div class="opt-head"><div class="alt-title">{prefix}{escape(label)}</div><div class="score-big">{score:.0f}</div></div>'
        cls = "alt-card"
    desc = f'<div class="alt-body" style="margin-bottom:1rem;">{escape(description)}</div>' if description else ""
    warn = warn_strip(warning) if warning else ""
    cls += " is-selected" if selected else ""
    cls += " bb-reveal" if animate else " no-motion"
    return (f'<div class="{cls}" style="--i:{i}">{head}<div class="opt-sub">{escape(route)}</div>'
            f'{desc}{criterion_bars(bars, alt=not recommended)}{warn}</div>')


# Short pill labels for the Constraint Engine's removal rules (README: "Constraint Engine").
RULE_LABELS = {
    "F1": "fuel safety reserve not met",
    "F2": "stem below port minimum",
    "C1": "stem above port maximum",
    "P1": "fuel grade unavailable",
    "R1": "HSFO needs a scrubber (MARPOL Annex VI)",
    "F4": "split stem's second leg falls short",
    "S1": "no schedule room for port time",
}


def infeasible_card(*, label: str, description: str, rule: str, reason: str) -> str:
    rule = str(rule)
    return ('<div class="infeasible-card">'
            f'<div class="infeasible-title">{sig("Removed")}{escape(label)}</div>'
            f'<div class="infeasible-ghost" aria-hidden="true">{escape(description)}</div>'
            f'<span class="rule-tag"><b>{escape(rule)}</b>{escape(RULE_LABELS.get(rule, "removed by the Constraint Engine"))}</span>'
            f'<div class="infeasible-reason">{escape(reason)}</div></div>')


def confidence_ring(*, data_quality: float, signal_agreement: float, completeness: float,
                    overall: float, level: str) -> str:
    """Three concentric arcs plus a legend that prints every figure (colour is never the only key)."""
    arcs = [(54, "ring-a", data_quality), (45, "ring-b", signal_agreement), (36, "ring-c", completeness)]
    svg_arcs = "".join(
        f'<circle class="ring-track" cx="60" cy="60" r="{r}"/>'
        f'<circle class="ring-arc {k}" cx="60" cy="60" r="{r}" pathLength="100" style="--v:{_clamp(v):.0f};--i:{i}"/>'
        for i, (r, k, v) in enumerate(arcs))
    aria = (f"Confidence {level}, {overall:.0f}%: data quality {data_quality:.0f}%, "
            f"signal agreement {signal_agreement:.0f}%, scenario completeness {completeness:.0f}%")
    svg = (f'<svg viewBox="0 0 120 120" role="img" aria-label="{escape(aria)}">{svg_arcs}'
           '<text class="ring-caption" x="60" y="57" text-anchor="middle">confidence</text>'
           f'<text class="ring-value" x="60" y="72" text-anchor="middle">{escape(level)}</text></svg>')
    legend = (
        '<div class="ring-legend">'
        f'<div><i style="background:var(--blue)"></i>Data quality (40%)<b>{data_quality:.0f}%</b></div>'
        f'<div><i style="background:var(--green)"></i>Signal agreement (30%)<b>{signal_agreement:.0f}%</b></div>'
        f'<div><i style="background:var(--amber)"></i>Scenario completeness (30%)<b>{completeness:.0f}%</b></div>'
        f'<div style="color:var(--text);">Overall<b>{overall:.0f}%</b></div></div>')
    return f'<div class="conf-ring">{svg}{legend}</div>'


# Port coordinates shown on the route arc (from the brand film; display only).
PORT_COORDS = {"Fujairah": "25.1°N 56.3°E", "Singapore": "1.26°N 103.8°E"}


def route_arc(west: str = "Fujairah", east: str = "Singapore", compact: bool = False) -> str:
    """The corridor as an arc, west port (blue) to east port (amber). A diagram, not a map.
    compact: larger text (see .route-arc.is-compact) for a narrow column, so the line gap grows too."""
    gap = 28 if compact else 18
    return (
        f'<div class="route-arc{" is-compact" if compact else ""}" style="max-width:520px;margin:0 0 0 auto;"><svg viewBox="0 0 640 230" role="img" aria-label="Route from {escape(west)} to {escape(east)}">'
        '<defs><linearGradient id="bb-route" x1="0" x2="1" y1="0" y2="0"><stop offset="0" class="route-stop-a"/><stop offset="1" class="route-stop-b"/></linearGradient></defs>'
        '<path class="route-path" d="M160 48 Q 250 230 500 180" stroke="url(#bb-route)" pathLength="100"/>'
        '<circle class="route-end-a" cx="160" cy="48" r="6"/><circle class="route-end-b" cx="500" cy="180" r="6"/>'
        f'<text class="route-port" x="146" y="52" text-anchor="end">{escape(west)}</text>'
        f'<text class="route-coord" x="146" y="{52 + gap}" text-anchor="end">{PORT_COORDS.get(west, "")}</text>'
        f'<text class="route-port" x="514" y="184">{escape(east)}</text>'
        f'<text class="route-coord" x="514" y="{184 + gap}">{PORT_COORDS.get(east, "")}</text></svg></div>')


# ── Bunkering workspace (live results) ───────────────────────────────────────

CRITERIA = (("expected_cost", "Cost"), ("operational_risk", "Ops risk"), ("schedule_risk", "Schedule"))


def feed_row(name: str, state: str, word: str) -> str:
    """One status line in the sidebar. state: live | stale | missing | error | off | on."""
    return (f'<div class="feed-row is-{state}"><span class="feed-name">{escape(name)}</span>'
            f'<span class="feed-state">{escape(word)}</span></div>')


def score_breakdown(*, label: str, description: str, breakdown: dict, score: float, warning: str = "") -> str:
    """How an option's composite score is built: each criterion's score x weight = points."""
    rows = []
    for key, name in CRITERIA:
        f = breakdown.get(key, {})
        s, w = float(f.get("score", 0) or 0), float(f.get("weight", 0) or 0)
        rows.append(
            '<div class="bd-row">'
            f'<div class="bd-head"><span class="bd-name">{name}</span><span class="bd-weight">weight {w:.0%}</span>'
            f'<span class="bd-points">{s:.0f} × {w:.2f} = <b>{s * w:.1f}</b> pts</span></div>'
            f'<div class="conf-bar-wrap" role="meter" aria-label="{name} score" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{s:.0f}">'
            f'<div class="conf-bar-fill" style="width:{_clamp(s):.0f}%"></div></div>'
            f'<div class="bd-note">{escape(f.get("note", "") or "No reasoning recorded.")}</div></div>')
    warn = warn_strip(warning) if warning else ""
    return ('<div class="info-card detail-card no-motion">'
            f'<div class="info-card-title">Score breakdown · {escape(label)}</div>'
            f'<div class="ws-body" style="margin-bottom:1rem;">{escape(description)}</div>'
            f'{"".join(rows)}<div class="bd-total">Composite <b>{score:.1f}</b> = sum of the weighted points</div>{warn}</div>')


def compare_panel(a: dict, b: dict) -> str:
    """a, b: {label, score, breakdown}. Side by side per criterion, the leader marked in words."""
    def cell(v, lead):
        return f'<td class="{"is-lead" if lead else ""}">{v:.0f}{" · leads" if lead else ""}</td>'
    rows = []
    for key, name in CRITERIA:
        va = float(a["breakdown"].get(key, {}).get("score", 0) or 0)
        vb = float(b["breakdown"].get(key, {}).get("score", 0) or 0)
        rows.append(f'<tr><th>{name}</th>{cell(va, va > vb)}{cell(vb, vb > va)}<td class="cmp-diff">{abs(va - vb):.0f}</td></tr>')
    rows.append(f'<tr class="cmp-total"><th>Composite</th>{cell(a["score"], a["score"] > b["score"])}'
                f'{cell(b["score"], b["score"] > a["score"])}<td class="cmp-diff">{abs(a["score"] - b["score"]):.1f}</td></tr>')
    return ('<div class="info-card no-motion"><div class="info-card-title">Compare</div>'
            '<table class="cmp-table"><thead><tr><th></th>'
            f'<th>{escape(a["label"])}</th><th>{escape(b["label"])}</th><th>Gap</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '<div class="field-label" style="margin-top:.75rem;">Higher is better on every criterion.</div></div>')


def whatif_list(items) -> str:
    """items: [(label, score or None, rule or None)] ranked under the what-if values."""
    rows = []
    for label, score, rule in items:
        if score is None:
            rows.append(f'<div class="wi-row is-removed"><span>{sig("Removed")}{escape(label)}</span>'
                        f'<span class="rule-tag" style="margin:0;"><b>{escape(str(rule))}</b>{escape(RULE_LABELS.get(str(rule), ""))}</span></div>')
        else:
            rows.append(f'<div class="wi-row"><span>{escape(label)}</span><span class="wi-score">{score:.0f}</span></div>')
    return f'<div class="no-motion">{"".join(rows)}</div>'


# ── Route backdrop: the corridor, drawn large behind the whole Bunkering page ──
# Canvas 1600 x 900, fixed to the window and cropped to fill it ("slice"). On a 1440 x 900
# window the visible canvas runs x 80-1520 and the sidebar covers x 80-380, so both ports
# and their labels sit right of x 500, inside the main area.
_BACKDROP_PORTS = {"Fujairah": (560.0, 290.0), "Singapore": (1400.0, 720.0)}
_BACKDROP_CTRL = (720.0, 1040.0)


def _quad(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def _split_quad(p0, p1, p2, t):
    """de Casteljau: the two halves of a quadratic Bézier at parameter t."""
    a = (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
    b = (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)
    m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return (p0, a, m), (m, b, p2)


def _t_at_fraction(p0, p1, p2, fraction, samples=200):
    """Bézier parameter t at a fraction of the curve's LENGTH (t itself is not proportional to length)."""
    pts = [_quad(p0, p1, p2, i / samples) for i in range(samples + 1)]
    seg = [((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5 for i in range(samples)]
    target, run = fraction * sum(seg), 0.0
    for i, s in enumerate(seg):
        if run + s >= target:
            return (i + (target - run) / s) / samples if s else i / samples
        run += s
    return 1.0


def route_backdrop(*, port_states: dict, reach_fraction: float | None = None, reach_label: str = "") -> str:
    """The Singapore -> Fujairah corridor as large, faded art fixed behind the whole page.

    port_states: {"Fujairah": ("recommended" | "feasible" | "removed" | "missing", note), "Singapore": (...)}
    reach_fraction: share of the Singapore -> Fujairah leg the vessel covers before hitting its
                    safety reserve (None or >= 1 means it reaches). Past that point the arc is red and dashed.
    Graphic only, no text, and aria-hidden: every fact it shows is stated in words on the page
    (the removed card, the What if thresholds), so it never competes with the content over it.
    """
    sg, fj, c = _BACKDROP_PORTS["Singapore"], _BACKDROP_PORTS["Fujairah"], _BACKDROP_CTRL
    parts = []
    if reach_fraction is not None and reach_fraction < 1:
        t = _t_at_fraction(sg, c, fj, max(0.0, reach_fraction))
        (a0, a1, a2), (b0, b1, b2) = _split_quad(sg, c, fj, t)
        parts.append(f'<path class="bd-arc" d="M{a0[0]:.0f} {a0[1]:.0f} Q {a1[0]:.0f} {a1[1]:.0f} {a2[0]:.0f} {a2[1]:.0f}" stroke="url(#bd-grad)"/>')
        parts.append(f'<path class="bd-arc is-short" d="M{b0[0]:.0f} {b0[1]:.0f} Q {b1[0]:.0f} {b1[1]:.0f} {b2[0]:.0f} {b2[1]:.0f}"/>')
        parts.append(f'<circle class="bd-reach" cx="{a2[0]:.0f}" cy="{a2[1]:.0f}" r="11"/>')
    else:
        parts.append(f'<path class="bd-arc" d="M{sg[0]:.0f} {sg[1]:.0f} Q {c[0]:.0f} {c[1]:.0f} {fj[0]:.0f} {fj[1]:.0f}" stroke="url(#bd-grad)"/>')
    # No text in the backdrop: big labels behind the inputs and results made them harder to read.
    # The port names are in the small route at the top; RECOMMENDED / REMOVED are stated on the cards.
    for port, (x, y) in _BACKDROP_PORTS.items():
        state, _note = port_states.get(port, ("feasible", ""))
        parts.append(f'<circle class="bd-end is-{state}" cx="{x:.0f}" cy="{y:.0f}" r="13"/>')
    fj_state = port_states.get("Fujairah", ("feasible", ""))[0]
    sg_state = port_states.get("Singapore", ("feasible", ""))[0]
    return ('<div class="route-backdrop no-motion" aria-hidden="true"><svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice">'
            f'<defs><linearGradient id="bd-grad" gradientUnits="userSpaceOnUse" x1="{sg[0]:.0f}" y1="{sg[1]:.0f}" x2="{fj[0]:.0f}" y2="{fj[1]:.0f}">'
            f'<stop offset="0" class="bd-stop is-{sg_state}"/><stop offset="1" class="bd-stop is-{fj_state}"/></linearGradient></defs>'
            f'{"".join(parts)}</svg></div>')


# ── Morning brief (Market intelligence page) ─────────────────────────────────
# Render the morning brief's payload. Every figure, change and date arrives as a
# finished display string from modules/morning_brief, so nothing here calculates,
# rounds or converts. News is headline, publisher, date and link only: feed
# excerpts can quote licensed figures, so they are never shown.

_DIR_WORD = {"up": "Up", "down": "Down", "flat": "Flat"}
# Prices are coloured from the buyer's view (a rising price is red). Volumes and
# counts (bunker sales, transits) get the word only: a colour would imply good or bad.
_PRICE_DIR_CLASS = {"up": "dir-up", "down": "dir-down", "flat": "dir-flat"}


def _tag(item_or_source) -> str:
    tag = item_or_source.get("source_tag") or item_or_source.get("tag")
    return f'<span class="mb-tag">[{escape(tag)}]</span>' if tag else ""


def brief_header(payload: dict) -> str:
    notice = payload.get("trial_notice")
    chip = f'<span class="manual-badge" style="margin:0;">{escape(notice)}</span>' if notice else ""
    return (f'<div class="mb-head"><div><div class="mb-date">Morning brief · {_s(payload, "brief_date_display")}</div>'
            '<div class="mb-meta">Built from free, permitted sources only · every figure carries its source tag</div></div>'
            f'{chip}</div>')


def _status_line(section: dict) -> str:
    status = section.get("status")
    if status == "missing":
        return f'<div class="mb-reason"><span class="missing-badge">MISSING</span>{escape(section.get("reason") or "No reason recorded.")}</div>'
    if status == "not_covered":
        return f'<div class="mb-reason"><span class="unknown-badge">NOT COVERED</span>{escape(section.get("reason") or "")}</div>'
    return ""


def _s(d: dict, key: str) -> str:
    """A payload field as escaped text; a missing or None field becomes empty, never "None" or a crash."""
    value = d.get(key)
    return escape(str(value)) if value is not None else ""


def _https(url) -> str:
    """Only https links are rendered as links; anything else (javascript:, data:, http:) is dropped."""
    return escape(url) if isinstance(url, str) and url.startswith("https://") else ""


# ── Charts (morning brief) ───────────────────────────────────────────────────
# Drawn from the payload's `series`, whose points carry their own display
# strings: these builders only place marks; they calculate no figure. Hover
# is CSS only (Streamlit runs no scripts in page text): each point or bar is a
# hit band larger than its mark, showing a crosshair and its value and date.

def _edge(x: float) -> str:
    """Tooltip anchoring so it never leaves the card: left third opens right, right third opens left."""
    return " ch-pt-start" if x < 34 else " ch-pt-end" if x > 66 else ""


def _chart_label(series: dict, name: str) -> str:
    pts = series["points"]
    return (f'{name}: {len(pts)} values from {pts[0]["date_display"]} to {pts[-1]["date_display"]}; '
            f'latest {pts[-1]["display"]}')


def _points(series) -> list:
    """The series' points if every one can be drawn (a value and both display strings), else []."""
    pts = (series or {}).get("points") or []
    ok = all(isinstance(p.get("value"), (int, float)) and isinstance(p.get("display"), str)
             and isinstance(p.get("date_display"), str) for p in pts)
    return pts if ok and len(pts) >= 2 else []


def _tip(bold: str, rest: str) -> str:
    # aria-hidden: screen readers get the chart's aria-label (or the sr-only headline) instead.
    return f'<span class="ch-tip" aria-hidden="true"><b>{bold}</b>{rest}</span>'


def line_chart(series: dict, name: str = "", uid: str = "") -> str:
    """One series as a line with a soft area under it, points placed by date (gaps such as
    weekends and holidays stay visible). Its scale spans the series' own low to high."""
    from datetime import date
    pts = _points(series)
    if not pts:
        return ""
    values = [p["value"] for p in pts]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.12 or abs(hi) * 0.05 or 1.0
    lo, hi = lo - pad, hi + pad
    try:
        days = [date.fromisoformat(p["date"]) for p in pts]
        span = (days[-1] - days[0]).days
        xs = [(d - days[0]).days / span * 100 for d in days] if span > 0 else None
    except (KeyError, TypeError, ValueError):
        xs = None
    if xs is None:
        xs = [i / (len(pts) - 1) * 100 for i in range(len(pts))]
    ys = [(1 - (v - lo) / (hi - lo)) * 100 for v in values]
    line = " ".join(f'{"M" if i == 0 else "L"}{x:.2f},{y:.2f}' for i, (x, y) in enumerate(zip(xs, ys)))
    area = f"{line} L100,100 L0,100 Z"
    # Each point's hit band runs halfway to its neighbours.
    edges = [0.0] + [(a + b) / 2 for a, b in zip(xs, xs[1:])] + [100.0]
    hits = "".join(
        f'<div class="ch-pt{_edge(x)}" style="left:{edges[i]:.2f}%;width:{edges[i + 1] - edges[i]:.2f}%;'
        f'--x:{(x - edges[i]) / max(edges[i + 1] - edges[i], 1e-9) * 100:.2f}%;--y:{y:.2f}%">'
        f'<i class="ch-dot"></i>{_tip(escape(p["display"]), escape(p["date_display"]))}</div>'
        for i, (x, y, p) in enumerate(zip(xs, ys, pts)))
    i_top, i_bottom = values.index(max(values)), values.index(min(values))
    scale = (f'<span class="ch-mark" style="top:{ys[i_top]:.2f}%">{escape(pts[i_top]["display"])}</span>'
             f'<span class="ch-mark ch-mark-low" style="top:{ys[i_bottom]:.2f}%">{escape(pts[i_bottom]["display"])}</span>')
    grad = "ch-fade-" + re.sub(r"[^A-Za-z0-9_-]", "", uid or str(abs(hash(line)) % 10**8))
    return (f'<div class="ch ch-line" role="img" aria-label="{escape(_chart_label(series, name))}">'
            f'<div class="ch-plot"><svg class="ch-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
            f'<defs><linearGradient id="{grad}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="ch-fade-top"/>'
            '<stop offset="1" class="ch-fade-bottom"/></linearGradient></defs>'
            f'<path class="ch-area" fill="url(#{grad})" d="{area}"/><path class="ch-path" d="{line}"/></svg>'
            f'<i class="ch-last" style="--y:{ys[-1]:.2f}%"></i>{scale}{hits}</div>'
            f'<div class="ch-axis"><span>{escape(pts[0]["date_display"])}</span><span>{escape(pts[-1]["date_display"])}</span></div></div>')


def bar_chart(series: dict, name: str = "", compact: bool = False) -> str:
    """One bar per point on a zero baseline (a cut baseline would exaggerate the change).
    Each bar is a full-height column (its hit area stays inside the plot); ::before is the fill."""
    pts = _points(series)
    if not pts:
        return ""
    hi = max(p["value"] for p in pts) or 1.0
    bars = "".join(
        f'<div class="ch-bar{_edge((i + .5) / len(pts) * 100)}" style="--h:{max(p["value"], 0) / hi * 100:.2f}%;--i:{i}">'
        f'{_tip(escape(p["display"]), escape(p["date_display"]))}</div>'
        for i, p in enumerate(pts))
    axis = ("" if compact else
            f'<div class="ch-axis"><span>{escape(pts[0]["date_display"])}</span><span>{escape(pts[-1]["date_display"])}</span></div>')
    return (f'<div class="ch ch-bars{" ch-compact" if compact else ""}" role="img" aria-label="{escape(_chart_label(series, name))}">'
            f'<div class="ch-plot">{bars}</div>{axis}</div>')


def news_timeline(lanes: list, start: str, end: str) -> str:
    """Headline flow in the criterion-bar style: one row per section (name, a pill track, the
    count), each headline an amber tick placed by publication time. Ticks closer than 4% of the
    track merge into one wider tick. Hovering or focusing a tick opens a glass card listing its
    headlines (publisher and date), each a link when the link is https.
    `lanes` = [(title, items)] or [(title, items, reason)]; the reason shows when a lane is empty.
    `start`/`end` are ISO times."""
    from datetime import datetime, timezone
    t0, t1 = datetime.fromisoformat(start), datetime.fromisoformat(end)
    span = (t1 - t0).total_seconds() or 1.0
    rows = []
    for lane in lanes:
        title, items = lane[0], lane[1]
        reason = lane[2] if len(lane) > 2 else ""
        dated = []
        for it in items:
            try:
                x = (datetime.fromisoformat(it["published"]) - t0).total_seconds() / span * 100
            except (KeyError, TypeError, ValueError):
                continue
            dated.append((min(max(x, 0.0), 100.0), it))
        dated.sort(key=lambda d: d[0])
        clusters: list = []
        for x, it in dated:
            if clusters and x - clusters[-1][0][-1] < 4:
                clusters[-1][0].append(x)
                clusters[-1][1].append(it)
            else:
                clusters.append(([x], [it]))
        ticks = []
        for xs, group in clusters:
            x = (xs[0] + xs[-1]) / 2
            entries = []
            for it in group:
                link = _https(it.get("link"))
                head = (f'<a href="{link}" target="_blank" rel="noopener noreferrer">{_s(it, "headline")}</a>' if link
                        else f'<span>{_s(it, "headline")}</span>')
                meta = " · ".join(c for c in (_s(it, "publisher"), _s(it, "published_display")) if c)
                entries.append(f'<li>{head}<span class="nf-meta">{meta}</span></li>')
            n = len(group)
            label = f"{n} headline{'s' if n > 1 else ''}"
            ticks.append(f'<span class="nf-tick{_edge(x)}" tabindex="0" style="left:{x:.2f}%;--n:{min(n, 5)}" '
                         f'aria-label="{escape(title)}: {label}">'
                         f'<span class="nf-pop"><ul>{"".join(entries)}</ul></span></span>')
        count = len(dated)
        track = "".join(ticks) if ticks else f'<span class="nf-empty">{escape(reason) if reason else "no headlines"}</span>'
        rows.append(f'<div class="nf-row"><div class="nf-name">{escape(title)}</div>'
                    f'<div class="nf-track">{track}</div><div class="nf-count">{count}</div></div>')
    t0, t1 = t0.astimezone(timezone.utc), t1.astimezone(timezone.utc)
    fmt = lambda t: f"{t.day} {t:%b %H:%M}"
    return (f'<div class="nf">{"".join(rows)}'
            f'<div class="nf-axis"><span>{fmt(t0)}</span><span>{fmt(t1)} UTC</span></div></div>')


# Short keys for a comparison's basis (the full basis and date stay in the chip's title and for screen readers).
_BASIS_KEY = {"previous published day": "1D", "one week earlier": "1W", "previous 7 days": "7D",
              "previous month": "1M", "same month a year earlier": "1Y"}

# Direction as a small monochrome arrow, not a colour: the word goes to screen readers.
_DIR_ICON = {
    "up": '<path d="M6 9.5V2.5M2.8 5.6L6 2.4l3.2 3.2"/>',
    "down": '<path d="M6 2.5v7M2.8 6.4L6 9.6l3.2-3.2"/>',
    "flat": '<path d="M2.5 6h7"/>',
}


def dir_icon(direction: str) -> str:
    path = _DIR_ICON.get(direction)
    if not path:
        return ""
    return (f'<span class="mb-dir-ico mb-dir-{direction}"><svg viewBox="0 0 12 12" aria-hidden="true">{path}</svg>'
            f'<span class="sr-only">{escape(_DIR_WORD.get(direction, direction))}</span></span>')


def _shared(items: list) -> tuple:
    """(as-of, tag) when every figure in the list shares them, so they are printed once per card."""
    pairs = {(str(i.get("as_of_display") or ""), str(i.get("source_tag") or "")) for i in items}
    return next(iter(pairs)) if len(pairs) == 1 else ("", "")


def brief_figures(items: list, *, prices: bool = False, chart: str = "") -> str:
    """One block per figure: short name, value, a chip per comparison (arrow, key, amount and
    percentage; the full basis and date in the chip's title), then its chart. The as-of date and
    source tag are printed once by `brief_section` when all figures share them, else per figure.
    The source's notes (e.g. MPA's "preliminary") sit in one "About this data" fold, each once."""
    shared_asof, _ = _shared(items)
    rows, notes = [], []
    for it in items:
        chips = []
        for ch in it.get("changes") or []:
            direction = ch.get("direction") or ""
            basis = str(ch.get("basis") or "")
            key = _BASIS_KEY.get(basis, basis)
            # pct_display is None when the previous value is 0 (no percentage exists); leave it out.
            parts = ["no change"] if direction == "flat" else [x for x in (_s(ch, "abs_display"), _s(ch, "pct_display")) if x]
            full = f'vs {ch.get("compared_with") or ""} ({basis})'
            chips.append(f'<span class="mb-chip" title="{escape(full)}">{dir_icon(direction)}'
                         f'<span class="mb-chip-key">{escape(key)}</span>{" · ".join(parts)}'
                         f'<span class="sr-only"> {escape(full)}</span></span>')
        graphic = ""
        if chart and it.get("series"):
            graphic = (line_chart(it["series"], it.get("label", ""), uid=str(it.get("id", ""))) if chart == "line"
                       else bar_chart(it["series"], it.get("label", ""), compact=bool(rows)))
        elif chart and it.get("series_note"):
            graphic = f'<div class="mb-nochart">No chart: {_s(it, "series_note")}</div>'
        note = (str(it["notes"]), _tag(it)) if it.get("notes") else None
        if note and note not in notes:
            notes.append(note)
        meta = "" if shared_asof else f'<div class="mb-stat-meta">{_s(it, "as_of_display")}{_tag(it)}</div>'
        name = _s(it, "short_label") or _s(it, "label")
        rows.append(f'<div class="mb-stat{" mb-stat-lead" if not rows else ""}">'
                    f'<div class="mb-stat-name" title="{_s(it, "label")}">{name}</div>'
                    f'<div class="mb-stat-value">{_s(it, "display")}</div>'
                    f'<div class="mb-chips">{"".join(chips)}</div>{meta}{graphic}</div>')
    about = ""
    if notes:
        about = ('<details class="mb-about"><summary>About this data</summary>'
                 + "".join(f'<p>{escape(n)}{tag}</p>' for n, tag in notes) + '</details>')
    return "".join(rows) + about


def brief_news(items: list) -> str:
    """Headline (linked when the link is https), publisher, wire agency or author when named, date, source tag. No excerpt."""
    rows = []
    for it in items:
        credit = [_s(it, "publisher")]
        if it.get("wire_agency"):
            credit.append(f'via {_s(it, "wire_agency")}')
        if it.get("author"):
            credit.append(f'by {_s(it, "author")}')
        credit.append(_s(it, "published_display"))
        link = _https(it.get("link"))
        headline = (f'<a href="{link}" target="_blank" rel="noopener noreferrer">{_s(it, "headline")}</a>' if link
                    else f'<span>{_s(it, "headline")}</span>')
        rows.append(f'<div class="mb-news">{headline}<div class="mb-news-meta">{" · ".join(c for c in credit if c)}{_tag(it)}</div></div>')
    return "".join(rows)


def brief_section(section: dict, body: str = "") -> str:
    """A section card: title, then one chip with the date and source when every figure shares
    them (the cadence moves to its title), its state (ok / MISSING / NOT COVERED with the reason),
    then the body."""
    asof, tag = _shared(section.get("items") or [])
    cadence = escape(section.get("cadence") or "")
    if asof:
        right = (f'<span class="mb-asof" title="{cadence}">{escape(asof)}'
                 f'{f"<span class=mb-tag>[{escape(tag)}]</span>" if tag else ""}</span>')
    else:
        right = f'<div class="mb-cadence">{cadence}</div>'
    return (f'<div class="info-card"><div class="mb-sec-head"><div class="info-card-title">{_s(section, "title")}</div>'
            f'{right}</div>{_status_line(section)}{body}</div>')


def brief_subsection(section: dict, body: str = "") -> str:
    return f'<div class="mb-sub">{_s(section, "title")}</div>{_status_line(section)}{body}'


def brief_sources(sources: list) -> str:
    def links(s: dict) -> str:
        out = [f'<a href="{u}" target="_blank" rel="noopener noreferrer">{label}</a>'
               for label, u in (("Source", _https(s.get("url"))), ("Terms", _https(s.get("terms_url")))) if u]
        return " · ".join(out)
    rows = "".join(
        f'<div class="mb-src"><span class="mb-tag" style="margin:0;">[{_s(s, "tag")}]</span>'
        f'<div><b>{_s(s, "name")}</b>{" · " + _s(s, "publisher") if s.get("publisher") else ""}<br>'
        f'Licence: {_s(s, "licence")}. {_s(s, "credit")} {links(s)}</div></div>'
        for s in sources)
    return f'<div class="info-card"><div class="info-card-title">Sources</div>{rows}</div>'
