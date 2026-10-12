"""modules/report.py — email and LinkedIn copy generator."""

from datetime import date
from modules.signals import SignalResult


def generate_email(signals: SignalResult, brief: dict) -> str:
    today_str = date.today().strftime("%d %B %Y")
    lines = [
        f"Subject: Daily Broker Brief — {today_str}", "",
        "Hi team,", "",
        f"Today's market tone is {signals.market_tone}.", "",
        f"Freight direction:    {signals.freight_direction}",
        f"Bunker direction:     {signals.bunker_direction}",
        f"Port congestion:      {signals.congestion_direction}",
        f"Key route to watch:   {signals.key_route}", "",
        "──────────────────────────────────────────────",
        "MAIN HEADLINE",
        "──────────────────────────────────────────────",
        brief["headline"], "",
        "──────────────────────────────────────────────",
        "MARKET NEWS NOTE",
        "──────────────────────────────────────────────",
        signals.main_news, "",
        "──────────────────────────────────────────────",
        "SUGGESTED TALKING POINT",
        "──────────────────────────────────────────────",
        f'"{brief["talking_point"]}"', "",
        "──────────────────────────────────────────────",
        "WATCH RISK",
        "──────────────────────────────────────────────",
        brief["watch_risk"], "",
        "──────────────────────────────────────────────",
        "DATA NOTE",
        "──────────────────────────────────────────────",
        "This brief is generated from selected source-backed market indicators "
        "and should support, not replace, commercial judgment.", "",
        "Best,", "BrokerBrief", f"Generated: {today_str}",
    ]
    return "\n".join(lines)


def generate_linkedin(signals: SignalResult, brief: dict) -> str:
    today_str = date.today().strftime("%d %B %Y")
    freight_emoji = {"Up": "📈", "Down": "📉", "Flat": "➡️"}.get(signals.freight_direction, "➡️")
    bunker_emoji  = {"Up": "🔺", "Down": "🔻", "Flat": "🔹"}.get(signals.bunker_direction, "🔹")
    cong_emoji    = {"Rising": "⚠️", "Easing": "✅", "Stable": "🔷", "Unknown": "❔"}.get(signals.congestion_direction, "❔")
    lines = [
        f"Maritime market signals — {today_str}", "",
        f"Market tone: {signals.market_tone}", "",
        f"{freight_emoji} Freight: {signals.freight_direction}",
        f"{bunker_emoji} Bunkers: {signals.bunker_direction}",
        f"{cong_emoji} Port congestion: {signals.congestion_direction}", "",
        brief["headline"], "",
        "Worth watching:", brief["watch_risk"], "",
        "These are directional signals drawn from source-backed data — not predictions. "
        "Useful as a starting point for deeper research or client conversations.", "",
        "#Maritime #Shipping #Bunkers #FreightMarket #BrokerBrief",
    ]
    return "\n".join(lines)
