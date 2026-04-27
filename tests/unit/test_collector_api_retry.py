from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import Mock, patch

import requests

from paperradar import collector as collector_module
from paperradar.models import Article, Paper, Source


ARXIV_XML = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<feed xmlns=\"http://www.w3.org/2005/Atom\">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Retry Test Paper</title>
    <summary>Abstract body</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Test Author</name></author>
  </entry>
</feed>
"""


def _success_response(content: bytes) -> Mock:
    response = Mock()
    response.content = content
    response.raise_for_status = Mock()
    return response


def _http_error_response() -> Mock:
    response = Mock()
    response.raise_for_status = Mock(
        side_effect=requests.exceptions.HTTPError("503 Service Unavailable")
    )
    return response


def _collect_arxiv_callable() -> Callable[..., list[Paper]]:
    target = getattr(collector_module, "_collect_arxiv", None)
    if target is None:
        raise AssertionError("_collect_arxiv is unavailable")
    return cast(Callable[..., list[Paper]], target)


def _collect_openalex_callable() -> Callable[..., list[Article]]:
    target = getattr(collector_module, "_collect_openalex", None)
    if target is None:
        raise AssertionError("_collect_openalex is unavailable")
    return cast(Callable[..., list[Article]], target)


def test_collect_arxiv_retries_on_transient_http_errors() -> None:
    collect_arxiv = _collect_arxiv_callable()
    source = Source(name="arXiv", type="arxiv", url="http://example.com?q=cat:cs.AI")
    session = Mock(spec=requests.Session)
    session.get.side_effect = [
        _http_error_response(),
        _http_error_response(),
        _success_response(ARXIV_XML),
    ]

    with patch("tenacity.nap.sleep", return_value=None):
        papers = collect_arxiv(
            source,
            category="research",
            limit=10,
            timeout=15,
            session=session,
        )

    assert len(papers) == 1
    assert papers[0].title == "Retry Test Paper"
    assert session.get.call_count == 3


def test_collect_arxiv_uses_session_not_requests_get() -> None:
    collect_arxiv = _collect_arxiv_callable()
    source = Source(name="arXiv", type="arxiv", url="http://example.com?q=cat:cs.AI")
    session = Mock(spec=requests.Session)
    session.get.return_value = _success_response(ARXIV_XML)

    with patch("paperradar.collector.requests.get") as mocked_requests_get:
        papers = collect_arxiv(
            source,
            category="research",
            limit=10,
            timeout=15,
            session=session,
        )

    assert len(papers) == 1
    assert papers[0].arxiv_id == "2401.00001v1"
    mocked_requests_get.assert_not_called()


def test_collect_openalex_accepts_current_api_schema_for_citation_snapshot() -> None:
    collect_openalex = _collect_openalex_callable()
    source = Source(
        name="OpenAlex AI Citation Feed",
        type="openalex",
        url="https://api.openalex.org/works",
        config={"event_model": "citation_snapshot"},
    )
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {
        "results": [
            {
                "id": "https://openalex.org/W4385245566",
                "doi": "https://doi.org/10.1145/example",
                "display_name": "Current OpenAlex Schema Paper",
                "publication_year": 2023,
                "publication_date": "2023-05-01",
                "cited_by_count": 1234,
            }
        ]
    }
    session = Mock(spec=requests.Session)
    session.get.return_value = response

    articles = collect_openalex(
        source,
        category="research",
        limit=10,
        timeout=15,
        session=session,
    )

    assert len(articles) == 1
    assert articles[0].title == "Current OpenAlex Schema Paper"
    assert articles[0].published is None
    assert articles[0].link == "https://doi.org/10.1145/example"
    assert "Citation count: 1234" in articles[0].summary
