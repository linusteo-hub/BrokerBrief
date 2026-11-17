"""
modules/morning_brief/site.py

Builds the static GitHub Pages site from the archive:

    index.html                 landing page (the README), with a link to the brief
    brief/index.html           the latest published brief
    brief/archive.html         every run date, with its status
    brief/YYYY-MM-DD.html      each published brief

Static pages do not sleep (unlike the Streamlit app) and cost nothing.

Safety: Markdown is rendered with raw HTML switched off, so any "<script>"
that reached a headline or summary is shown as text, never run.

Staleness: the latest-brief page (brief/index.html) carries its brief date.
A few lines of JavaScript compare it with the reader's clock and show a
banner once the brief is more than STALE_AFTER_DAYS old, counted from 06:00
Singapore time on its date. So a stopped workflow is visible to every reader
even though nothing inside GitHub can run to report it. Past briefs in the
archive carry no banner: they are meant to be old. Without JavaScript, the
"Last updated" line still shows the date.

    python -m modules.morning_brief.site --archive <briefs checkout> --readme README.md --out _site
"""

import argparse
import html
import json
import sys
from datetime import date
from pathlib import Path

from markdown_it import MarkdownIt

from modules.morning_brief.archive import day_dir, read_index

STALE_AFTER_DAYS = 2      # days after 06:00 Singapore time on the brief date
APP_URL = "https://brokerbrief-agyxesfh7xqqqxqqdqnyfx.streamlit.app/"
TRIAL_BANNER = ("Trial — under review. This brief is produced automatically every morning and is being checked "
                "for errors during a trial. Treat it as a student project, not as market data.")

MD = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable("table")

CSS = """
:root{--bg:#ffffff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--accent:#9a6700;--warn-bg:#fff8c5;--warn-fg:#4d2d00}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--accent:#f0a500;--warn-bg:#3b2e00;--warn-fg:#f8e3a1}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}
nav{font-size:14px;margin-bottom:16px}nav a{margin-right:16px}
a{color:var(--accent)}h1{font-size:28px;line-height:1.25}h2{border-bottom:1px solid var(--line);padding-bottom:4px;margin-top:32px}
.banner{background:var(--warn-bg);color:var(--warn-fg);border-radius:6px;padding:10px 14px;margin:12px 0;font-size:14px}
.meta{color:var(--muted);font-size:14px}
blockquote{margin:0;padding:0 14px;border-left:3px solid var(--line);color:var(--muted)}
code,pre{font-size:13px;overflow-x:auto}
table{border-collapse:collapse}td,th{border:1px solid var(--line);padding:4px 8px}
#stale{display:none}
"""

STALE_JS = """
<script>
(function(){var el=document.getElementById('stale');var d=el&&el.getAttribute('data-generated');
if(!d)return;var age=(Date.now()-Date.parse(d+'T06:00:00+08:00'))/86400000;
if(age>%(days)d){el.style.display='block';}})();
</script>
""" % {"days": STALE_AFTER_DAYS}


def page(title: str, body: str, *, depth: int = 0, generated: str = "") -> str:
    """A full HTML page. `depth` is how many folders below the site root the
    page sits, for relative links; `generated` (a brief date) adds the
    staleness banner, and is passed only for the latest-brief page."""
    up = "../" * depth
    stale = ""
    if generated:
        stale = (f'<div id="stale" class="banner" data-generated="{html.escape(generated)}">'
                 "This brief has not been updated for more than two days. The automation may have stopped; "
                 "the figures below may be out of date.</div>")
    return ("<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>"
            f"<nav><a href=\"{up}index.html\">BrokerBrief</a><a href=\"{up}brief/index.html\">Latest brief</a>"
            f"<a href=\"{up}brief/archive.html\">Archive</a><a href=\"{APP_URL}\">Decision tool</a></nav>"
            f"{stale}{body}</main>{STALE_JS if generated else ''}</body></html>\n")


def display_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def brief_page(markdown: str, brief_date: str, *, latest: bool = False) -> str:
    """A brief's page (it sits one folder down, in brief/). Only the latest
    brief carries the staleness banner."""
    label = "Last updated" if latest else "Brief date"
    body = (f'<div class="banner">{html.escape(TRIAL_BANNER)}</div>'
            f'<p class="meta">{label}: {display_date(brief_date)} (Singapore date).</p>'
            + MD.render(markdown))
    return page(f"BrokerBrief Morning Brief, {display_date(brief_date)}", body, depth=1,
                generated=brief_date if latest else "")


def build(archive_root: Path, readme: Path, out: Path) -> dict:
    out = Path(out)
    (out / "brief").mkdir(parents=True, exist_ok=True)
    index = read_index(archive_root)
    published = [e for e in index if e["published"]]

    latest_link = (f'<div class="banner">New: the <a href="brief/index.html">BrokerBrief Morning Brief</a>, '
                   "a daily shipping-markets brief built automatically from public sources (trial).</div>")
    (out / "index.html").write_text(page("BrokerBrief", latest_link + MD.render(Path(readme).read_text(encoding="utf-8"))),
                                    encoding="utf-8")

    for entry in published:
        md = (day_dir(archive_root, entry["date"]) / "brief.md").read_text(encoding="utf-8")
        (out / "brief" / f"{entry['date']}.html").write_text(brief_page(md, entry["date"]), encoding="utf-8")
    if published:
        latest = published[0]
        md = (day_dir(archive_root, latest["date"]) / "brief.md").read_text(encoding="utf-8")
        (out / "brief" / "index.html").write_text(brief_page(md, latest["date"], latest=True), encoding="utf-8")
    else:
        (out / "brief" / "index.html").write_text(
            page("BrokerBrief Morning Brief", "<h1>BrokerBrief Morning Brief</h1><p>No brief has been published yet.</p>",
                 depth=1),
            encoding="utf-8")

    rows = []
    for entry in index:
        empty = sorted(k for k, v in entry.get("sections", {}).items() if v == "missing")
        status = ("published" if entry["published"] else "not published (stopped by the checks)")
        if entry["published"]:
            status += WRITER_STATUS_WORDS.get(entry.get("writer_status"), "")
        link = (f'<a href="{entry["date"]}.html">{display_date(entry["date"])}</a>' if entry["published"]
                else display_date(entry["date"]))
        rows.append(f"<tr><td>{link}</td><td>{html.escape(status)}</td>"
                    f"<td>{html.escape(', '.join(empty) or '–')}</td></tr>")
    table = ("<table><thead><tr><th>Date</th><th>Status</th><th>Empty sections</th></tr></thead><tbody>"
             + "".join(rows) + "</tbody></table>") if rows else "<p>No runs yet.</p>"
    (out / "brief" / "archive.html").write_text(
        page("BrokerBrief Morning Brief archive",
             "<h1>Archive</h1><p class=\"meta\">Every archived run, newest first. A date with no row had no "
             "archived run (the brief page then shows an older date). Each brief's payload and validation "
             "report are in the repository's <code>briefs</code> branch.</p>" + table, depth=1), encoding="utf-8")
    return {"pages": len(published) + 3, "latest": published[0]["date"] if published else None}


WRITER_STATUS_WORDS = {
    "partial": "; some news summaries were held back by the checks",
    "model_unavailable": "; news as headlines only (model unavailable)",
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief.site")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--readme", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(Path(args.archive), Path(args.readme), Path(args.out))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
