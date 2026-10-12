"""
modules/morning_brief/guarded_http.py

The only way the morning brief makes HTTP requests. The URL is checked
against the allowlist *before* anything is sent; a URL outside it raises
SourceNotAllowed, which no fetcher catches, so the run fails loudly.

Redirects are not followed: a feed that redirects elsewhere would otherwise
sidestep the check. A redirect therefore shows up as a failed feed, which is
the safe outcome.
"""

import requests

from modules.morning_brief.allowlist import require_allowed_url

USER_AGENT = "BrokerBrief-MorningBrief/0.1 (+https://github.com/linusteo-hub/BrokerBrief)"


def guarded_get(url: str, params=None, timeout: float = 15, **kwargs) -> requests.Response:
    require_allowed_url(url)
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    response = requests.get(url, params=params, timeout=timeout, headers=headers,
                            allow_redirects=False, **kwargs)
    if response.is_redirect:
        raise requests.HTTPError(f"{url} redirected to {response.headers.get('Location')!r}; not followed")
    return response
