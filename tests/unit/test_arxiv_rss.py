"""Regression tests for the 2026-10-20 empty arXiv RSS channel."""

from __future__ import annotations

from unittest.mock import Mock

import feedparser
import pytest

from paperradar.collector import _collect_rss
from paperradar.config_loader import load_category_config
from paperradar.models import Source

# Body returned by http://export.arxiv.org/rss/cs.AI on 2026-10-20 (HTTP 200,
# content-length 892). feedparser yields zero entries from this channel.
EMPTY_EXPORT_CHANNEL = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
  <channel>
    <title>cs.AI updates on arXiv.org</title>
    <link>http://rss.arxiv.org/rss/cs.AI</link>
    <description>cs.AI updates on the arXiv.org e-print archive.</description>
    <atom:link href="http://rss.arxiv.org/rss/cs.AI" rel="self" type="application/rss+xml"/>
    <pubDate>Tue, 20 Oct 2026 00:00:00 -0400</pubDate>
  </channel>
</rss>
"""

CANONICAL_ITEM = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version="2.0">
  <channel>
    <title>cs.AI updates on arXiv.org</title>
    <link>https://rss.arxiv.org/rss/cs.AI</link>
    <item>
      <title>GardenBench: A lightweight, daily evaluation of LLM capabilities</title>
      <link>https://arxiv.org/abs/2610.23866</link>
      <description>arXiv:2610.23866v1 Announce Type: new Abstract: GardenBench fixture.</description>
      <pubDate>Tue, 20 Oct 2026 00:00:00 -0400</pubDate>
    </item>
  </channel>
</rss>
"""


def _response(content: bytes) -> Mock:
    response = Mock()
    response.content = content
    response.raise_for_status = Mock()
    return response


def test_empty_export_channel_has_zero_entries() -> None:
    feed = feedparser.parse(EMPTY_EXPORT_CHANNEL)
    assert feed.entries == []
    assert feed.feed.link == "http://rss.arxiv.org/rss/cs.AI"


def test_legacy_export_url_collects_canonical_feed_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """The zero-item export channel must not be stored as a successful empty fetch."""
    sleeps: list[float] = []

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("paperradar.collector.time.sleep", _sleep)

    calls: list[str] = []

    def _get(url: str, **_kwargs: object) -> Mock:
        calls.append(url)
        if url == "https://rss.arxiv.org/rss/cs.AI":
            return _response(CANONICAL_ITEM)
        return _response(EMPTY_EXPORT_CHANNEL)

    session = Mock()
    session.get.side_effect = _get
    source = Source(
        name="arXiv CS.AI",
        type="rss",
        url="http://export.arxiv.org/rss/cs.AI",
    )
    articles = _collect_rss(source, category="research", limit=30, timeout=15, session=session)

    assert calls == ["https://rss.arxiv.org/rss/cs.AI"]
    assert sleeps == []
    assert len(articles) == 1
    assert articles[0].title.startswith("GardenBench")
    assert articles[0].link == "https://arxiv.org/abs/2610.23866"
    assert articles[0].source == "arXiv CS.AI"


def test_empty_channel_follows_declared_canonical_url_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("paperradar.collector.time.sleep", _sleep)

    calls: list[str] = []

    def _get(url: str, **_kwargs: object) -> Mock:
        calls.append(url)
        if len(calls) == 1:
            return _response(EMPTY_EXPORT_CHANNEL)
        return _response(CANONICAL_ITEM)

    session = Mock()
    session.get.side_effect = _get
    source = Source(
        name="arXiv CS.AI",
        type="rss",
        url="https://mirror.example/rss/cs.AI",
    )
    articles = _collect_rss(source, category="research", limit=30, timeout=15, session=session)

    assert calls == [
        "https://mirror.example/rss/cs.AI",
        "https://rss.arxiv.org/rss/cs.AI",
    ]
    assert sleeps == [3.0]
    assert len(articles) == 1
    assert articles[0].link == "https://arxiv.org/abs/2610.23866"


def test_empty_channel_does_not_follow_off_arxiv_link(monkeypatch: pytest.MonkeyPatch) -> None:
    def _sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("paperradar.collector.time.sleep", _sleep)
    offsite = EMPTY_EXPORT_CHANNEL.replace(
        b"http://rss.arxiv.org/rss/cs.AI",
        b"https://evil.example/rss/cs.AI",
    )
    calls: list[str] = []

    def _get(url: str, **_kwargs: object) -> Mock:
        calls.append(url)
        return _response(offsite)

    session = Mock()
    session.get.side_effect = _get
    source = Source(name="arXiv CS.AI", type="rss", url="https://mirror.example/rss/cs.AI")
    articles = _collect_rss(source, category="research", limit=30, timeout=15, session=session)

    assert articles == []
    assert calls == ["https://mirror.example/rss/cs.AI"]


def test_weekend_empty_canonical_feed_is_not_refetched(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("paperradar.collector.time.sleep", _sleep)
    calls: list[str] = []

    def _get(url: str, **_kwargs: object) -> Mock:
        calls.append(url)
        return _response(EMPTY_EXPORT_CHANNEL)

    session = Mock()
    session.get.side_effect = _get
    source = Source(
        name="arXiv CS.AI",
        type="rss",
        url="https://rss.arxiv.org/rss/cs.AI",
    )
    articles = _collect_rss(source, category="research", limit=30, timeout=15, session=session)

    assert articles == []
    assert calls == ["https://rss.arxiv.org/rss/cs.AI"]
    assert sleeps == []


def test_research_arxiv_rss_sources_use_canonical_host() -> None:
    category = load_category_config("research")
    expected = {
        "arXiv CS.AI": "https://rss.arxiv.org/rss/cs.AI",
        "arXiv CS.CL": "https://rss.arxiv.org/rss/cs.CL",
        "arXiv CS.LG": "https://rss.arxiv.org/rss/cs.LG",
        "arXiv CS.CV": "https://rss.arxiv.org/rss/cs.CV",
        "arXiv CS.NE": "https://rss.arxiv.org/rss/cs.NE",
        "arXiv Stat.ML": "https://rss.arxiv.org/rss/stat.ML",
    }
    found = {source.name: source.url for source in category.sources if source.name in expected}
    assert found == expected
    for source in category.sources:
        if source.name in expected:
            assert source.enabled is True
            assert "export.arxiv.org" not in source.url
