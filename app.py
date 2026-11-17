"""
BrokerBrief — Maritime Commercial Decision Support Platform
Run with: streamlit run app.py

Architecture:
  Homepage (decision entry point)
  → Bunkering Strategy module (scenario → options → constraints → scoring → confidence → workspace)
  → Market intelligence (the morning brief, built live from free, permitted sources)
  → Data input (your own CSV: signals, bunker spreads and reports)
"""

import hashlib
import os
import time

import streamlit as st
import pandas as pd
from datetime import date

from modules.data import load_data, REQUIRED_COLUMNS, engine_inputs, is_sample, real_rows
from modules.signals import compute_signals, SignalResult
from modules.brief import generate_brief
from modules.report import generate_email, generate_linkedin
from modules.pdf_export import generate_pdf_bytes
from modules.bunker import compute_bunker_spreads
from modules.eia import fetch_all as eia_fetch_all, _redact
from modules.morning_brief.payload import fetch_and_build
from datetime import datetime, timezone
from modules.portwatch import PORTWATCH_CREDIT, fetch_port_activity

from modules.decision.scenario import (
    BunkeringScenario, FuelGrade, RiskProfile, FuelAvailability, Scrubber,
)
from modules.decision.options import generate_options
from modules.decision.constraint_engine import (
    run_constraint_engine, CONGESTION_WAIT_HOURS, PORT_BUNKERING_TIME_HOURS,
)
from modules.decision.evaluation_engine import score_options, WEIGHT_SETS
from modules.decision.confidence_model import compute_confidence
from modules.decision.market_data import assemble_market_data
from modules.provenance import Freshness, Provenance, SAMPLE_LABEL
from modules import ui, whatif
from dataclasses import replace
from html import escape
from pathlib import Path

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BrokerBrief",
    page_icon=str(Path(__file__).resolve().parent / "assets" / "brokerbrief-anchor.png"),
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ── (BrokerBrief design system: styles/tokens.css, components.css, streamlit.css)
st.markdown(ui.stylesheet_html(), unsafe_allow_html=True)

# ── Live data without a manual step ──────────────────────────────────────────
# On the deployed app the EIA key is a server-side secret (Streamlit secrets,
# or the EIA_API_KEY environment variable), so a visitor gets live Brent with
# nothing to paste. Results are cached for LIVE_TTL_SECONDS and shared by all
# visitors: EIA releases weekly and PortWatch lags 8–10 days, so refetching on
# every visit would only add load and failure points.
#
# A failed fetch is never kept in that 3-hour cache (it would show an error for
# hours). It is held for FAILURE_RETRY_SECONDS instead, so that during an outage
# the app retries every few minutes rather than on every click: without this,
# each widget edit would wait on network timeouts and hammer the failing API.
LIVE_TTL_SECONDS = 3 * 60 * 60
FAILURE_RETRY_SECONDS = 5 * 60


def _server_eia_key() -> str:
    try:
        key = st.secrets.get("EIA_API_KEY", "")
    except Exception:          # no secrets file at all (local run, tests)
        key = ""
    return key or os.environ.get("EIA_API_KEY", "")


SERVER_EIA_KEY = _server_eia_key()


@st.cache_data(ttl=LIVE_TTL_SECONDS, show_spinner=False)
def _cached_eia() -> dict:
    return eia_fetch_all(SERVER_EIA_KEY)


@st.cache_data(ttl=LIVE_TTL_SECONDS, show_spinner=False)
def _cached_portwatch() -> dict:
    return fetch_port_activity()


@st.cache_resource
def _recent_failures() -> dict:
    """name -> (monotonic time, failed result). Shared by all sessions."""
    return {}


def _live(name: str, cached_fetch, succeeded) -> dict:
    """The cached result of `cached_fetch`, with failures held only briefly."""
    failures = _recent_failures()
    held = failures.get(name)
    if held and time.monotonic() - held[0] < FAILURE_RETRY_SECONDS:
        return held[1]
    data = cached_fetch()
    if succeeded(data):
        failures.pop(name, None)
    else:
        cached_fetch.clear()                       # never keep a failure for 3 hours
        failures[name] = (time.monotonic(), data)
    return data


def _live_eia() -> dict:
    return _live("eia", _cached_eia,
                 lambda d: d.get("spot", {}).get("success") and d.get("forecast", {}).get("success"))


def _live_portwatch() -> dict:
    return _live("portwatch", _cached_portwatch, lambda d: d.get("success"))


@st.cache_data(ttl=LIVE_TTL_SECONDS, show_spinner=False)
def _cached_brief(eia_key: str) -> dict:
    """The morning brief's payload, built by the same fetchers and final gate as the
    scheduled workflow (modules/morning_brief), with no language model. A rule
    breach raises inside build_payload, so only a gated payload is ever shown."""
    try:
        return {"success": True, "payload": fetch_and_build(eia_api_key=eia_key or None)}
    except Exception as exc:          # show the reason rather than take the page down
        message = _redact(f"{type(exc).__name__}: {exc}")
        return {"success": False, "error": message.replace(eia_key, "<redacted>") if eia_key else message}


def _brief_ok(data: dict, eia_key: str) -> bool:
    """A brief built while a feed was down is shown, but not kept for 3 hours: it counts
    as a failure so the next visit after 5 minutes rebuilds it. A missing EIA key is
    not an outage (retrying cannot fix it), so it alone does not trigger a rebuild."""
    if not data.get("success"):
        return False
    return not _outages(data["payload"], eia_key)


# A feed that answered but carried no items is shown on the page but does not trigger a
# rebuild: refetching every source each 5 minutes would not fill an empty feed.
_NOT_AN_OUTAGE = "feed contained no items"


def _feed_problems(payload: dict, eia_key: str) -> dict:
    """source id -> reason, for every feed that failed in this build. A missing EIA key
    is reported in the Prices section itself, so it is left out here."""
    errors = dict((payload.get("validation") or {}).get("feed_errors") or {})
    if not eia_key:
        errors.pop("eia_spot", None)
    return errors


def _outages(payload: dict, eia_key: str) -> dict:
    return {k: v for k, v in _feed_problems(payload, eia_key).items() if v != _NOT_AN_OUTAGE}


def _live_brief(eia_key: str) -> dict:
    def fetch() -> dict:
        return _cached_brief(eia_key)
    fetch.clear = _cached_brief.clear
    # Note: a failure clears every key's cached brief. In deployment only the server key is used.
    # Hold failures per key (hashed, so the key itself is never stored as a name).
    name = "brief:" + hashlib.sha256(eia_key.encode()).hexdigest()[:12]
    return _live(name, fetch, lambda d: _brief_ok(d, eia_key))


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

