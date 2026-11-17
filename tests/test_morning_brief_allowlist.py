"""
tests/test_morning_brief_allowlist.py

The allowlist gate: only allowlisted sources pass, denylisted ones are
refused with their reason, and numbers from non-redistributable sources
are refused. Banned names live in fixtures/banned_sources.json so this file
stays clean for the licensed-source scan.
"""

import json
import re
from pathlib import Path

import pytest

from modules.morning_brief.allowlist import (
    ALLOWLIST,
    DENYLIST,
    SourceNotAllowed,
    mentions_banned_source,
    require_allowed,
)

FIXTURES = Path(__file__).parent / "fixtures"
BANNED = json.loads((FIXTURES / "banned_sources.json").read_text())


def test_allowlisted_data_source_passes_with_numbers():
    assert require_allowed("eia_spot", numeric=True).redistributable


def test_unknown_source_is_refused():
    with pytest.raises(SourceNotAllowed, match="not on the morning-brief allowlist"):
        require_allowed("some_random_blog")


@pytest.mark.parametrize("source_id", BANNED["denylisted_ids"])
def test_denylisted_sources_are_refused(source_id):
    with pytest.raises(SourceNotAllowed, match="denylisted"):
        require_allowed(source_id)


def test_news_source_allowed_for_headlines_but_not_numbers():
    assert require_allowed("gcaptain").kind == "news"
    with pytest.raises(SourceNotAllowed, match="not redistributable"):
        require_allowed("gcaptain", numeric=True)


def test_allow_and_deny_lists_do_not_overlap():
    assert not set(ALLOWLIST) & set(DENYLIST)


def test_every_allowlisted_source_records_its_terms():
    for source in ALLOWLIST.values():
        assert source.terms_url.startswith("https://"), source.id
        assert source.licence and source.credit, source.id
        assert source.kind in {"data", "news"}, source.id
        if source.kind == "data":
            assert source.max_age is not None, source.id


@pytest.mark.parametrize("text", BANNED["texts_that_must_match"])
def test_banned_names_are_detected(text):
    assert mentions_banned_source(text)


@pytest.mark.parametrize("text", BANNED["texts_that_must_not_match"])
def test_ordinary_words_are_not_flagged(text):
    assert mentions_banned_source(text) is None


def test_morning_brief_never_imports_decision_engine():
    package = Path(__file__).parent.parent / "modules" / "morning_brief"
    pattern = re.compile(r"^\s*(from|import)\s+modules\.decision|from\s+modules\s+import\s+decision", re.M)
    offenders = [p.name for p in package.glob("*.py") if pattern.search(p.read_text())]
    assert offenders == []


def test_brief_uses_the_apps_eia_staleness_limit():
    from modules.provenance import EIA_SPOT_MAX_AGE
    assert require_allowed("eia_spot").max_age is EIA_SPOT_MAX_AGE
