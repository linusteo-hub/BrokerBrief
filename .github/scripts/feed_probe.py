"""
.github/scripts/feed_probe.py

Checks whether the morning brief's news feeds can be fetched from a GitHub
Actions runner (Splash247 returned HTTP 403 to one fetcher on 12-10-2026).

For each feed it prints only metadata: HTTP status, redirects followed,
final URL, content type, byte count and number of items parsed. It never
prints item text (titles, excerpts, authors). Standard library only; no
secrets. Exits 0 even if a feed fails, so every feed is always reported.
"""

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

# Same User-Agent as modules/morning_brief/guarded_http.py.
USER_AGENT = "BrokerBrief-MorningBrief/0.1 (+https://github.com/linusteo-hub/BrokerBrief)"
FEEDS = {
    "gCaptain": "https://gcaptain.com/feed/",
    "Splash247": "https://splash247.com/feed/",
    "The Maritime Executive": "https://maritime-executive.com/articles.rss",
}
ATOM = "{http://www.w3.org/2005/Atom}"


class CountingRedirects(urllib.request.HTTPRedirectHandler):
    """Follows redirects but counts them: the brief's fetcher does NOT follow
    redirects, so any redirect here means the brief would treat the feed as failed."""

    def __init__(self):
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def count_items(body: bytes) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return "not parseable as XML"
    if root.tag == "rss":
        return str(len(root.findall("./channel/item")))
    if root.tag == f"{ATOM}feed":
        return str(len(root.findall(f"{ATOM}entry")))
    return "unrecognised feed format"


def probe(name: str, url: str) -> None:
    redirects = CountingRedirects()
    opener = urllib.request.build_opener(redirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read()
            status, final_url = response.status, response.geturl()
            content_type = response.headers.get("Content-Type", "")
        items = count_items(body)
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        status, final_url = e.code, e.geturl()
        content_type = e.headers.get("Content-Type", "") if e.headers else ""
        items = "n/a (HTTP error)"
    except Exception as e:  # network errors: report the type only, no response text
        print(f"{name}\n  error: {type(e).__name__}\n")
        return
    print(f"{name}\n"
          f"  status: {status}\n"
          f"  redirects followed: {redirects.count}\n"
          f"  final URL: {final_url}\n"
          f"  content type: {content_type}\n"
          f"  bytes: {len(body)}\n"
          f"  items parsed: {items}\n")


if __name__ == "__main__":
    for feed_name, feed_url in FEEDS.items():
        probe(feed_name, feed_url)
