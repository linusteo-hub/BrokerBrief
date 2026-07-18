"""modules/brief.py — generates human-readable broker brief text."""

from datetime import date
from modules.signals import SignalResult

_HEADLINES = {
    "Bullish": "Freight indicators firmed while fuel costs eased — voyage economics improving across key bulk and tanker routes.",
    "Cautiously Bullish": "Freight signals point higher, but rising port congestion may delay vessel availability and pressure round-voyage costs.",
    "Mixed": "Freight and bunker signals are pulling in opposite directions — market tone is mixed with no clear dominant trend today.",
    "Bearish": "Freight indicators softened while bunker costs rose and port delays increased, squeezing voyage economics from multiple angles.",
    "Neutral": "Market indicators are broadly flat across freight, bunkers, and congestion — no strong directional signal today.",
    "Soft Demand / Mixed": "Freight rates are easing alongside bunker costs, suggesting softer underlying demand rather than an improving supply-demand balance.",
}

_TALKING_POINTS = {
    "Bullish": "Fuel costs eased while freight indicators strengthened, improving voyage economics and giving owners more room in rate negotiations. Worth monitoring whether this spread holds through the week.",
    "Cautiously Bullish": "Freight signals are constructive, but congestion at key ports may absorb available tonnage. Charterers may face tighter supply windows than the headline rate move suggests.",
    "Mixed": "With freight and bunkers moving against each other, voyage P&L is sensitive to fuel choice and routing assumptions today. Worth stress-testing TCE estimates before fixing.",
    "Bearish": "Costs are rising while rates are falling — a difficult combination for owners. Charterers may find this a good window to cover, but voyage economics require careful scrutiny.",
    "Neutral": "No strong directional signal today. The market appears to be digesting recent moves. Signals suggest monitoring rather than acting on directional positioning.",
    "Soft Demand / Mixed": "Falling freight and bunker prices together may signal softening cargo demand. Worth probing the demand side before drawing conclusions.",
}

_WATCH_RISKS = {
    "Bullish": "Monitor for reversal if Chinese demand signals weaken or Red Sea diversion costs re-escalate.",
    "Cautiously Bullish": "Watch port congestion closely — persistent delays could offset rate gains and reduce effective TCE.",
    "Mixed": "Key risk is directional — further freight weakness or a sharp bunker move could shift the tone quickly.",
    "Bearish": "Owners should watch for any demand-side catalyst that could halt the current rate slide.",
    "Neutral": "Watch for a macro catalyst — inventory data, Chinese import volumes, or OPEC supply decisions.",
    "Soft Demand / Mixed": "Demand-side confirmation needed. Watch steel output data and crude import figures from China.",
}

_RISK_NOTE = (
    "Signals are derived from source-backed indicators and reflect directional trends only. "
    "Confirm all data with primary sources before use in commercial decisions."
)


def generate_brief(signals: SignalResult) -> dict:
    tone = signals.market_tone
    return {
        "headline":      _HEADLINES.get(tone, _HEADLINES["Mixed"]),
        "talking_point": _TALKING_POINTS.get(tone, _TALKING_POINTS["Mixed"]),
        "watch_risk":    _WATCH_RISKS.get(tone, _WATCH_RISKS["Mixed"]),
        "risk_note":     _RISK_NOTE,
        "date_str":      date.today().strftime("%d %B %Y"),
        "news":          signals.main_news,
    }
