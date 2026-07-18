"""modules/pdf_export.py — one-page PDF via ReportLab."""

from datetime import date
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from modules.signals import SignalResult

NAVY  = HexColor("#0a1628")
TEAL  = HexColor("#0e7c7b")
AMBER = HexColor("#e8a020")
FOG   = HexColor("#c8d8e8")
CHALK = HexColor("#f0f4f8")
MID   = HexColor("#6b8aab")
DARK  = HexColor("#2c4a62")


def _draw_header(c, width, height, today_str):
    c.setFillColor(NAVY)
    c.rect(0, height - 38*mm, width, 38*mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(14*mm, height - 17*mm, "BrokerBrief")
    c.setFillColor(TEAL)
    c.setFont("Helvetica", 7)
    c.drawString(14*mm, height - 23*mm, "MARITIME MARKET INTELLIGENCE")
    c.setFillColor(FOG)
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 14*mm, height - 16*mm, today_str)
    c.drawRightString(width - 14*mm, height - 22*mm, "DAILY BROKER BRIEF")


def _tone_colour(tone):
    m = {"Bullish": "#1a7a4a", "Cautiously Bullish": "#856404",
         "Bearish": "#c0392b", "Neutral": "#004085", "Soft Demand / Mixed": "#6d4c0f"}
    return HexColor(m.get(tone, "#4a4a4a"))


def _body_text(c, x, y, text, font="Helvetica", size=9, colour=None, max_width=None):
    c.setFillColor(colour or DARK)
    c.setFont(font, size)
    if max_width:
        words, line, line_y = text.split(), "", y
        for word in words:
            test = (line + " " + word).strip()
            if c.stringWidth(test, font, size) <= max_width:
                line = test
            else:
                c.drawString(x, line_y, line)
                line_y -= (size + 3)
                line = word
        if line:
            c.drawString(x, line_y, line)
        return line_y - (size + 3)
    c.drawString(x, y, text)
    return y - (size + 3)


def _stat_box(c, x, y, label, value, box_w=40*mm):
    c.setFillColor(CHALK); c.setStrokeColor(FOG)
    c.rect(x, y - 14*mm, box_w, 14*mm, fill=1, stroke=1)
    c.setFillColor(TEAL); c.setFont("Helvetica-Bold", 6)
    c.drawString(x + 2*mm, y - 5*mm, label.upper())
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 11)
    c.drawString(x + 2*mm, y - 11*mm, value)


def generate_pdf_bytes(signals: SignalResult, brief: dict) -> bytes:
    buf = BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)
    today_str = date.today().strftime("%d %B %Y")
    margin = 14*mm
    cw = width - 2*margin

    _draw_header(c, width, height, today_str)

    y = height - 45*mm
    # Tone pill
    c.setFillColor(_tone_colour(signals.market_tone))
    c.roundRect(margin, y - 7*mm, 65*mm, 7*mm, 3, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 8)
    c.drawString(margin + 3*mm, y - 5*mm, f"MARKET TONE: {signals.market_tone.upper()}")

    y -= 18*mm
    box_w = (cw - 8*mm) / 3
    _stat_box(c, margin,             y, "Freight",         signals.freight_direction,    box_w)
    _stat_box(c, margin+box_w+4*mm,  y, "Bunkers",         signals.bunker_direction,     box_w)
    _stat_box(c, margin+2*(box_w+4*mm), y, "Port Congestion", signals.congestion_direction, box_w)

    y -= 18*mm
    c.setFillColor(TEAL); c.setFont("Helvetica-Bold", 6.5)
    c.drawString(margin, y, "KEY ROUTE TO WATCH")
    y -= 5*mm
    _body_text(c, margin, y, signals.key_route, font="Helvetica-Bold", size=9)
    y -= 9*mm

    c.setStrokeColor(TEAL); c.setLineWidth(1.5)
    c.line(margin, y+4*mm, width-margin, y+4*mm)
    c.setFillColor(TEAL); c.setFont("Helvetica-Bold", 6.5)
    c.drawString(margin, y, "MAIN HEADLINE")
    y -= 5*mm
    y = _body_text(c, margin, y, brief["headline"], font="Helvetica-Bold", size=10, colour=NAVY, max_width=cw)
    y -= 4*mm

    if signals.main_news and signals.main_news != "No news signal available.":
        c.setFillColor(TEAL); c.setFont("Helvetica-Bold", 6.5)
        c.drawString(margin, y, "MARKET NEWS NOTE")
        y -= 5*mm
        y = _body_text(c, margin, y, signals.main_news, size=8, colour=DARK, max_width=cw)
        y -= 4*mm

    c.setFillColor(TEAL); c.setFont("Helvetica-Bold", 6.5)
    c.drawString(margin+4*mm, y, "SUGGESTED TALKING POINT")
    c.setStrokeColor(AMBER); c.setLineWidth(2.5)
    c.line(margin, y, margin+1.5, y-20*mm)
    y -= 5*mm
    y = _body_text(c, margin+4*mm, y, f'"{brief["talking_point"]}"',
                   font="Helvetica-Oblique", size=8.5, colour=DARK, max_width=cw-6*mm)
    y -= 4*mm

    c.setFillColor(TEAL); c.setFont("Helvetica-Bold", 6.5)
    c.drawString(margin, y, "WATCH RISK")
    y -= 5*mm
    y = _body_text(c, margin, y, brief["watch_risk"], size=8, colour=DARK, max_width=cw)
    y -= 5*mm

    c.setStrokeColor(FOG); c.line(margin, y, width-margin, y)
    y -= 5*mm
    y = _body_text(c, margin, y,
        "Freight: Baltic Exchange · Bunkers: Ship & Bunker · Congestion: IMF Portwatch · Crude: EIA",
        size=7, colour=MID, max_width=cw)
    y -= 3*mm
    _body_text(c, margin, y,
        "Data note: This brief supports, not replaces, commercial judgment. Confirm with primary sources.",
        font="Helvetica-Oblique", size=6.5, colour=MID, max_width=cw)

    c.setFillColor(NAVY)
    c.rect(0, 0, width, 10*mm, fill=1, stroke=0)
    c.setFillColor(FOG); c.setFont("Helvetica", 6.5)
    c.drawString(margin, 4*mm, "BrokerBrief · No source, no signal · For informational use only")
    c.drawRightString(width-margin, 4*mm, f"Generated {today_str}")

    c.save()
    return buf.getvalue()