def _on_eia_key():
    st.session_state["eia_key"] = st.session_state["eia_key_input"]
    st.session_state["eia_data"] = None


def _refresh_live():
    _cached_portwatch.clear()
    _cached_brief.clear()
    _recent_failures().clear()
    st.session_state["eia_data"] = None
    st.session_state["portwatch_data"] = None


# ── Bunkering strategy: scenario state ───────────────────────────────────────
# Step inputs live in st.session_state["bk"], not only in widget keys: Streamlit
# drops a widget's value when the widget isn't drawn on a run, and each step draws
# only its own inputs. Widgets use "bkw_<field>" keys, seeded from bk when absent.
GRADES = [g.value for g in FuelGrade]
PROFILES = [r.value for r in RiskProfile]
AVAIL = [a.value for a in FuelAvailability]
SCRUBBERS = [s.value for s in Scrubber]
BK_DEFAULTS = dict(vessel="MT Demo Trader", loc="South China Sea, ex Zhoushan (in ballast)", dest="Ras Tanura",
                   grade=GRADES[0], scrubber=SCRUBBERS[0], enters_eca=False,
                   fuel=900.0, cons=45.0, qty=1000.0, reserve=0.0, eta_sg=1.0, eta_fuj=11.5, flex=36.0,
                   risk=PROFILES[1], sg_avail=AVAIL[2], fuj_avail=AVAIL[2], sim_fuj_missing=False)
# The README demo scenarios (tests/test_demo_mode.py mirrors these).
PRESETS = {
    "Both ports feasible":    dict(fuel=900.0, cons=45.0, qty=1000.0, eta_sg=1.0, eta_fuj=11.5, flex=36.0, sim_fuj_missing=False),
    "Fujairah unreachable":   dict(fuel=280.0, cons=45.0, qty=1000.0, eta_sg=1.0, eta_fuj=11.5, flex=36.0, sim_fuj_missing=False),
    "Fujairah price missing": dict(fuel=900.0, cons=45.0, qty=1000.0, eta_sg=1.0, eta_fuj=11.5, flex=36.0, sim_fuj_missing=True),
}
STEPS = {1: "1 · Vessel", 2: "2 · Route", 3: "3 · Prices"}
STEP_COPY = {
    1: ("Vessel and fuel", "What the vessel carries, burns and needs."),
    2: ("Route and schedule", "Where it is, where it's going, and how much time it can spare."),
    3: ("Prices and preferences", "No free, redistributable source of port bunker prices exists, so BrokerBrief never "
        "fills these in: enter your own quotes for the chosen grade, upload a CSV on the Data input page, or load a "
        "demo scenario. The other answers are optional and raise confidence."),
}
PORT_CODE = {"Singapore": "SIN", "Fujairah": "FUJ"}
if "bk" not in st.session_state:
    st.session_state["bk"] = dict(BK_DEFAULTS)


def _set_bk(values: dict):
    st.session_state["bk"].update(values)
    for field in values:
        st.session_state.pop(f"bkw_{field}", None)   # re-seeded from bk on the next draw


def _apply_preset(name: str):
    # The documented scenario results rely on demo prices, so a preset loads demo
    # data (and its banner) if it isn't loaded yet, replacing any uploaded CSV.
    if not is_sample(st.session_state["df"]).any():
        _load_demo_data()
    # Typed bunker prices would override the demo prices the documented results rely on.
    typed = [k for k in st.session_state["bk"] if k.startswith(("sg_price_", "fuj_price_"))]
    for k in typed:
        st.session_state["bk"].pop(k)
        st.session_state.pop(f"bkw_{k}", None)
    _set_bk(PRESETS[name])
    st.session_state.pop("bk_selected", None)


def _bk_input(widget, label, field, default=None, **kw):
    if field not in st.session_state["bk"]:
        st.session_state["bk"][field] = default   # e.g. a price for a grade not used before
    key = f"bkw_{field}"
    if key not in st.session_state:
        st.session_state[key] = st.session_state["bk"][field]
    st.session_state["bk"][field] = widget(label, key=key, **kw)


def _goto_step(n: int):
    st.session_state["bk_step"] = n
    st.session_state["bk_step_last"] = n


def _keep_step():
    # Clicking the active segment deselects it; keep the user on their step instead.
    if st.session_state["bk_step"] is None:
        st.session_state["bk_step"] = st.session_state.get("bk_step_last", 1)
    st.session_state["bk_step_last"] = st.session_state["bk_step"]


def _keep_risk():
    if st.session_state["bkw_risk"] is None:
        st.session_state["bkw_risk"] = st.session_state["bk"]["risk"]


def _toggle_detail(option_id: str):
    st.session_state["bk_selected"] = None if st.session_state.get("bk_selected") == option_id else option_id


def _apply_whatif():
    _set_bk(dict(fuel=st.session_state["wif_fuel"], eta_fuj=st.session_state["wif_eta"],
                 flex=st.session_state["wif_flex"]))


def _scenario_from(bk: dict) -> BunkeringScenario:
    return BunkeringScenario(
        vessel_name=bk["vessel"], current_location=bk["loc"], destination=bk["dest"],
        fuel_remaining_mt=bk["fuel"], daily_consumption_mt=bk["cons"], required_quantity_mt=bk["qty"],
        fuel_grade=FuelGrade(bk["grade"]),
        eta_singapore_days=bk["eta_sg"], eta_fujairah_days=bk["eta_fuj"],
        schedule_flexibility_hours=bk["flex"],
        safety_reserve_mt=bk["reserve"] if bk["reserve"] > 0 else None,
        singapore_vlsfo_available=FuelAvailability(bk["sg_avail"]),
        fujairah_vlsfo_available=FuelAvailability(bk["fuj_avail"]),
        risk_profile=RiskProfile(bk["risk"]),
        scrubber=Scrubber(bk["scrubber"]),
        voyage_enters_eca=bk["enters_eca"],
    )


def _bars(o):
    bd = getattr(o, "_score_breakdown", {})
    return [(name, bd.get(key, {}).get("score", 0)) for key, name in ui.CRITERIA]


