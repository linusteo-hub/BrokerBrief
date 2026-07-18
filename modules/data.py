"""
modules/data.py
Handles sample data generation and CSV loading.
Core rule: every row must carry source_name, source_url, updated_at, confidence.
"""

import pandas as pd
from datetime import date, timedelta

REQUIRED_COLUMNS = [
    "date", "signal_type", "market_segment", "route_or_port",
    "current_value", "previous_value", "unit", "source_name",
    "source_url", "updated_at", "confidence", "notes",
]

def _build_sample_data() -> pd.DataFrame:
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    rows = [
        # FREIGHT
        {"date": today, "signal_type": "freight", "market_segment": "Capesize",
         "route_or_port": "C5 – W Australia / China (iron ore)",
         "current_value": 9.42, "previous_value": 9.10, "unit": "USD/MT",
         "source_name": "Baltic Exchange", "source_url": "https://www.balticexchange.com",
         "updated_at": today, "confidence": 0.92,
         "notes": "Iron ore export volumes from Port Hedland remain elevated."},
        {"date": today, "signal_type": "freight", "market_segment": "Panamax",
         "route_or_port": "P2A – Skaw/Gibraltar / Far East",
         "current_value": 13850, "previous_value": 13200, "unit": "USD/day",
         "source_name": "Baltic Exchange", "source_url": "https://www.balticexchange.com",
         "updated_at": today, "confidence": 0.90,
         "notes": "Grain fixture activity firming from US Gulf."},
        {"date": today, "signal_type": "freight", "market_segment": "VLCC",
         "route_or_port": "TD3C – Middle East Gulf / China",
         "current_value": 42500, "previous_value": 44100, "unit": "USD/day",
         "source_name": "Baltic Exchange", "source_url": "https://www.balticexchange.com",
         "updated_at": today, "confidence": 0.88,
         "notes": "VLCC softness persists amid weak Chinese crude demand signal."},
        # BUNKER
        {"date": today, "signal_type": "bunker", "market_segment": "VLSFO",
         "route_or_port": "Singapore", "current_value": 615, "previous_value": 632,
         "unit": "USD/MT", "source_name": "Ship & Bunker",
         "source_url": "https://shipandbunker.com", "updated_at": today,
         "confidence": 0.95, "notes": "Singapore VLSFO easing on soft crude."},
        {"date": today, "signal_type": "bunker", "market_segment": "VLSFO",
         "route_or_port": "Rotterdam", "current_value": 647, "previous_value": 658,
         "unit": "USD/MT", "source_name": "Ship & Bunker",
         "source_url": "https://shipandbunker.com", "updated_at": today,
         "confidence": 0.93, "notes": "European VLSFO tracking Brent softness."},
        {"date": today, "signal_type": "bunker", "market_segment": "VLSFO",
         "route_or_port": "Fujairah", "current_value": 598, "previous_value": 612,
         "unit": "USD/MT", "source_name": "Ship & Bunker",
         "source_url": "https://shipandbunker.com", "updated_at": today,
         "confidence": 0.92, "notes": "Fujairah VLSFO softening with regional supply length."},
        {"date": today, "signal_type": "bunker", "market_segment": "MGO",
         "route_or_port": "Singapore", "current_value": 855, "previous_value": 870,
         "unit": "USD/MT", "source_name": "Ship & Bunker",
         "source_url": "https://shipandbunker.com", "updated_at": today,
         "confidence": 0.94, "notes": "MGO demand firm in ECA-regulated coastal trades."},
        {"date": today, "signal_type": "bunker", "market_segment": "MGO",
         "route_or_port": "Fujairah", "current_value": 872, "previous_value": 868,
         "unit": "USD/MT", "source_name": "Ship & Bunker",
         "source_url": "https://shipandbunker.com", "updated_at": today,
         "confidence": 0.88, "notes": "Fujairah MGO steady."},
        {"date": today, "signal_type": "bunker", "market_segment": "IFO380",
         "route_or_port": "Singapore", "current_value": 482, "previous_value": 495,
         "unit": "USD/MT", "source_name": "Ship & Bunker",
         "source_url": "https://shipandbunker.com", "updated_at": today,
         "confidence": 0.90, "notes": "IFO380 demand limited outside non-scrubber fleet."},
        {"date": today, "signal_type": "bunker", "market_segment": "IFO380",
         "route_or_port": "Houston", "current_value": 498, "previous_value": 492,
         "unit": "USD/MT", "source_name": "Ship & Bunker",
         "source_url": "https://shipandbunker.com", "updated_at": today,
         "confidence": 0.87, "notes": "Houston IFO380 slight uptick."},
        # CONGESTION
        {"date": today, "signal_type": "congestion", "market_segment": "Bulk",
         "route_or_port": "Port Hedland", "current_value": 18, "previous_value": 17,
         "unit": "vessels at anchor", "source_name": "IMF Portwatch",
         "source_url": "https://portwatch.imf.org", "updated_at": today,
         "confidence": 0.80, "notes": "Iron ore export queue manageable."},
        {"date": today, "signal_type": "congestion", "market_segment": "Container",
         "route_or_port": "Singapore", "current_value": 52, "previous_value": 49,
         "unit": "vessels at anchor", "source_name": "IMF Portwatch",
         "source_url": "https://portwatch.imf.org", "updated_at": today,
         "confidence": 0.85, "notes": "Anchorage demand rising ahead of Chinese export peak."},
        # NEWS
        {"date": today, "signal_type": "news", "market_segment": "Macro",
         "route_or_port": "Global", "current_value": None, "previous_value": None,
         "unit": "n/a", "source_name": "Lloyd's List",
         "source_url": "https://lloydslist.com", "updated_at": yesterday,
         "confidence": 0.82,
         "notes": "Red Sea diversion routes adding 8–12 days on Asia–Europe legs. War risk premiums steady."},
        {"date": today, "signal_type": "news", "market_segment": "Regulatory",
         "route_or_port": "Global", "current_value": None, "previous_value": None,
         "unit": "n/a", "source_name": "IMO",
         "source_url": "https://www.imo.org", "updated_at": yesterday,
         "confidence": 0.88,
         "notes": "CII annual ratings release approaching. Owners with D/E-rated vessels reviewing operational speed."},
    ]
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def load_data(source: str = "sample", file_obj=None) -> pd.DataFrame:
    if source == "sample":
        return _build_sample_data()
    if source == "csv" and file_obj is not None:
        df = pd.read_csv(file_obj)
        df["current_value"] = pd.to_numeric(df["current_value"], errors="coerce")
        df["previous_value"] = pd.to_numeric(df["previous_value"], errors="coerce")
        df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
        return df
    raise ValueError(f"Unknown data source: {source}")
