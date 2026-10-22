from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from paperradar.collector import _CooldownProbeSession, collect_sources
from paperradar.models import Source


def _response(status: int = 200, body: bytes | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://example.org/feed"
    response._content = (
        body
        if body is not None
        else (
            b'<rss version="2.0"><channel><title>Feed</title><item>'
            b"<title>Research</title><link>https://example.org/paper</link>"
            b"<description>Abstract</description></item></channel></rss>"
        )
    )
    return response


def _store() -> Mock:
    store = Mock()
    store.is_disabled.return_value = True
    store.claim_retry.return_value = True
    return store


def _source(**kwargs: object) -> Source:
    return Source(
        name="Hugging Face Blog",
        type="rss",
        url="https://example.org/feed",
        config={"retry_after_cooldown": True},
        **kwargs,
    )


def _manager() -> Mock:
    manager = Mock()
    manager.get_breaker.return_value.call.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
    return manager


def test_probe_recovers_only_with_valid_items() -> None:
    store = _store()
    with (
        patch("paperradar.collector.CrawlHealthStore", return_value=store),
        patch("paperradar.collector.get_circuit_breaker_manager", return_value=_manager()),
        patch("requests.Session.request", return_value=_response()) as request,
    ):
        items, errors = collect_sources([_source()], category="research", max_workers=1)
    assert len(items) == 1
    assert errors == []
    request.assert_called_once()
    assert request.call_args.kwargs["allow_redirects"] is False
    assert request.call_args.kwargs["verify"] is True
    store.finish_retry.assert_called_once_with("Hugging Face Blog")


@pytest.mark.parametrize(
    "status,body",
    [
        (200, b"<rss><channel><title>Empty</title></channel></rss>"),
        (200, b"<html><title>Just a moment...</title></html>"),
        (302, b""),
        (403, b"Forbidden"),
        (429, b"Limited"),
        (503, b"Unavailable"),
    ],
)
def test_failed_or_empty_probe_never_restores_or_retries(status: int, body: bytes) -> None:
    store = _store()
    with (
        patch("paperradar.collector.CrawlHealthStore", return_value=store),
        patch("paperradar.collector.get_circuit_breaker_manager", return_value=_manager()),
        patch("requests.Session.request", return_value=_response(status, body)) as request,
    ):
        items, errors = collect_sources([_source()], category="research", max_workers=1)
    assert not items
    assert errors
    request.assert_called_once()
    store.finish_retry.assert_not_called()


@pytest.mark.parametrize("retry_after", ["604800", "Wed, 30 Dec 2026 00:00:00 GMT"])
def test_retry_after_is_persisted(retry_after: str) -> None:
    store = _store()
    response = _response(429)
    response.headers["Retry-After"] = retry_after
    with (
        patch("paperradar.collector.CrawlHealthStore", return_value=store),
        patch("paperradar.collector.get_circuit_breaker_manager", return_value=_manager()),
        patch("requests.Session.request", return_value=response),
    ):
        collect_sources([_source()], category="research", max_workers=1)
    store.postpone_retry.assert_called_once()


@pytest.mark.parametrize("mode", ["not_due", "no_opt_in", "old_core", "disabled_config"])
def test_disabled_sources_fail_closed_without_eligible_claim(mode: str) -> None:
    store = _store()
    source = _source()
    if mode == "not_due":
        store.claim_retry.return_value = False
    elif mode == "no_opt_in":
        source.config.clear()
    elif mode == "old_core":
        del store.claim_retry
    else:
        source.enabled = False
    with (
        patch("paperradar.collector.CrawlHealthStore", return_value=store),
        patch("paperradar.collector._collect_single") as collect,
    ):
        items, _ = collect_sources([source], category="research", max_workers=1)
    assert items == []
    collect.assert_not_called()


def test_probe_session_has_no_adapter_retries() -> None:
    with _CooldownProbeSession() as session:
        assert session.get_adapter("https://example.org").max_retries.total == 0


def test_openalex_probe_limits_parsed_items_to_five() -> None:
    import json

    store = _store()
    response = _response(
        body=json.dumps(
            {
                "results": [
                    {"id": f"https://openalex.org/W{n}", "display_name": f"Work {n}"}
                    for n in range(10)
                ]
            }
        ).encode()
    )
    source = Source(
        name="OpenAlex AI Citation Feed",
        type="openalex",
        url="https://example.org/api",
        config={"retry_after_cooldown": True, "event_model": "citation_snapshot"},
    )
    with (
        patch("paperradar.collector.CrawlHealthStore", return_value=store),
        patch("paperradar.collector.get_circuit_breaker_manager", return_value=_manager()),
        patch("requests.Session.request", return_value=response) as request,
    ):
        items, errors = collect_sources([source], category="research", max_workers=1)
    assert len(items) == 5
    assert not errors
    request.assert_called_once()
    store.finish_retry.assert_called_once_with(source.name)