def _route_backdrop_for(scenario, feasible, infeasible, bk) -> str:
    """Port states and the fuel reach for the background route.

    Reach uses the same quantities as rule F1: usable fuel = fuel on board minus the
    safety reserve in effect, burned at the daily consumption. If that runs out before
    the Fujairah ETA, the arc is solid only for that share of the leg.
    """
    states = {"Singapore": ("feasible", ""), "Fujairah": ("feasible", "")}
    for o in infeasible:
        if o.port in states and not o.is_partial:
            states[o.port] = ("removed", f"REMOVED · {o.infeasible_rule}")
    if feasible:
        best = feasible[0]
        for port in (best.port, best.top_up_port):
            if port in states:
                states[port] = ("recommended", "RECOMMENDED")
    if bk.get("sim_fuj_missing") and states["Fujairah"][0] != "removed":
        states["Fujairah"] = ("missing", "PRICE MISSING")
    usable = scenario.fuel_remaining_mt - scenario.effective_safety_reserve_mt()
    reach_days = max(0.0, usable) / scenario.daily_consumption_mt
    reach = reach_days / scenario.eta_fujairah_days if scenario.eta_fujairah_days else None
    label = f"Reserve reached · day {reach_days:.1f} of {scenario.eta_fujairah_days:.1f}"
    return ui.route_backdrop(port_states=states, reach_fraction=reach, reach_label=label)


def _route(o):
    first = PORT_CODE.get(o.port, o.port)
    return f"{first} then {PORT_CODE.get(o.top_up_port, o.top_up_port)}" if o.top_up_port else f"full stem at {first}"


# ── Fetch live data (shared cache; see LIVE_TTL_SECONDS) ─────────────────────
# Fetched before the sidebar is drawn, so the sidebar can show each feed's status.
# Locally without a server key, a pasted key arrives through a callback, which runs
# before this script, so it is fetched on the same click.
if SERVER_EIA_KEY:
    with st.spinner("Fetching EIA data..."):
        st.session_state["eia_data"] = _live_eia()
elif st.session_state["eia_key"] and st.session_state["eia_data"] is None:
    with st.spinner("Fetching EIA data..."):
        st.session_state["eia_data"] = eia_fetch_all(st.session_state["eia_key"])
with st.spinner("Fetching PortWatch data..."):
    st.session_state["portwatch_data"] = _live_portwatch()

def _feed_status(result: "dict | None") -> tuple:
    """(css state, word) for a feed result: live, stale, age unknown, or error."""
    if not result or not result.get("success"):
        return "error", "error"
    prov = result.get("provenance")
    fresh = prov.freshness() if prov is not None else Freshness.UNKNOWN
    if fresh is Freshness.STALE:
        return "stale", "stale"
    if fresh is Freshness.UNKNOWN:
        return "off", "age unknown"
    return "live", "live"


# ── Sidebar: brand, a quiet page list, then data status and controls ─────────
NAV = ["Home", "Bunkering strategy", "Market intelligence", "Data input", "Live data"]
with st.sidebar:
    st.markdown(ui.sidebar_brand(tagline=False), unsafe_allow_html=True)
    page = st.radio("Navigation", NAV, label_visibility="collapsed")

    st.markdown("---")
    demo_on = bool(is_sample(st.session_state["df"]).any())
    eia_state = (("off", "no key") if not (SERVER_EIA_KEY or st.session_state["eia_key"])
                 else _feed_status((st.session_state["eia_data"] or {}).get("spot")))
    pw_state = _feed_status(st.session_state["portwatch_data"])
    st.markdown('<div class="side-label">Data &amp; connections</div>'
                + ui.feed_row("EIA Brent", *eia_state)
                + ui.feed_row("IMF PortWatch", *pw_state)
                + ui.feed_row("Demo data", *(("on", "on") if demo_on else ("off", "off"))),
                unsafe_allow_html=True)
    with st.expander("Manage data"):
        if SERVER_EIA_KEY:
            # Deployed: nothing for the visitor to enter, and no refresh button: the
            # cache is shared by every visitor, so one visitor must not be able to
            # force refetches for all. The server key is never put in session state
            # or in a widget, so it cannot be sent to a browser.
            st.caption(f"Live data loads automatically and is refetched every "
                       f"{LIVE_TTL_SECONDS // 3600} hours.")
        else:
            # Local run without a configured key: paste one for this session.
            if "eia_key_input" not in st.session_state:
                st.session_state["eia_key_input"] = st.session_state["eia_key"]
            st.text_input("EIA API key", key="eia_key_input", type="password",
                          placeholder="Paste EIA key here", on_change=_on_eia_key)
            st.button("Refresh live data", on_click=_refresh_live, key="refresh_live")
        if demo_on:
            st.button("Clear demo data", on_click=_clear_demo_data, key="demo_clear")
        else:
            st.button("Load demo data (invented values)", on_click=_load_demo_data, key="demo_sidebar",
                      help="Invented bunker, freight and congestion rows for trying the "
                           "Bunkering strategy page. Never used in Market intelligence.")
    today = date.today()
    st.markdown(f'<div class="side-foot" style="margin-top:1.5rem;">{today.day} {today:%B %Y} · v0.3<br>No source, no certainty.</div>',
                unsafe_allow_html=True)

df             = st.session_state["df"]
eia_data       = st.session_state["eia_data"]
portwatch_data = st.session_state["portwatch_data"]

# Persistent on every page while any demo row is loaded (including demo rows
# re-uploaded as a CSV, hence checking the rows rather than data_source).
if is_sample(df).any():
    st.warning(
        "**DEMO DATA ACTIVE — invented values, not real market data.** "
        "They feed the Bunkering Strategy page only, together with fixed demo Brent, forecast "
        "and congestion values in place of the live feeds; Market Intelligence ignores them. "
        "Clear them from the sidebar."
    )
    st.markdown(ui.sample_chip("sample data · illustrative"), unsafe_allow_html=True)


def _chip_for(source: str, prov: "Provenance | None") -> str:
    """A source chip: status dot, source name, and the tier spelt out (never colour alone)."""
    if prov is None:
        state, tier = "is-missing", "MISSING"
    elif prov.source_name == SAMPLE_LABEL:
        state, tier = "is-stale", SAMPLE_LABEL
    else:
        tier = prov.quality_tier.value.replace("_", " ")
        fresh = prov.freshness()
        if fresh is Freshness.STALE:
            age = f"as of {prov.as_of.day} {prov.as_of:%b %Y}" if prov.as_of else "age unknown"
            state, tier = "is-stale", f"{tier} · STALE ({age})"
        elif fresh is Freshness.UNKNOWN:
            state, tier = "is-unknown", f"{tier} · freshness unknown"
        else:
            state = {"LIVE_API": "is-live", "MANUAL_ENTRY": "is-manual",
                     "USER_OVERRIDE": "is-user"}[prov.quality_tier.value]
    return f'<span class="prov-chip {state}">{escape(source)} <span class="prov-tier">{escape(tier)}</span></span>'


