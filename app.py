"""
BrokerBrief — Maritime Commercial Decision Support Platform
Run with: streamlit run app.py

Architecture:
  Homepage (decision entry point)
  → Bunkering Strategy module (scenario → options → constraints → scoring → confidence → workspace)
  → Market Intelligence (repositioned dashboard, supporting role)
"""

import streamlit as st
import pandas as pd
from datetime import date

from modules.data import load_data, REQUIRED_COLUMNS, is_sample, real_rows
from modules.signals import compute_signals, SignalResult
from modules.brief import generate_brief
from modules.report import generate_email, generate_linkedin
from modules.pdf_export import generate_pdf_bytes
from modules.bunker import compute_bunker_spreads
from modules.eia import fetch_all as eia_fetch_all
from modules.portwatch import fetch_port_activity

from modules.decision.scenario import (
    BunkeringScenario, FuelGrade, RiskProfile, FuelAvailability,
)
from modules.decision.options import generate_options
from modules.decision.constraint_engine import (
    run_constraint_engine, CONGESTION_WAIT_HOURS, PORT_BUNKERING_TIME_HOURS,
)
from modules.decision.evaluation_engine import score_options, WEIGHT_SETS
from modules.decision.confidence_model import compute_confidence
from modules.decision.market_data import assemble_market_data
from modules.provenance import Freshness, Provenance, SAMPLE_LABEL

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BrokerBrief",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap');
:root {
    --black:#0D1117; --surface:#161B22; --surface2:#1C2330; --bdr:#30363D;
    --text:#E6EDF3; --muted:#8B949E; --amber:#F0A500; --amber-dim:#7A5300;
    --blue:#58A6FF; --red:#FF6B6B; --green:#3FB950;
    --font-head:'Space Grotesk',sans-serif; --font-body:'Inter',sans-serif; --font-mono:'JetBrains Mono',monospace;
}
html,body,[data-testid="stAppViewContainer"]{background:var(--black)!important;font-family:var(--font-body);color:var(--text);}
[data-testid="stHeader"]{background:rgba(13,17,23,0.85)!important;}
[data-testid="stSidebar"]{background:var(--surface)!important;border-right:1px solid var(--bdr);}
[data-testid="stSidebar"] *{color:var(--muted)!important;}
[data-testid="stSidebar"] .stRadio label p{color:var(--text)!important;font-family:var(--font-body);font-size:.9rem;}
.sidebar-brand{font-family:var(--font-head);font-size:1.25rem;font-weight:600;color:var(--text)!important;letter-spacing:-.3px;padding:.5rem 0 .15rem;}
.sidebar-brand span{color:var(--amber)!important;}
.sidebar-tagline{font-family:var(--font-mono);font-size:.62rem;color:var(--amber)!important;letter-spacing:.12em;text-transform:uppercase;margin-bottom:1.5rem;}
.page-title{font-family:var(--font-head);font-weight:600;font-size:1.9rem;color:var(--text);letter-spacing:-.5px;margin-bottom:.25rem;}
.page-subtitle{font-family:var(--font-mono);font-size:.7rem;color:var(--amber);text-transform:uppercase;letter-spacing:.1em;margin-bottom:1.75rem;}
.home-hero{font-family:var(--font-head);font-weight:700;font-size:2.4rem;color:var(--text);letter-spacing:-1px;line-height:1.15;margin:1rem 0 .75rem;}
.home-hero em{color:var(--amber);font-style:normal;}
.home-sub{font-size:1.05rem;color:var(--muted);margin-bottom:2rem;line-height:1.65;max-width:640px;}
.module-card{background:var(--surface);border:1px solid var(--bdr);border-radius:8px;padding:1.5rem 1.75rem;margin-bottom:1rem;}
.module-card-active{border-left:3px solid var(--amber);}
.module-card-soon{opacity:.5;}
.module-title{font-family:var(--font-head);font-weight:600;font-size:1.05rem;color:var(--text);margin-bottom:.35rem;}
.module-desc{font-size:.85rem;color:var(--muted);line-height:1.65;}
.module-desc strong{color:var(--text);}
.soon-badge{display:inline-block;font-family:var(--font-mono);font-size:.6rem;background:var(--surface2);color:var(--muted);border:1px solid var(--bdr);border-radius:4px;padding:.15rem .5rem;margin-left:.5rem;vertical-align:middle;}
.live-badge{display:inline-block;font-family:var(--font-mono);font-size:.6rem;background:rgba(63,185,80,.12);color:var(--green);border:1px solid rgba(63,185,80,.35);border-radius:4px;padding:.15rem .45rem;margin-left:.5rem;vertical-align:middle;}
.manual-badge{display:inline-block;font-family:var(--font-mono);font-size:.6rem;background:rgba(240,165,0,.1);color:var(--amber);border:1px solid var(--amber-dim);border-radius:4px;padding:.15rem .45rem;margin-left:.5rem;vertical-align:middle;}
.missing-badge{display:inline-block;font-family:var(--font-mono);font-size:.6rem;background:rgba(255,107,107,.1);color:var(--red);border:1px solid rgba(255,107,107,.35);border-radius:4px;padding:.15rem .45rem;margin-left:.5rem;vertical-align:middle;}
.user-badge{display:inline-block;font-family:var(--font-mono);font-size:.6rem;background:rgba(88,166,255,.1);color:var(--blue);border:1px solid rgba(88,166,255,.35);border-radius:4px;padding:.15rem .45rem;margin-left:.5rem;vertical-align:middle;}
.stale-badge{display:inline-block;font-family:var(--font-mono);font-size:.6rem;background:rgba(255,107,107,.22);color:var(--red);border:1px solid var(--red);border-radius:4px;padding:.15rem .45rem;margin-left:.5rem;vertical-align:middle;font-weight:600;}
.unknown-badge{display:inline-block;font-family:var(--font-mono);font-size:.6rem;background:var(--surface2);color:var(--muted);border:1px solid var(--bdr);border-radius:4px;padding:.15rem .45rem;margin-left:.5rem;vertical-align:middle;}
.rec-card{background:var(--surface2);border:1px solid var(--amber-dim);border-left:3px solid var(--amber);border-radius:8px;padding:1.75rem 2rem;margin-bottom:1.25rem;}
.rec-label{font-family:var(--font-mono);font-size:.62rem;color:var(--amber);text-transform:uppercase;letter-spacing:.12em;margin-bottom:.5rem;}
.rec-title{font-family:var(--font-head);font-weight:600;font-size:1.3rem;color:var(--text);margin-bottom:.4rem;}
.rec-body{font-size:.9rem;color:var(--muted);line-height:1.65;}
.alt-card{background:var(--surface);border:1px solid var(--bdr);border-radius:8px;padding:1.25rem 1.5rem;margin-bottom:1rem;}
.alt-title{font-family:var(--font-head);font-weight:600;font-size:1rem;color:var(--text);margin-bottom:.3rem;}
.infeasible-card{background:var(--surface);border:1px solid rgba(255,107,107,.3);border-left:3px solid var(--red);border-radius:8px;padding:1.1rem 1.4rem;margin-bottom:.85rem;}
.infeasible-title{font-family:var(--font-head);font-weight:600;font-size:.95rem;color:var(--red);margin-bottom:.3rem;}
.infeasible-reason{font-size:.8rem;color:var(--muted);line-height:1.6;}
.rule-tag{display:inline-block;font-family:var(--font-mono);font-size:.62rem;background:rgba(255,107,107,.12);color:var(--red);border:1px solid rgba(255,107,107,.3);border-radius:4px;padding:.1rem .45rem;margin-right:.5rem;}
.warn-strip{background:rgba(240,165,0,.07);border:1px solid var(--amber-dim);border-radius:6px;padding:.6rem .9rem;font-size:.78rem;color:var(--amber);margin:.5rem 0;line-height:1.55;}
.score-pill{display:inline-block;font-family:var(--font-mono);font-weight:500;font-size:1rem;color:var(--amber);}
.conf-row{display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem;}
.conf-label{font-family:var(--font-mono);font-size:.68rem;color:var(--muted);width:180px;flex-shrink:0;}
.conf-bar-wrap{flex:1;background:var(--surface2);border-radius:3px;height:7px;}
.conf-bar-fill{height:7px;border-radius:3px;background:var(--amber);}
.conf-val{font-family:var(--font-mono);font-size:.68rem;color:var(--text);width:44px;text-align:right;}
.info-card{background:var(--surface);border-radius:8px;padding:1.25rem 1.5rem;margin-bottom:1rem;border:1px solid var(--bdr);}
.info-card-title{font-family:var(--font-mono);font-weight:500;font-size:.72rem;color:var(--amber);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.65rem;}
.data-note{font-family:var(--font-mono);font-size:.65rem;color:var(--muted);border-top:1px solid var(--bdr);padding-top:.75rem;margin-top:1.5rem;line-height:1.7;}
.assumption-item{font-size:.8rem;color:var(--muted);padding:.25rem 0;line-height:1.6;}
.provenance-row{font-family:var(--font-mono);font-size:.72rem;color:var(--muted);padding:.35rem 0;border-bottom:1px solid var(--surface2);}
.tone-badge{display:inline-block;font-family:var(--font-mono);font-weight:500;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;padding:.3rem .8rem;border-radius:4px;margin-bottom:.75rem;border:1px solid;}
.tone-bullish{background:rgba(63,185,80,.1);color:var(--green);border-color:rgba(63,185,80,.35);}
.tone-cautious{background:rgba(240,165,0,.1);color:var(--amber);border-color:var(--amber-dim);}
.tone-mixed{background:var(--surface2);color:var(--muted);border-color:var(--bdr);}
.tone-bearish{background:rgba(255,107,107,.1);color:var(--red);border-color:rgba(255,107,107,.35);}
.tone-neutral{background:rgba(88,166,255,.1);color:var(--blue);border-color:rgba(88,166,255,.35);}
.tone-soft{background:rgba(240,165,0,.06);color:var(--amber);border-color:var(--amber-dim);}
.brief-card{background:var(--surface);border:1px solid var(--bdr);border-radius:10px;padding:2rem 2.25rem 1.75rem;margin-bottom:1.5rem;border-left:3px solid var(--amber);}
.brief-card-label{font-family:var(--font-mono);font-size:.62rem;color:var(--amber);text-transform:uppercase;letter-spacing:.12em;margin-bottom:.45rem;}
.brief-card-value{font-size:.95rem;color:var(--text);line-height:1.65;margin-bottom:1rem;}
.brief-card-headline{font-family:var(--font-head);font-weight:600;font-size:1.2rem;color:var(--text);line-height:1.45;margin-bottom:.5rem;}
.brief-card-talking{font-size:.9rem;font-style:italic;color:var(--muted);border-left:2px solid var(--amber);padding-left:.9rem;margin:1rem 0;line-height:1.6;}
.brief-card-risk{font-family:var(--font-mono);font-size:.72rem;color:var(--amber);margin-top:1rem;}
.stat-pill-row{display:flex;gap:.75rem;flex-wrap:wrap;margin:1rem 0;}
.stat-pill{background:var(--surface2);border:1px solid var(--bdr);border-radius:6px;padding:.5rem .85rem;min-width:112px;}
.stat-pill-label{font-family:var(--font-mono);font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;}
.stat-pill-value{font-family:var(--font-mono);font-weight:500;font-size:.95rem;color:var(--text);}
.dir-up{color:var(--red)!important;} .dir-down{color:var(--green)!important;} .dir-flat{color:var(--blue)!important;}
.dir-rising{color:var(--amber)!important;} .dir-easing{color:var(--green)!important;} .dir-stable{color:var(--blue)!important;}
.report-block{background:var(--surface);border:1px solid var(--bdr);border-radius:8px;padding:1.25rem 1.5rem;font-family:var(--font-mono);font-size:.76rem;color:var(--text);white-space:pre-wrap;line-height:1.7;}
h1,h2,h3,h4{font-family:var(--font-head)!important;color:var(--text)!important;}
p,li,span,label{color:var(--text);}
[data-testid="stMarkdownContainer"] p{color:var(--text);}
.stButton>button{background:var(--amber)!important;color:#000!important;border:none!important;border-radius:6px!important;font-family:var(--font-head)!important;font-weight:500!important;}
.stButton>button:hover{opacity:.88;}
[data-testid="stExpander"]{background:var(--surface)!important;border:1px solid var(--bdr)!important;border-radius:8px!important;}
[data-testid="stExpander"] summary{color:var(--text)!important;}
div[data-baseweb="input"],div[data-baseweb="select"]{background:var(--surface2)!important;border-color:var(--bdr)!important;}
div[data-baseweb="input"] input,div[data-baseweb="select"] div{color:var(--text)!important;}
[data-testid="stNumberInput"] input{color:var(--text)!important;background:var(--surface2)!important;}
[data-testid="stDataFrame"]{background:var(--surface)!important;border:1px solid var(--bdr)!important;border-radius:8px;}
[data-testid="stAlert"]{background:var(--surface)!important;border:1px solid var(--bdr)!important;color:var(--text)!important;border-radius:8px!important;}
[data-testid="stTabs"] button{color:var(--muted)!important;font-family:var(--font-head)!important;}
[data-testid="stTabs"] button[aria-selected="true"]{color:var(--amber)!important;}
hr{border-color:var(--bdr)!important;}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
_defaults = {
    "df": None, "data_source": "none", "eia_key": "", "eia_data": None,
    "portwatch_data": None, "decision_result": None, "nav": "home",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v
# Start with no market rows: demo data loads only on request.
if st.session_state["df"] is None:
    st.session_state["df"] = load_data(source="none")


def _load_demo_data():
    st.session_state["df"] = load_data(source="sample")
    st.session_state["data_source"] = "sample"
    st.session_state["decision_result"] = None


def _clear_demo_data():
    st.session_state["df"] = load_data(source="none")
    st.session_state["data_source"] = "none"
    st.session_state["decision_result"] = None

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-brand">⚓ Broker<span>Brief</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-tagline">Commercial Decision Support</div>', unsafe_allow_html=True)

    page = st.radio("Navigation", [
        "🏠  Home",
        "🧭  Bunkering Strategy",
        "📈  Market Intelligence",
        "📂  Data Input",
        "🔌  Live Data",
    ], label_visibility="collapsed")

    st.markdown("---")
    st.markdown('<div style="font-family:JetBrains Mono,monospace;font-size:0.65rem;color:#8B949E;margin-bottom:4px;">EIA API KEY</div>', unsafe_allow_html=True)
    eia_key_input = st.text_input("EIA Key", value=st.session_state["eia_key"],
                                   type="password", label_visibility="collapsed",
                                   placeholder="Paste EIA key here")
    if eia_key_input != st.session_state["eia_key"]:
        st.session_state["eia_key"] = eia_key_input
        st.session_state["eia_data"] = None

    if st.button("↺  Refresh Live Data"):
        st.session_state["eia_data"] = None
        st.session_state["portwatch_data"] = None
        st.rerun()

    if is_sample(st.session_state["df"]).any():
        st.button("✕  Clear demo data", on_click=_clear_demo_data)
    else:
        st.button("Load demo data (invented values)", on_click=_load_demo_data, key="demo_sidebar",
                  help="Invented bunker, freight and congestion rows for trying the "
                       "Bunkering Strategy page. Never used in Market Intelligence.")

    st.markdown("---")
    st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.65rem;color:#8B949E;">Date: {date.today().strftime("%d %b %Y")}</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-family:JetBrains Mono,monospace;font-size:0.6rem;color:#6B7480;line-height:1.6;margin-top:.75rem;">BrokerBrief v0.3<br>No source, no certainty.<br>The decision belongs to you.</div>', unsafe_allow_html=True)

# ── Fetch live data (cached per session) ──────────────────────────────────────
if st.session_state["eia_key"] and st.session_state["eia_data"] is None:
    with st.spinner("Fetching EIA data..."):
        st.session_state["eia_data"] = eia_fetch_all(st.session_state["eia_key"])
if st.session_state["portwatch_data"] is None:
    with st.spinner("Fetching Portwatch data..."):
        st.session_state["portwatch_data"] = fetch_port_activity()

df             = st.session_state["df"]
eia_data       = st.session_state["eia_data"]
portwatch_data = st.session_state["portwatch_data"]

# Persistent on every page while any demo row is loaded (including demo rows
# re-uploaded as a CSV, hence checking the rows rather than data_source).
if is_sample(df).any():
    st.warning(
        "**DEMO DATA ACTIVE — invented values, not real market data.** "
        "They feed the Bunkering Strategy page only; Market Intelligence ignores them. "
        "Clear them from the sidebar."
    )


def _badge_for(prov: "Provenance | None") -> str:
    if prov is None:
        return '<span class="missing-badge">MISSING</span>'
    if prov.source_name == SAMPLE_LABEL:
        return f'<span class="stale-badge">{SAMPLE_LABEL}</span>'
    label = prov.quality_tier.value.replace("_", " ")
    fresh = prov.freshness()
    if fresh is Freshness.STALE:
        age_str = f"as of {prov.as_of:%Y-%m-%d}" if prov.as_of else "age unknown"
        return f'<span class="stale-badge">{label} — STALE ({age_str})</span>'
    if fresh is Freshness.UNKNOWN:
        return f'<span class="unknown-badge">{label} — freshness unknown</span>'
    css_class = {
        "LIVE_API": "live-badge",
        "MANUAL_ENTRY": "manual-badge",
        "USER_OVERRIDE": "user-badge",
    }[prov.quality_tier.value]
    return f'<span class="{css_class}">{label}</span>'


# ════════════════════════════════════════════════════════════════════════════
# PAGE: HOME — DECISION ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════
if "Home" in page:
    st.markdown('<div class="home-hero">What commercial decision<br>are you making <em>today?</em></div>', unsafe_allow_html=True)
    st.markdown('<div class="home-sub">BrokerBrief evaluates your scenario against live market intelligence, removes options that don\'t work, and shows you the viable alternatives with transparent trade-offs. The final decision is always yours.</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="module-card module-card-active">
        <div class="module-title">🧭 Evaluate Bunkering Strategy</div>
        <div class="module-desc">Should your vessel bunker now, wait until the next port, or split the stem?
        BrokerBrief generates the feasible strategies, scores them transparently, and explains every trade-off.
        <br><br><strong>→ Select "Bunkering Strategy" in the sidebar to begin.</strong></div>
    </div>
    <div class="module-card module-card-soon">
        <div class="module-title">📋 Supplier Quote Evaluation <span class="soon-badge">COMING SOON</span></div>
        <div class="module-desc">Is the quote you just received competitive? Compare against market benchmarks and recent trends.</div>
    </div>
    <div class="module-card module-card-soon">
        <div class="module-title">🗺 Port Selection Analysis <span class="soon-badge">COMING SOON</span></div>
        <div class="module-desc">Which bunkering port offers the best overall commercial outcome across your voyage?</div>
    </div>
    <div class="module-card">
        <div class="module-title">📈 Market Briefing</div>
        <div class="module-desc">Today's market tone, freight and bunker signals, and port congestion — the intelligence layer
        that supports every decision. <strong>→ Available now under "Market Intelligence".</strong></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="data-note">BrokerBrief is a GPS for maritime commercial decisions. It identifies viable routes, ranks them, and explains the trade-offs. You stay in control of the wheel.</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: BUNKERING STRATEGY — SCENARIO INPUT + DECISION WORKSPACE
# ════════════════════════════════════════════════════════════════════════════
elif "Bunkering" in page:
    st.markdown('<div class="page-title">Bunkering Strategy</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Singapore – Fujairah corridor · Decision support module</div>', unsafe_allow_html=True)

    # ── Preset demo scenarios ────────────────────────────────────────────────
    with st.expander("📌 Load a demo scenario", expanded=False):
        st.caption("Picking a scenario also loads demo data (invented values), replacing any uploaded CSV.")
        c1, c2, c3 = st.columns(3)
        preset = None
        with c1:
            if st.button("Scenario 1\nBoth ports feasible"):
                preset = dict(fuel=900.0, cons=45.0, qty=1000.0, eta_sg=1.0, eta_fuj=8.0, flex=36.0, sim_fuj_missing=False)
        with c2:
            if st.button("Scenario 2\nFujairah unreachable"):
                preset = dict(fuel=280.0, cons=45.0, qty=1000.0, eta_sg=1.0, eta_fuj=8.0, flex=36.0, sim_fuj_missing=False)
        with c3:
            if st.button("Scenario 3\nFujairah price missing"):
                preset = dict(fuel=900.0, cons=45.0, qty=1000.0, eta_sg=1.0, eta_fuj=8.0, flex=36.0, sim_fuj_missing=True)
        if preset:
            # The documented scenario results rely on demo prices, so picking a
            # scenario loads demo data (and its banner) if it isn't loaded yet.
            # This replaces any uploaded CSV, as the button's help text says.
            if not is_sample(st.session_state["df"]).any():
                _load_demo_data()
            st.session_state["preset"] = preset
            st.session_state["decision_result"] = None
            st.rerun()

    p = st.session_state.get("preset", dict(fuel=900.0, cons=45.0, qty=1000.0, eta_sg=1.0, eta_fuj=8.0, flex=36.0, sim_fuj_missing=False))

    # ── Scenario input form ──────────────────────────────────────────────────
    st.markdown("### Vessel Scenario")
    col1, col2, col3 = st.columns(3)
    with col1:
        vessel_name  = st.text_input("Vessel name (display only)", value="MV Demo Trader")
        current_loc  = st.text_input("Current location / last port", value="Colombo")
        destination  = st.text_input("Destination / next major port", value="Rotterdam")
        fuel_grade   = st.selectbox("Required fuel grade", [g.value for g in FuelGrade], index=0)
    with col2:
        fuel_remaining = st.number_input("Fuel remaining (MT)", min_value=0.0, value=p["fuel"], step=10.0)
        daily_cons     = st.number_input("Daily consumption (MT/day)", min_value=1.0, value=p["cons"], step=1.0)
        required_qty   = st.number_input("Required bunker quantity (MT)", min_value=0.0, value=p["qty"], step=50.0)
        safety_reserve = st.number_input("Safety reserve (MT) — 0 = use default", min_value=0.0, value=0.0, step=10.0,
                                          help="Default: max(10% of remaining fuel, 24h consumption). No universal industry standard — set per your company SMS.")
    with col3:
        eta_sg   = st.number_input("ETA to Singapore (days)", min_value=0.1, value=p["eta_sg"], step=0.5)
        eta_fuj  = st.number_input("ETA to Fujairah (days)", min_value=0.1, value=p["eta_fuj"], step=0.5)
        flex     = st.number_input("Schedule flexibility (hours)", min_value=0.0, value=p["flex"], step=6.0)
        risk     = st.selectbox("Risk profile", [r.value for r in RiskProfile], index=1)

    with st.expander("Optional inputs — improve confidence"):
        c1, c2, c3 = st.columns(3)
        with c1:
            sg_avail = st.selectbox("Singapore fuel grade availability",
                                     [a.value for a in FuelAvailability], index=2)
        with c2:
            fuj_avail = st.selectbox("Fujairah fuel grade availability",
                                      [a.value for a in FuelAvailability], index=2)
        with c3:
            sim_fuj_missing = st.checkbox("Simulate: Fujairah price unavailable",
                                           value=p["sim_fuj_missing"],
                                           help="Demo flag — treats Fujairah VLSFO price as missing to show data-gap behaviour.")

    run = st.button("⚓  Evaluate Bunkering Strategy", type="primary")

    if run:
        scenario = BunkeringScenario(
            vessel_name          = vessel_name,
            current_location     = current_loc,
            destination          = destination,
            fuel_remaining_mt    = fuel_remaining,
            daily_consumption_mt = daily_cons,
            required_quantity_mt = required_qty,
            fuel_grade           = FuelGrade(fuel_grade),
            eta_singapore_days   = eta_sg,
            eta_fujairah_days    = eta_fuj,
            schedule_flexibility_hours = flex,
            safety_reserve_mt    = safety_reserve if safety_reserve > 0 else None,
            singapore_vlsfo_available = FuelAvailability(sg_avail),
            fujairah_vlsfo_available  = FuelAvailability(fuj_avail),
            risk_profile         = RiskProfile(risk),
        )

        market_data = assemble_market_data(
            df, eia_data, portwatch_data,
            simulate_fujairah_missing=sim_fuj_missing,
        )

        options = generate_options(scenario)
        options = run_constraint_engine(options, scenario, market_data["congestion_signals"])
        options = score_options(options, scenario, market_data)
        confidence = compute_confidence(scenario, market_data)

        st.session_state["decision_result"] = {
            "scenario": scenario, "options": options,
            "confidence": confidence, "market_data": market_data,
        }

    # ── Decision Workspace ────────────────────────────────────────────────────
    result = st.session_state.get("decision_result")
    if result:
        scenario   = result["scenario"]
        options    = result["options"]
        confidence = result["confidence"]
        market_data = result["market_data"]

        feasible   = sorted([o for o in options if o.is_feasible], key=lambda o: o.rank or 99)
        infeasible = [o for o in options if not o.is_feasible]

        st.markdown("---")
        st.markdown('<div class="page-title">Decision Workspace</div>', unsafe_allow_html=True)

        # 1 — SCENARIO SUMMARY
        reserve = scenario.effective_safety_reserve_mt()
        st.markdown(f"""
        <div class="info-card">
            <div class="info-card-title">1 · Scenario Summary</div>
            <div style="font-size:.85rem;color:#8B949E;line-height:1.7;">
            <strong>{scenario.vessel_name}</strong> — currently near {scenario.current_location}, bound for {scenario.destination}.<br>
            Fuel remaining: <strong>{scenario.fuel_remaining_mt:,.0f} MT</strong> ·
            Consumption: {scenario.daily_consumption_mt:,.0f} MT/day ·
            Required stem: <strong>{scenario.required_quantity_mt:,.0f} MT {scenario.fuel_grade.value}</strong><br>
            ETA Singapore: {scenario.eta_singapore_days:.1f} days · ETA Fujairah: {scenario.eta_fujairah_days:.1f} days ·
            Schedule flexibility: {scenario.schedule_flexibility_hours:.0f}h<br>
            Safety reserve in effect: <strong>{reserve:,.0f} MT</strong>
            {"(user-defined)" if scenario.safety_reserve_mt else "(default: max of 10% remaining fuel or 24h consumption)"} ·
            Risk profile: {scenario.risk_profile.value}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 2 — FEASIBILITY CHECK
        st.markdown('<div class="info-card"><div class="info-card-title">2 · Feasibility Check</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:.82rem;color:#8B949E;">Options considered: {len(options)} · Feasible: {len(feasible)} · Removed: {len(infeasible)}</div>', unsafe_allow_html=True)
        if infeasible:
            for o in infeasible:
                st.markdown(f"""
                <div class="infeasible-card">
                    <div class="infeasible-title">✕ {o.label}</div>
                    <div class="infeasible-reason"><span class="rule-tag">RULE {o.infeasible_rule}</span>{o.infeasible_reason}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:.82rem;color:#3FB950;padding:.5rem 0;">✓ All generated options passed the Constraint Engine.</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        if not feasible:
            st.error("No feasible bunkering options exist for this scenario. Review fuel remaining, ETAs, and schedule flexibility.")
        else:
            best = feasible[0]

            # 3 — RECOMMENDED OPTION
            warn_html = f'<div class="warn-strip">⚠ {best.warning_message}</div>' if best.is_warning else ""
            st.markdown(f"""
            <div class="rec-card">
                <div class="rec-label">3 · Recommended Option ⭐ — strongest overall commercial balance based on current information</div>
                <div class="rec-title">{best.label}</div>
                <div class="rec-body">{best.description}</div>
                <div style="margin-top:.75rem;"><span style="font-family:JetBrains Mono,monospace;font-size:.7rem;color:#3FB950;">COMPOSITE SCORE</span>
                <span style="font-family:Space Grotesk,sans-serif;font-weight:700;font-size:1.3rem;color:#fff;margin-left:.75rem;">{best.score:.1f} / 100</span></div>
            </div>
            """, unsafe_allow_html=True)
            if best.is_warning:
                st.markdown(warn_html, unsafe_allow_html=True)

            # 4 — ALTERNATIVES
            if len(feasible) > 1:
                st.markdown('<div class="info-card"><div class="info-card-title">4 · Alternative Options</div>', unsafe_allow_html=True)
                for o in feasible[1:]:
                    warn = f'<div class="warn-strip">⚠ {o.warning_message}</div>' if o.is_warning else ""
                    st.markdown(f"""
                    <div class="alt-card">
                        <div class="alt-title">#{o.rank} — {o.label} <span class="score-pill" style="float:right;">{o.score:.1f}</span></div>
                        <div style="font-size:.82rem;color:#8B949E;line-height:1.55;">{o.description}</div>
                        {warn}
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # 5 — TRADE-OFF COMPARISON
            st.markdown('<div class="info-card"><div class="info-card-title">5 · Trade-off Comparison</div>', unsafe_allow_html=True)
            weights = WEIGHT_SETS[scenario.risk_profile]
            st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:.7rem;color:#8B949E;margin-bottom:.75rem;">Scoring weights ({scenario.risk_profile.value}): Expected cost {weights["expected_cost"]:.0%} · Operational risk {weights["operational_risk"]:.0%} · Schedule risk {weights["schedule_risk"]:.0%}</div>', unsafe_allow_html=True)
            rows = []
            for o in feasible:
                bd = getattr(o, "_score_breakdown", {})
                rows.append({
                    "Rank": o.rank, "Option": o.label,
                    "Expected Cost": bd.get("expected_cost", {}).get("score", "–"),
                    "Operational Risk": bd.get("operational_risk", {}).get("score", "–"),
                    "Schedule Risk": bd.get("schedule_risk", {}).get("score", "–"),
                    "Composite": o.score,
                })
            st.dataframe(pd.DataFrame(rows).set_index("Rank"), use_container_width=True)
            with st.expander("Show scoring reasoning per option"):
                for o in feasible:
                    bd = getattr(o, "_score_breakdown", {})
                    st.markdown(f"**{o.label}**")
                    for factor in ("expected_cost", "operational_risk", "schedule_risk"):
                        f = bd.get(factor, {})
                        st.markdown(f"- *{factor.replace('_',' ').title()}* ({f.get('score','–')}): {f.get('note','')}")
            st.markdown('</div>', unsafe_allow_html=True)

            # 6 — DECISION CONFIDENCE
            st.markdown('<div class="info-card"><div class="info-card-title">6 · Decision Confidence</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="font-family:Space Grotesk,sans-serif;font-weight:700;font-size:1.8rem;color:#E6EDF3;">{confidence["overall"]:.0f}% <span style="font-size:.9rem;color:#8B949E;">({confidence["label"]})</span></div>', unsafe_allow_html=True)
            for label, comp in [("Data Quality (40%)", "data_quality"),
                                 ("Signal Agreement (30%)", "signal_agreement"),
                                 ("Scenario Completeness (30%)", "scenario_completeness")]:
                s = confidence[comp]["score"]
                st.markdown(f"""
                <div class="conf-row"><span class="conf-label">{label}</span>
                <div class="conf-bar-wrap"><div class="conf-bar-fill" style="width:{min(100,max(0,s))}%"></div></div>
                <span class="conf-val">{s:.0f}%</span></div>
                """, unsafe_allow_html=True)
            if confidence["reductions"]:
                st.markdown('<div style="font-family:JetBrains Mono,monospace;font-size:.68rem;color:#F0A500;margin-top:.75rem;">CONFIDENCE REDUCED BECAUSE:</div>', unsafe_allow_html=True)
                for r in confidence["reductions"][:8]:
                    st.markdown(f'<div style="font-size:.76rem;color:#8B949E;padding:.15rem 0;">— {r}</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

            # 7 — WHY THIS OPTION RANKS HIGHEST
            bd = getattr(best, "_score_breakdown", {})
            reasoning_parts = [f.get("note", "") for f in
                               (bd.get("expected_cost", {}), bd.get("operational_risk", {}), bd.get("schedule_risk", {}))
                               if f.get("note")]
            st.markdown(f"""
            <div class="info-card"><div class="info-card-title">7 · Why This Option Ranks Highest</div>
            <div style="font-size:.85rem;color:#8B949E;line-height:1.7;">{" ".join(reasoning_parts)}</div></div>
            """, unsafe_allow_html=True)

            # 8 — ASSUMPTIONS
            assumptions = [
                "Vessel ETA remains unchanged from user input.",
                f"Daily consumption of {scenario.daily_consumption_mt:,.0f} MT/day is accurate as provided.",
                "Waiting times are estimated from congestion signals, not confirmed port data.",
                f"Bunkering operation times assumed: Singapore {PORT_BUNKERING_TIME_HOURS['Singapore']:.0f}h, Fujairah {PORT_BUNKERING_TIME_HOURS['Fujairah']:.0f}h (indicative).",
                "No unexpected geopolitical or weather disruption assumed.",
                "Minimum/maximum stem sizes use indicative POC values, not confirmed supplier data.",
            ]
            st.markdown('<div class="info-card"><div class="info-card-title">8 · Assumptions</div>' +
                        "".join(f'<div class="assumption-item">• {a}</div>' for a in assumptions) +
                        '</div>', unsafe_allow_html=True)

            # 9 — DATA SOURCES
            st.markdown('<div class="info-card"><div class="info-card-title">9 · Data Sources</div>', unsafe_allow_html=True)
            for source, prov in market_data["provenance"].items():
                st.markdown(f'<div class="provenance-row">{source} {_badge_for(prov)}</div>', unsafe_allow_html=True)
            st.markdown('<div class="data-note">No source, no certainty. Missing data lowers confidence but does not remove physically feasible options. The final commercial decision remains with you — BrokerBrief cannot observe supplier relationships, internal budgets, charterparty obligations, or company risk appetite.</div></div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: MARKET INTELLIGENCE (repositioned dashboard)
# ════════════════════════════════════════════════════════════════════════════
elif "Market Intelligence" in page:
    # Demo rows are invented: Market Intelligence must never be generated from
    # them, so everything on this page works from real rows only.
    mi_df = real_rows(df)
    signals: SignalResult = compute_signals(mi_df)
    has_freight    = (mi_df["signal_type"] == "freight").any()
    has_bunker     = (mi_df["signal_type"] == "bunker").any()
    has_congestion = (mi_df["signal_type"] == "congestion").any()
    used_types     = ["freight", "bunker", "congestion", "news"]
    brief_sources  = set(mi_df.loc[mi_df["signal_type"].isin(used_types), "source_name"].dropna().astype(str))
    if portwatch_data and portwatch_data.get("success"):
        cong_signals = portwatch_data["congestion_signals"]
        if cong_signals:
            counts = {"Rising": 0, "Stable": 0, "Easing": 0}
            for v in cong_signals.values():
                counts[v] = counts.get(v, 0) + 1
            signals.congestion_direction = max(counts, key=counts.get)
            has_congestion = True
            brief_sources.add(portwatch_data["source_name"])
    brief_sources = sorted(brief_sources)
    # The template brief speaks to freight and bunkers, so it needs real rows for both.
    brief_ready = bool(has_freight and has_bunker)
    missing_parts = [name for name, ok in (("freight", has_freight), ("bunker", has_bunker)) if not ok]
    missing_msg = (f"No real {' or '.join(missing_parts)} data loaded, so no brief is generated. "
                   "Demo data is never used here.")

    st.markdown('<div class="page-title">Market Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Supporting evidence layer — informs every decision module</div>', unsafe_allow_html=True)

    tab_brief, tab_signals, tab_bunker, tab_reports = st.tabs(
        ["📋 Today's Brief", "📡 Signal Engine", "⛽ Bunker Spread Watch", "📄 Reports"])

    with tab_brief:
        dir_color = {"Up": "dir-up", "Down": "dir-down", "Flat": "dir-flat",
                     "Rising": "dir-rising", "Easing": "dir-easing", "Stable": "dir-stable"}
        def _pill(label, value):
            return (f'<div class="stat-pill"><div class="stat-pill-label">{label}</div>'
                    f'<div class="stat-pill-value {dir_color.get(value,"")}">{value}</div></div>')
        pills = (_pill("Freight", signals.freight_direction if has_freight else "MISSING")
                 + _pill("Bunkers", signals.bunker_direction if has_bunker else "MISSING")
                 + _pill("Congestion", signals.congestion_direction if has_congestion else "MISSING"))
        brent_pill = ""
        if eia_data and eia_data.get("spot", {}).get("success"):
            spot = eia_data["spot"]
            brent_pill = (f'<div class="stat-pill"><div class="stat-pill-label">Brent Crude</div>'
                          f'<div class="stat-pill-value {dir_color.get(spot["direction"],"")}">${spot["current_value"]:.2f}/bbl</div></div>')
        if not brief_ready:
            st.markdown(f"""
            <div class="brief-card">
                <div class="brief-card-label">Main Headline <span class="missing-badge">MISSING</span></div>
                <div class="brief-card-value">{missing_msg}</div>
                <div class="stat-pill-row">{pills}{brent_pill}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            brief = generate_brief(signals)
            tone_css = {"Bullish": "tone-bullish", "Cautiously Bullish": "tone-cautious",
                        "Mixed": "tone-mixed", "Bearish": "tone-bearish",
                        "Neutral": "tone-neutral", "Soft Demand / Mixed": "tone-soft"}.get(signals.market_tone, "tone-mixed")
            st.markdown(f'<span class="tone-badge {tone_css}">Market Tone: {signals.market_tone}</span>', unsafe_allow_html=True)
            st.markdown(f"""
            <div class="brief-card">
                <div class="brief-card-label">Main Headline</div>
                <div class="brief-card-headline">{brief["headline"]}</div>
                <div class="stat-pill-row">{pills}{brent_pill}</div>
                <div class="brief-card-label" style="margin-top:1rem;">Key Route to Watch</div>
                <div class="brief-card-value">{signals.key_route}</div>
                <div class="brief-card-label">Suggested Talking Point</div>
                <div class="brief-card-talking">"{brief["talking_point"]}"</div>
                <div class="brief-card-risk">⚠ {brief["risk_note"]}</div>
            </div>
            """, unsafe_allow_html=True)

    with tab_signals:
        if signals.signal_table:
            table_df = pd.DataFrame(signals.signal_table)
            def _colour_dir(val):
                return {"Up":"color:#FF6B6B;font-weight:600","Down":"color:#FF6B6B;font-weight:600",
                        "Flat":"color:#58A6FF;font-weight:600","Rising":"color:#F0A500;font-weight:600",
                        "Easing":"color:#3FB950;font-weight:600","Stable":"color:#58A6FF;font-weight:600"}.get(val,"")
            styled = (table_df.style.applymap(_colour_dir, subset=["Direction"])
                      .format({"Pct Change": "{:+.2f}%", "Confidence": "{:.0%}"})
                      .hide(axis="index"))
            st.dataframe(styled, use_container_width=True, height=420)
        else:
            st.warning("MISSING — no real freight, bunker or congestion rows loaded. Demo data is never shown here.")
        if portwatch_data and portwatch_data.get("success"):
            st.markdown("**Live Portwatch Congestion Signals**")
            for port, sig in portwatch_data["congestion_signals"].items():
                st.markdown(f"- **{port}**: {sig}")

    with tab_bunker:
        bunker_data = compute_bunker_spreads(mi_df)
        if not bunker_data["available"]:
            st.warning("MISSING — no real bunker price rows loaded. Demo data is never shown here.")
        else:
            for fuel_type, info in bunker_data["by_fuel"].items():
                spread = info["spread"]
                st.markdown(f"""
                <div class="info-card"><div class="info-card-title">{fuel_type}</div>
                <div style="font-size:.85rem;color:#8B949E;line-height:1.6;">
                Cheapest: <strong style="color:#3FB950;">{info["cheapest_port"]} — USD {info["cheapest_price"]:,.0f}/MT</strong> ·
                Most expensive: <strong style="color:#FF6B6B;">{info["most_expensive_port"]} — USD {info["most_expensive_price"]:,.0f}/MT</strong><br>
                Spread: USD {spread:,.0f}/MT → theoretical 1,000 MT stem difference of <strong>USD {spread*1000:,.0f}</strong>
                before operational, credit, supplier, and timing considerations.</div></div>
                """, unsafe_allow_html=True)

    with tab_reports:
        if not brief_ready:
            st.warning(f"MISSING — {missing_msg}")
        else:
            brief = generate_brief(signals)
            r1, r2, r3 = st.tabs(["✉️ Email", "📄 PDF", "💼 LinkedIn"])
            with r1:
                email_text = generate_email(signals, brief)
                st.markdown(f'<div class="report-block">{email_text}</div>', unsafe_allow_html=True)
                st.download_button("⬇ Download .txt", email_text.encode(), f"brokerbrief_email_{date.today()}.txt", "text/plain")
            with r2:
                if st.button("Generate PDF"):
                    pdf_bytes = generate_pdf_bytes(signals, brief, brief_sources)
                    st.download_button("📄 Download PDF", pdf_bytes, f"brokerbrief_{date.today()}.pdf", "application/pdf")
            with r3:
                linkedin_text = generate_linkedin(signals, brief)
                st.markdown(f'<div class="report-block">{linkedin_text}</div>', unsafe_allow_html=True)
                st.download_button("⬇ Download .txt", linkedin_text.encode(), f"brokerbrief_linkedin_{date.today()}.txt", "text/plain")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: DATA INPUT
# ════════════════════════════════════════════════════════════════════════════
elif "Data Input" in page:
    st.markdown('<div class="page-title">Data Input</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Upload a CSV, or load demo data (invented values) for the Bunkering Strategy page</div>', unsafe_allow_html=True)

    col_a, col_b = st.columns([3, 1])
    with col_a:
        uploaded = st.file_uploader("Upload market data CSV", type=["csv"],
                                     help="Must include: " + ", ".join(REQUIRED_COLUMNS))
    with col_b:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Load demo data (invented values)", on_click=_load_demo_data, key="demo_page"):
            st.success("Demo data loaded — invented values, used by Bunkering Strategy only.")

    if uploaded is not None:
        try:
            uploaded_df = pd.read_csv(uploaded)
            missing_cols = [c for c in REQUIRED_COLUMNS if c not in uploaded_df.columns]
            if missing_cols:
                st.error(f"Missing required columns: {', '.join(missing_cols)}")
            else:
                st.session_state["df"] = uploaded_df
                st.session_state["data_source"] = "uploaded"
                st.success(f"CSV loaded: {len(uploaded_df)} rows.")
        except Exception as exc:
            st.error(f"Could not read file: {exc}")

    st.markdown("---")
    st.markdown("**Data Preview**")
    st.dataframe(st.session_state["df"], use_container_width=True)

    st.markdown("**Validation Report**")
    if st.session_state["df"].empty:
        st.info("No market rows loaded.")
    for field in ["source_name", "source_url", "updated_at", "confidence"]:
        df_display = st.session_state["df"]
        if field in df_display.columns:
            missing_n = df_display[field].isna().sum() + (df_display[field].astype(str).str.strip() == "").sum()
            if missing_n == 0:
                st.markdown(f"✅ `{field}` — all {len(df_display)} rows populated")
            else:
                st.warning(f"⚠️ `{field}` — {missing_n} rows missing or blank")
        else:
            st.error(f"❌ `{field}` column not found")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: LIVE DATA
# ════════════════════════════════════════════════════════════════════════════
elif "Live Data" in page:
    st.markdown('<div class="page-title">Live Data</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Status of all live API connections</div>', unsafe_allow_html=True)

    st.markdown("### EIA Crude Oil API")
    if not st.session_state["eia_key"]:
        st.warning("No EIA API key entered. Add your key in the sidebar. Register free at https://www.eia.gov/opendata/")
    elif eia_data:
        spot  = eia_data.get("spot", {})
        fcast = eia_data.get("forecast", {})
        if spot.get("success"):
            st.success(f"✅ Brent spot: ${spot['current_value']:.2f}/bbl ({spot['latest_date']}) — {spot['pct_change']:+.2f}% — {spot['direction']}")
        else:
            st.error(f"❌ Spot fetch failed: {spot.get('error')}")
        if fcast.get("success"):
            st.success(f"✅ Forecast: ${fcast['nearest_value']:.2f}/bbl for {fcast['nearest_month']}")
            st.dataframe(pd.DataFrame(fcast["forecast_rows"]), use_container_width=True)
        else:
            st.error(f"❌ Forecast fetch failed: {fcast.get('error')}")

    st.markdown("---")
    st.markdown("### IMF Portwatch API")
    if portwatch_data and portwatch_data.get("success"):
        st.success(f"✅ Connected — {len(portwatch_data['ports'])} port activity rows fetched")
        for port, sig in portwatch_data["congestion_signals"].items():
            colour = {"Rising": "🔴", "Stable": "🔵", "Easing": "🟢"}.get(sig, "⚪")
            st.markdown(f"{colour} **{port}**: {sig}")
        with st.expander("Show raw port data"):
            st.dataframe(pd.DataFrame(portwatch_data["ports"]), use_container_width=True)
    else:
        err = portwatch_data.get("error", "Unknown error") if portwatch_data else "Not fetched"
        st.error(f"❌ Portwatch: {err}")

    st.markdown('<div class="data-note">Live data is cached per session. Click "↺ Refresh Live Data" in the sidebar to force a fresh fetch. EIA updates daily. Portwatch updates weekly on Tuesdays.</div>', unsafe_allow_html=True)