# ════════════════════════════════════════════════════════════════════════════
# PAGE: HOME — DECISION ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════
if "Home" in page:
    st.markdown('<div class="home-hero bb-reveal">What commercial decision<br>are you making <em>today?</em></div>', unsafe_allow_html=True)
    st.markdown('<div class="home-sub bb-reveal" style="--i:1">BrokerBrief checks your scenario against live, permitted sources, removes options that can\'t work, and shows every weight and source behind the ranking. You make the call.</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="module-card module-card-active bb-reveal" style="--i:2"><div class="module-title">Evaluate bunkering strategy</div>'
        '<div class="module-desc">Should your vessel bunker now, wait until the next port, or split the stem? BrokerBrief generates the feasible strategies, scores them transparently and explains every trade-off.'
        '<br><br><strong>→ Open "Bunkering strategy" in the sidebar to begin.</strong></div></div>'
        '<div class="module-card bb-reveal" style="--i:3"><div class="module-title">Morning brief</div>'
        '<div class="module-desc">The latest Brent and diesel prices, Singapore bunker sales, ship activity, and sale-and-purchase and events headlines, each with its source and date. '
        '<strong>→ Available now under "Market intelligence".</strong></div></div>'
        '<div class="module-card module-card-soon bb-reveal" style="--i:4"><div class="module-title">Supplier quote evaluation <span class="soon-badge">COMING SOON</span></div>'
        '<div class="module-desc">Is the quote you just received competitive? Compare it against market benchmarks and recent trends.</div></div>'
        '<div class="module-card module-card-soon bb-reveal" style="--i:5"><div class="module-title">Port selection analysis <span class="soon-badge">COMING SOON</span></div>'
        '<div class="module-desc">Which bunkering port offers the best overall commercial outcome across your voyage?</div></div>',
        unsafe_allow_html=True)

    st.markdown('<div class="data-note">BrokerBrief is a GPS for maritime commercial decisions. It identifies viable routes, ranks them, and explains the trade-offs. You stay in control of the wheel.</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: BUNKERING STRATEGY — SCENARIO INPUT + DECISION WORKSPACE
# ════════════════════════════════════════════════════════════════════════════
elif page == "Bunkering strategy":
    head_txt, head_arc = st.columns([3, 2], vertical_alignment="center")
    with head_txt:
        st.markdown(ui.page_header("Where should the vessel bunker?", "Bunkering strategy · Singapore – Fujairah corridor"), unsafe_allow_html=True)
    with head_arc:
        st.markdown(ui.route_arc("Fujairah", "Singapore", compact=True), unsafe_allow_html=True)
    # The large route behind the page. Its colours depend on the results, which are
    # computed further down, so reserve the slot here and fill it once they exist.
    backdrop_slot = st.empty()
    bk = st.session_state["bk"]

    # ── Demo scenarios (they load demo data, replacing any uploaded CSV) ──────
    st.markdown('<div class="field-label">Try a demo scenario · loads invented demo data</div>', unsafe_allow_html=True)
    pcols = st.columns(len(PRESETS))
    for col, name in zip(pcols, PRESETS):
        with col:
            st.button(name, key=f"preset_{name}", on_click=_apply_preset, args=(name,), width="stretch")

    left, right = st.columns([5, 7], gap="large")

    # ── Left: the scenario, in three steps ────────────────────────────────────
    with left:
        if "bk_step" not in st.session_state:
            st.session_state["bk_step"] = 1
        st.segmented_control("Step", list(STEPS), format_func=STEPS.get, key="bk_step",
                             on_change=_keep_step, label_visibility="collapsed")
        step = st.session_state["bk_step"] or st.session_state.get("bk_step_last", 1)
        title, sub = STEP_COPY[step]
        st.markdown(f'<div class="step-head">{title}</div><div class="step-sub">{sub}</div>', unsafe_allow_html=True)
        if step == 1:
            _bk_input(st.text_input, "Vessel name (display only)", "vessel")
            _bk_input(st.selectbox, "Required fuel grade", "grade", options=GRADES,
                      help="VLSFO: max 0.50% sulphur. MGO: distillate. HSFO: above 0.50%, up to "
                           "3.50% sulphur — usable only with a scrubber.")
            _bk_input(st.selectbox, "Scrubber (exhaust gas cleaning system) fitted", "scrubber", options=SCRUBBERS,
                      help="HSFO may only be used, or carried for use, with an approved "
                           "equivalent such as a scrubber (MARPOL Annex VI regulations 14.1 and 4.1).")
            _bk_input(st.number_input, "Fuel remaining (MT)", "fuel", min_value=0.0, step=10.0)
            _bk_input(st.number_input, "Daily consumption (MT/day)", "cons", min_value=1.0, step=1.0)
            _bk_input(st.number_input, "Required bunker quantity (MT)", "qty", min_value=0.0, step=50.0)
        elif step == 2:
            _bk_input(st.text_input, "Current location / last port", "loc")
            _bk_input(st.text_input, "Destination / next major port", "dest")
            _bk_input(st.number_input, "ETA to Singapore (days)", "eta_sg", min_value=0.1, step=0.5)
            _bk_input(st.number_input, "ETA to Fujairah (days)", "eta_fuj", min_value=0.1, step=0.5)
            _bk_input(st.number_input, "Schedule flexibility (hours)", "flex", min_value=0.0, step=6.0)
            _bk_input(st.checkbox, "Voyage enters an emission control area (ECA)", "enters_eca",
                      help="Inside an ECA the fuel used on board must not exceed 0.10% sulphur "
                           "(regulation 14.4). Adds a warning; removes nothing.")
        else:
            grade = bk["grade"]
            # One price per grade: a price typed for one grade is never carried over to another.
            _bk_input(st.number_input, f"Singapore {grade} price (USD/MT) — 0 = not provided", f"sg_price_{grade}",
                      default=0.0, min_value=0.0, step=5.0)
            _bk_input(st.number_input, f"Fujairah {grade} price (USD/MT) — 0 = not provided", f"fuj_price_{grade}",
                      default=0.0, min_value=0.0, step=5.0)
            _bk_input(st.number_input, "Safety reserve (MT) — 0 = use default", "reserve", min_value=0.0, step=10.0,
                      help="Default: max(10% of remaining fuel, 24h consumption). No universal industry standard — set per your company SMS.")
            _bk_input(st.selectbox, "Singapore fuel grade availability", "sg_avail", options=AVAIL)
            _bk_input(st.selectbox, "Fujairah fuel grade availability", "fuj_avail", options=AVAIL)
            _bk_input(st.checkbox, "Simulate: Fujairah price unavailable", "sim_fuj_missing",
                      help="Demo flag — treats the Fujairah price as missing to show data-gap behaviour. "
                           "It overrides any price typed or loaded.")
        back, nxt = st.columns(2)
        with back:
            if step > 1:
                st.button("Back", key="step_back", on_click=_goto_step, args=(step - 1,), width="stretch")
        with nxt:
            if step < 3:
                st.button("Next", key="step_next", type="primary", on_click=_goto_step, args=(step + 1,), width="stretch")
        st.markdown('<div class="live-note">Results on the right update as you type.</div>', unsafe_allow_html=True)

    # ── Right: live results ───────────────────────────────────────────────────
    with right:
        if "bkw_risk" not in st.session_state:
            st.session_state["bkw_risk"] = bk["risk"]
        st.segmented_control("Risk profile · flip it to see how the ranking changes", PROFILES,
                             key="bkw_risk", on_change=_keep_risk)
        bk["risk"] = st.session_state["bkw_risk"] or bk["risk"]
        st.markdown('<div class="info-card-title" style="margin:.75rem 0 .5rem;">Ranked options</div>', unsafe_allow_html=True)

        scenario = _scenario_from(bk)
        # With demo data active, Brent, the forecast and congestion are fixed
        # SAMPLE values too, so demo results never depend on live feeds.
        engine_eia, engine_portwatch = engine_inputs(df, eia_data, portwatch_data)
        sg_price = bk.get(f"sg_price_{scenario.fuel_grade.value}") or 0.0
        fuj_price = bk.get(f"fuj_price_{scenario.fuel_grade.value}") or 0.0
        market_data = assemble_market_data(df, engine_eia, engine_portwatch,
                                           simulate_fujairah_missing=bk["sim_fuj_missing"],
                                           fuel_grade=scenario.fuel_grade.value,
                                           singapore_price_override=sg_price if sg_price > 0 else None,
                                           fujairah_price_override=fuj_price if fuj_price > 0 else None)
        options = whatif.run_pipeline(scenario, market_data)
        scored_ports = {p for o in options if o.is_feasible for p in (o.port, o.top_up_port) if p}
        confidence = compute_confidence(scenario, market_data, scored_ports=scored_ports)
        feasible = sorted([o for o in options if o.is_feasible], key=lambda o: o.rank or 99)
        infeasible = [o for o in options if not o.is_feasible]
        feasible_ids = {o.id for o in feasible}
        selected = st.session_state.get("bk_selected") if st.session_state.get("bk_selected") in feasible_ids else None

        # The corridor behind the page, coloured by this scenario's result.
        backdrop_slot.markdown(_route_backdrop_for(scenario, feasible, infeasible, bk), unsafe_allow_html=True)

        if not feasible:
            st.error("ERROR — No feasible bunkering options exist for this scenario. The What if tab shows what would change that.")
        for i, o in enumerate(feasible):
            st.markdown(ui.option_card(
                label=o.label, route=_route(o), score=o.score or 0, bars=_bars(o),
                recommended=(i == 0), rank=o.rank,
                warning=o.warning_message if o.is_warning else "",
                selected=(o.id == selected), animate=False), unsafe_allow_html=True)
            act1, act2, _ = st.columns([3, 2, 3])
            with act1:
                st.button("Hide breakdown" if o.id == selected else "Score breakdown", key=f"det_{o.id}",
                          on_click=_toggle_detail, args=(o.id,))
            with act2:
                st.checkbox("Compare", key=f"cmp_{o.id}")
            if o.id == selected:
                st.markdown(ui.score_breakdown(label=o.label, description=o.description,
                                               breakdown=getattr(o, "_score_breakdown", {}), score=o.score or 0,
                                               warning=o.warning_message if o.is_warning else ""),
                            unsafe_allow_html=True)
        for o in infeasible:
            st.markdown(f'<div class="no-motion">{ui.infeasible_card(label=o.label, description=o.description, rule=o.infeasible_rule, reason=o.infeasible_reason)}</div>',
                        unsafe_allow_html=True)

        to_compare = [o for o in feasible if st.session_state.get(f"cmp_{o.id}")]
        if len(to_compare) == 2:
            a, b = to_compare
            st.markdown(ui.compare_panel(
                {"label": a.label, "score": a.score or 0, "breakdown": getattr(a, "_score_breakdown", {})},
                {"label": b.label, "score": b.score or 0, "breakdown": getattr(b, "_score_breakdown", {})}),
                unsafe_allow_html=True)
        elif len(to_compare) == 1:
            st.caption("Tick one more option to compare the two side by side.")
        elif len(to_compare) > 2:
            st.caption("Compare works on two options at a time. Untick one.")

        tab_wi, tab_conf, tab_src, tab_table = st.tabs(["What if", "Confidence", "Sources & assumptions", "Score table"])

        with tab_wi:
            base = (float(bk["fuel"]), float(bk["eta_fuj"]), float(bk["flex"]))
            if st.session_state.get("wif_base") != base:
                st.session_state["wif_base"] = base
                st.session_state["wif_fuel"], st.session_state["wif_eta"], st.session_state["wif_flex"] = base
            w1, w2, w3 = st.columns(3)
            with w1:
                st.slider("Fuel on board (MT)", 0.0, max(3000.0, base[0] * 2), key="wif_fuel", step=5.0)
            with w2:
                st.slider("ETA to Fujairah (days)", 0.1, max(20.0, base[1]), key="wif_eta", step=0.1)
            with w3:
                st.slider("Schedule flexibility (h)", 0.0, max(120.0, base[2]), key="wif_flex", step=6.0)
            wi_scen = replace(scenario, fuel_remaining_mt=st.session_state["wif_fuel"],
                              eta_fujairah_days=st.session_state["wif_eta"],
                              schedule_flexibility_hours=st.session_state["wif_flex"])
            wi_opts = whatif.run_pipeline(wi_scen, market_data)
            wi_items = ([(o.label, o.score or 0, None) for o in sorted([o for o in wi_opts if o.is_feasible], key=lambda o: o.rank or 99)]
                        + [(o.label, None, o.infeasible_rule) for o in wi_opts if not o.is_feasible])
            st.markdown('<div class="field-label">Ranking with these values</div>' + ui.whatif_list(wi_items), unsafe_allow_html=True)
            if (st.session_state["wif_fuel"], st.session_state["wif_eta"], st.session_state["wif_flex"]) != base:
                st.button("Apply these values to the scenario", key="wif_apply", type="primary", on_click=_apply_whatif)
            lines = whatif.threshold_sentences(scenario, market_data["congestion_signals"], {o.id: o.label for o in options})
            st.markdown('<div class="info-card-title" style="margin-top:1.25rem;">Where each option switches</div>'
                        + "".join(f'<div class="threshold-line">{escape(l)}</div>' for l in lines), unsafe_allow_html=True)

        with tab_conf:
            conf = ui.confidence_ring(
                data_quality=confidence["data_quality"]["score"],
                signal_agreement=confidence["signal_agreement"]["score"],
                completeness=confidence["scenario_completeness"]["score"],
                overall=confidence["overall"], level=confidence["label"])
            if confidence.get("cap_reason"):
                # Say "capped" only when a cap actually lowered the score, and
                # name the level it was capped at (Medium or Low).
                if confidence["overall"] < confidence["uncapped_overall"]:
                    lead = (f'Capped at {confidence["label"]} '
                            f'(would be {confidence["uncapped_overall"]:.0f}%). ')
                else:
                    lead = "A cap applies, but the score was already below it. "
                conf += ui.warn_strip(lead + confidence["cap_reason"])
            if confidence["reductions"]:
                conf += ('<div class="reduction-label">Confidence reduced because:</div>'
                         + "".join(f'<div class="reduction-item">— {escape(r)}</div>' for r in confidence["reductions"][:8]))
            st.markdown(f'<div class="no-motion">{conf}</div>', unsafe_allow_html=True)

        with tab_src:
            reserve = scenario.effective_safety_reserve_mt()
            assumptions = [
                f"Safety reserve in effect: {reserve:,.0f} MT "
                + ("(user-defined)." if scenario.safety_reserve_mt else "(default: max of 10% remaining fuel or 24h consumption)."),
                "Vessel ETA remains unchanged from user input.",
                f"Daily consumption of {scenario.daily_consumption_mt:,.0f} MT/day is accurate as provided.",
                "Waiting times are estimated from congestion signals, not confirmed port data.",
                f"Bunkering operation times assumed: Singapore {PORT_BUNKERING_TIME_HOURS['Singapore']:.0f}h, Fujairah {PORT_BUNKERING_TIME_HOURS['Fujairah']:.0f}h (indicative).",
                "No unexpected geopolitical or weather disruption assumed.",
                "Minimum/maximum stem sizes use indicative POC values, not confirmed supplier data.",
                "The split stem's Singapore-to-Fujairah leg is checked (rule F4) from the two ETAs and the daily "
                "consumption; fuel burned while waiting and bunkering at Singapore is assumed to be within the ETAs.",
            ] + [f"Congestion at {port} is unknown, so an 8-hour wait is assumed."
                 for port in ("Singapore", "Fujairah")
                 if market_data["congestion_signals"].get(port) not in CONGESTION_WAIT_HOURS]
            # Source, date and licence for every input (PR #4), under the chips.
            details = "".join(
                f'<div class="field-label" style="margin:.2rem 0;">{escape(source)} · {escape(prov.source_name)} · '
                + (f"as of {prov.as_of:%d-%m-%Y}" if prov.as_of else "no source date")
                + f' · licence: {escape(str(prov.licence))}</div>'
                for source, prov in market_data["provenance"].items() if prov is not None)
            chips = "".join(_chip_for(source, prov) for source, prov in market_data["provenance"].items())
            # PortWatch data drives the waiting times here, and its licence asks for this credit.
            pw_credit = (f'<div class="field-label" style="margin:.4rem 0 0;">{escape(PORTWATCH_CREDIT)}</div>'
                         if any(p is not None and "portwatch" in p.source_name.lower()
                                for p in market_data["provenance"].values()) else "")
            st.markdown(f'<div class="provenance-row">{chips}</div><div style="margin-top:.75rem;">{details}{pw_credit}</div>'
                        '<div class="info-card-title" style="margin-top:1.25rem;">Assumptions</div>'
                        + "".join(f'<div class="assumption-item">• {escape(a)}</div>' for a in assumptions)
                        + '<div class="data-note" style="margin-top:1.25rem;">No source, no certainty. Missing data lowers confidence but does not remove physically feasible options. The final commercial decision remains with you — BrokerBrief cannot observe supplier relationships, internal budgets, charterparty obligations, or company risk appetite.</div>',
                        unsafe_allow_html=True)

        with tab_table:
            weights = WEIGHT_SETS[scenario.risk_profile]
            st.markdown(f'<div class="field-label">Scoring weights ({scenario.risk_profile.value}): Expected cost {weights["expected_cost"]:.0%} · '
                        f'Operational risk {weights["operational_risk"]:.0%} · Schedule risk {weights["schedule_risk"]:.0%}</div>',
                        unsafe_allow_html=True)
            if feasible:
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
                st.dataframe(pd.DataFrame(rows).set_index("Rank"), width="stretch")


elif page == "Market intelligence":
    st.markdown(ui.page_header("Where does the market stand?", "Market intelligence · the morning brief, from free and permitted sources"),
                unsafe_allow_html=True)
    with st.spinner("Building the morning brief..."):
        brief_result = _live_brief(SERVER_EIA_KEY or st.session_state["eia_key"])
    if not brief_result.get("success"):
        st.error(f"ERROR — The morning brief could not be built: {brief_result.get('error')} "
                 f"It is retried automatically after {FAILURE_RETRY_SECONDS // 60} minutes.")
    else:
        payload = brief_result["payload"]
        sec = payload["sections"]
        freight = sec["freight"]
        subs = freight.get("subsections", {})
        activity_body = ui.brief_figures(subs.get("activity", {}).get("items") or [])
        if subs.get("activity", {}).get("items"):
            activity_body += f'<div class="field-label" style="margin-top:.6rem;">{escape(PORTWATCH_CREDIT)}</div>'
        freight_body = "".join([
            ui.brief_subsection(subs["container_rates"]) if "container_rates" in subs else "",
            ui.brief_subsection(subs["rate_direction"], ui.brief_news(subs["rate_direction"].get("items") or []))
            if "rate_direction" in subs else "",
            ui.brief_subsection(subs["activity"], activity_body) if "activity" in subs else "",
        ])
        st.markdown(ui.brief_header(payload), unsafe_allow_html=True)
        col_figs, col_news = st.columns([7, 5], gap="large")
        with col_figs:
            st.markdown(
                ui.brief_section(sec["prices"], ui.brief_figures(sec["prices"].get("items") or [], prices=True))
                + ui.brief_section(sec["bunker_sales"], ui.brief_figures(sec["bunker_sales"].get("items") or []))
                + ui.brief_section(freight, freight_body),
                unsafe_allow_html=True)
        # A section this page does not know yet (a newer payload) is still shown, never silently dropped.
        known = {"prices", "bunker_sales", "freight", "sale_and_purchase", "events"}
        def _body(section: dict) -> str:
            items = section.get("items") or []
            body = ui.brief_figures(items) if any("display" in i for i in items) else ui.brief_news(items)
            return body + "".join(ui.brief_subsection(sub, _body(sub)) for sub in (section.get("subsections") or {}).values())
        extra = "".join(ui.brief_section(other, _body(other)) for key, other in sec.items() if key not in known)
        problems = _feed_problems(payload, SERVER_EIA_KEY or st.session_state["eia_key"])
        if problems:
            names = {s.get("id"): s.get("name") for s in payload.get("sources") or []}
            listed = "; ".join(f"{names.get(k) or k} ({v})" for k, v in problems.items())
            st.markdown(ui.warn_strip(f"Feeds that failed in this build, so their items are missing below: {listed}. "
                                      f"Retried after {FAILURE_RETRY_SECONDS // 60} minutes."),
                        unsafe_allow_html=True)
        with col_news:
            st.markdown(
                ui.brief_section(sec["sale_and_purchase"], ui.brief_news(sec["sale_and_purchase"].get("items") or []))
                + ui.brief_section(sec["events"], ui.brief_news(sec["events"].get("items") or []))
                + extra
                + ui.brief_sources(payload.get("sources") or []),
                unsafe_allow_html=True)
        built = datetime.fromisoformat(payload["generated_at"]).astimezone(timezone.utc)
        st.markdown(
            f'<div class="data-note">Built {built.day} {built:%B %Y, %H:%M} UTC and shared by every visitor; it is rebuilt '
            f'once it is {LIVE_TTL_SECONDS // 3600} hours old, or {FAILURE_RETRY_SECONDS // 60} minutes after a feed failed. Each value and its date are as '
            "the source published them; every comparison with an earlier reading is calculated by BrokerBrief's code. No language model is used. News is shown as headline, publisher, date and link only. "
            'A section with no verified data says so, with the reason, rather than being filled in. No source, no certainty.</div>',
            unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: DATA INPUT
# ════════════════════════════════════════════════════════════════════════════
elif page == "Data input":
    st.markdown(ui.page_header("Bring your own data", "Data input · upload a CSV for signals, spreads and reports, or load demo data"), unsafe_allow_html=True)

    col_a, col_b = st.columns([5, 2])
    with col_a:
        uploaded = st.file_uploader("Upload market data CSV", type=["csv"],
                                     help="Must include: " + ", ".join(REQUIRED_COLUMNS))
    with col_b:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Load demo data (invented values)", on_click=_load_demo_data, key="demo_page"):
            st.success("LOADED — Demo data (invented values), used by Bunkering Strategy only.")

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
            st.error(f"ERROR — Could not read file: {exc}")

    st.markdown("---")
    st.markdown("**Data Preview**")
    st.dataframe(st.session_state["df"], width="stretch")

    st.markdown("**Validation Report**")
    if st.session_state["df"].empty:
        st.info("No market rows loaded.")
    # A column check on zero rows proves nothing, so the checks run only when there are rows.
    for field in ([] if st.session_state["df"].empty else ["source_name", "source_url", "updated_at", "confidence"]):
        df_display = st.session_state["df"]
        if field in df_display.columns:
            missing_n = df_display[field].isna().sum() + (df_display[field].astype(str).str.strip() == "").sum()
            if missing_n == 0:
                st.markdown(f'<div class="pass-note">{ui.sig("Passed")}<code>{field}</code> — all {len(df_display)} rows populated</div>',
                            unsafe_allow_html=True)
            else:
                st.warning(f"MISSING — `{field}`: {missing_n} rows missing or blank")
        else:
            st.error(f"MISSING — `{field}` column not found")

    # Demo rows are invented: Market Intelligence must never be generated from
    # them, so everything on this page works from real rows only.
    df = st.session_state["df"]   # rebind: an upload on this run replaced the frame read at the top
    mi_df = real_rows(df)
    signals: SignalResult = compute_signals(mi_df)
    has_freight    = (mi_df["signal_type"] == "freight").any()
    has_bunker     = (mi_df["signal_type"] == "bunker").any()
    has_congestion = (mi_df["signal_type"] == "congestion").any()
    used_types     = ["freight", "bunker", "congestion", "news"]
    brief_sources  = set(mi_df.loc[mi_df["signal_type"].isin(used_types), "source_name"].dropna().astype(str))
    unknown_congestion = {}   # port -> reason, shown wherever congestion is shown
    if portwatch_data and portwatch_data.get("success"):
        cong_signals = portwatch_data["congestion_signals"]
        cong_reasons = portwatch_data.get("congestion_reasons", {})
        unknown_congestion = {p: cong_reasons.get(p, "No reason recorded.")
                              for p, v in cong_signals.items() if v == "Unknown"}
        if cong_signals:
            # Majority of the KNOWN signals; "Unknown" if no port has one.
            counts = {"Rising": 0, "Stable": 0, "Easing": 0}
            for v in cong_signals.values():
                if v in counts:
                    counts[v] += 1
            signals.congestion_direction = (max(counts, key=counts.get) if any(counts.values())
                                            else "Unknown")
            has_congestion = True
            # The PDF lists source names; for PortWatch that must be the IMF credit line.
            brief_sources.add(PORTWATCH_CREDIT)
    brief_sources = sorted(brief_sources)
    # The template brief speaks to freight and bunkers, so it needs real rows for both.
    brief_ready = bool(has_freight and has_bunker)
    missing_parts = [name for name, ok in (("freight", has_freight), ("bunker", has_bunker)) if not ok]
    missing_msg = (f"No real {' or '.join(missing_parts)} data loaded, so no brief is generated. "
                   "Demo data is never used here.")

    st.markdown("---")
    st.markdown('<div class="info-card-title">From your data · signals, bunker spreads and reports</div>'
                '<div class="field-label">These use the real rows in your CSV (demo rows are never used here), '
                'plus IMF PortWatch congestion.</div>', unsafe_allow_html=True)
    tab_signals, tab_bunker, tab_reports = st.tabs(["Signal engine", "Bunker spread watch", "Reports"])

    with tab_signals:
        if signals.signal_table:
            table_df = pd.DataFrame(signals.signal_table)
            def _colour_dir(val):
                hexes = ui.DIRECTION_HEX.get(val)
                return f"color:{hexes};font-weight:600" if hexes else ""
            styled = (table_df.style.map(_colour_dir, subset=["Direction"])
                      .format({"Pct Change": "{:+.2f}%", "Confidence": "{:.0%}"})
                      .hide(axis="index"))
            st.dataframe(styled, width="stretch", height=420)
        else:
            st.warning("MISSING — no real freight, bunker or congestion rows loaded. Demo data is never shown here.")
        if portwatch_data and portwatch_data.get("success"):
            st.markdown("**Live PortWatch congestion signals**")
            for port, sig in portwatch_data["congestion_signals"].items():
                if sig == "Unknown":
                    st.markdown(f"- **{port}**: Unknown — {unknown_congestion.get(port, 'No reason recorded.')}")
                else:
                    st.markdown(f"- **{port}**: {sig}")
            if unknown_congestion:
                st.caption("Congestion unknown (not counted in the congestion direction): "
                           + " ".join(f"{p}: {r}" for p, r in unknown_congestion.items()))
            st.caption(PORTWATCH_CREDIT)

    with tab_bunker:
        bunker_data = compute_bunker_spreads(mi_df)
        if not bunker_data["available"]:
            st.warning("MISSING — no real bunker price rows loaded. Demo data is never shown here.")
        else:
            for fuel_type, info in bunker_data["by_fuel"].items():
                spread = info["spread"]
                st.markdown(f"""
                <div class="info-card"><div class="info-card-title">{fuel_type}</div>
                <div class="ws-body">
                Cheapest: <strong class="dir-down">{info["cheapest_port"]} — USD {info["cheapest_price"]:,.0f}/MT</strong> ·
                Most expensive: <strong class="dir-up">{info["most_expensive_port"]} — USD {info["most_expensive_price"]:,.0f}/MT</strong><br>
                Spread: USD {spread:,.0f}/MT → theoretical 1,000 MT stem difference of <strong>USD {spread*1000:,.0f}</strong>
                before operational, credit, supplier, and timing considerations.</div></div>
                """, unsafe_allow_html=True)

    with tab_reports:
        if not brief_ready:
            st.warning(f"MISSING — {missing_msg}")
        else:
            brief = generate_brief(signals)
            r1, r2, r3 = st.tabs(["Email", "PDF", "LinkedIn"])
            with r1:
                email_text = generate_email(signals, brief)
                st.markdown(f'<div class="report-block">{email_text}</div>', unsafe_allow_html=True)
                st.download_button("Download .txt", email_text.encode(), f"brokerbrief_email_{date.today()}.txt", "text/plain")
            with r2:
                if st.button("Generate PDF"):
                    pdf_bytes = generate_pdf_bytes(signals, brief, brief_sources)
                    st.download_button("Download PDF", pdf_bytes, f"brokerbrief_{date.today()}.pdf", "application/pdf")
            with r3:
                linkedin_text = generate_linkedin(signals, brief)
                st.markdown(f'<div class="report-block">{linkedin_text}</div>', unsafe_allow_html=True)
                st.download_button("Download .txt", linkedin_text.encode(), f"brokerbrief_linkedin_{date.today()}.txt", "text/plain")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: LIVE DATA
# ════════════════════════════════════════════════════════════════════════════
elif page == "Live data":
    st.markdown(ui.page_header("Only sources it may share", "Live data · status of every live connection"), unsafe_allow_html=True)

    st.markdown("### EIA Crude Oil API")
    if not (SERVER_EIA_KEY or st.session_state["eia_key"]):
        st.warning("MISSING — No EIA API key is configured. On the deployed app the key is a server-side secret; "
                   "for a local run, set EIA_API_KEY or paste a key under Manage data in the sidebar "
                   "(free registration at https://www.eia.gov/opendata/).")
    elif eia_data:
        spot  = eia_data.get("spot", {})
        fcast = eia_data.get("forecast", {})
        if spot.get("success"):
            st.success(f"CONNECTED — Brent spot: ${spot['current_value']:.2f}/bbl ({spot['latest_date']}) — {spot['pct_change']:+.2f}% — {spot['direction']}")
        else:
            st.error(f"ERROR — Spot fetch failed: {spot.get('error')}")
        if fcast.get("success"):
            st.success(f"CONNECTED — Forecast: ${fcast['nearest_value']:.2f}/bbl for {fcast['nearest_month']}")
            st.dataframe(pd.DataFrame(fcast["forecast_rows"]), width="stretch")
        else:
            st.error(f"ERROR — Forecast fetch failed: {fcast.get('error')}")

    st.markdown("---")
    st.markdown("### IMF PortWatch API")
    if portwatch_data and portwatch_data.get("success"):
        st.success(f"CONNECTED — {len(portwatch_data['ports'])} port activity rows fetched")
        reasons = portwatch_data.get("congestion_reasons", {})
        for port, sig in portwatch_data["congestion_signals"].items():
            text = f"Unknown — {reasons.get(port, 'No reason recorded.')}" if sig == "Unknown" else sig
            st.markdown(f"- **{port}**: {text}")
        with st.expander("Show raw port data"):
            st.dataframe(pd.DataFrame(portwatch_data["ports"]), width="stretch")
        st.caption(PORTWATCH_CREDIT)
    else:
        err = portwatch_data.get("error", "Unknown error") if portwatch_data else "Not fetched"
        st.error(f"ERROR — PortWatch: {err}")

    st.markdown('<div class="data-note">On the deployed app, live data is fetched automatically, shared by all visitors and refetched every 3 hours; a failed fetch is retried after 5 minutes. EIA publishes its daily spot prices in a weekly release, so the latest value can be up to about 9 days old; it is marked stale after 10 days. IMF PortWatch publishes in weekly batches about 8–10 days behind.</div>', unsafe_allow_html=True)
