from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
import yaml

from paperradar.collector import _cooldown_policy, _robots_allows, collect_sources
from paperradar.models import Source

FEED_URL = "https://news.example.org/feed"
ROBOTS_URL = "https://news.example.org/robots.txt"
WEEK = 604800.0
VALID_FEED = (
    b'<rss version="2.0"><channel><title>Feed</title><item><title>Post</title>'
    b"<link>https://news.example.org/p</link><description>Body</description></item>"
    b"</channel></rss>"
)


def _response(url: str, status: int = 200, body: bytes = b"", ctype: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = body
    if ctype:
        response.headers["Content-Type"] = ctype
    return response


def _source(**config: object) -> Source:
    base: dict[str, object] = {
        "retry_after_cooldown": True,
        "retry_after_cooldown_statuses": [403],
        "retry_after_cooldown_seconds": WEEK,
    }
    base.update(config)
    return Source(name="Import AI", type="rss", url=FEED_URL, config=base)


def _store(claim: bool = True) -> Mock:
    store = Mock()
    store.is_disabled.return_value = True
    store.claim_retry.return_value = claim
    return store


def _manager() -> Mock:
    manager = Mock()
    manager.get_breaker.return_value.call.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
    return manager


def _router(robots: requests.Response, feed: requests.Response):
    calls: list[str] = []

    def request(self, method, url, **kwargs):  # noqa: ANN001
        calls.append(url)
        return robots if url == ROBOTS_URL else feed

    return request, calls


def _run(source: Source, store: Mock, robots, feed):
    request, calls = _router(robots, feed)
    with (
        patch("paperradar.collector.CrawlHealthStore", return_value=store),
        patch("paperradar.collector.get_circuit_breaker_manager", return_value=_manager()),
        patch("requests.Session.request", request),
    ):
        items, errors = collect_sources([source], category="research", max_workers=1)
    return items, errors, calls


ALLOW = _response(ROBOTS_URL, 200, b"User-agent: *\nDisallow: /action/\n", "text/plain; charset=utf-8")


def test_403_probe_recovers_after_robots_allows_and_valid_feed() -> None:
    store = _store()
    items, errors, calls = _run(
        _source(), store, ALLOW, _response(FEED_URL, 200, VALID_FEED, "application/xml")
    )
    assert len(items) == 1 and errors == []
    assert calls == [ROBOTS_URL, FEED_URL]
    store.claim_retry.assert_called_once_with(
        "Import AI", retry_statuses=[403], cooldown_seconds=WEEK
    )
    store.finish_retry.assert_called_once_with("Import AI")


def test_cooldown_below_one_week_is_raised_for_403() -> None:
    policy = _cooldown_policy(_source(retry_after_cooldown_seconds=86400))
    assert policy == (frozenset({403}), WEEK)
    assert _cooldown_policy(_source(retry_after_cooldown_seconds=None)) == (frozenset({403}), WEEK)


@pytest.mark.parametrize(
    "robots",
    [
        _response(ROBOTS_URL, 200, b"User-agent: *\nDisallow: /\n", "text/plain"),
        _response(ROBOTS_URL, 200, b"User-agent: PaperRadar\nDisallow: /feed\n", "text/plain"),
        _response(ROBOTS_URL, 202, b'<html><meta http-equiv="refresh" content="0;/sgcaptcha/">', "text/html"),
        _response(ROBOTS_URL, 200, b"<html>challenge</html>", "text/html"),
        _response(ROBOTS_URL, 503, b"down", "text/plain"),
        _response(ROBOTS_URL, 301, b"", ""),
    ],
)
def test_robots_disallow_or_unverifiable_never_requests_feed(robots: requests.Response) -> None:
    store = _store()
    items, errors, calls = _run(
        _source(), store, robots, _response(FEED_URL, 200, VALID_FEED, "application/xml")
    )
    assert items == []
    assert errors and "robots.txt" in errors[0]
    assert calls == [ROBOTS_URL]
    store.finish_retry.assert_not_called()


def test_missing_robots_file_allows_probe() -> None:
    assert _robots_allows_with(_response(ROBOTS_URL, 404, b"nope", "text/html")) is True


def test_robots_network_error_blocks_probe() -> None:
    with patch("requests.get", side_effect=requests.ConnectionError("down")):
        assert _robots_allows(FEED_URL) is False


def _robots_allows_with(response: requests.Response) -> bool:
    with patch("requests.get", return_value=response):
        return _robots_allows(FEED_URL)


@pytest.mark.parametrize("status", [401, 404, 410, 451, 500, "x"])
def test_only_403_can_be_opted_in(status: object) -> None:
    source = _source(retry_after_cooldown_statuses=[status])
    assert _cooldown_policy(source) is None
    store = _store()
    items, errors, calls = _run(source, store, ALLOW, _response(FEED_URL, 200, VALID_FEED))
    assert items == [] and calls == []
    store.claim_retry.assert_not_called()


def test_old_core_without_status_opt_in_stays_closed() -> None:
    store = _store()

    def old_claim_retry(source_name, cooldown_seconds=86400):  # noqa: ANN001, ANN202
        raise AssertionError("must not be called on an old core")

    store.claim_retry = old_claim_retry
    items, errors, calls = _run(_source(), store, ALLOW, _response(FEED_URL, 200, VALID_FEED))
    assert items == [] and calls == []
    assert "disabled" in errors[0]


def test_not_due_claim_makes_no_request() -> None:
    store = _store(claim=False)
    items, _, calls = _run(_source(), store, ALLOW, _response(FEED_URL, 200, VALID_FEED))
    assert items == [] and calls == []


def test_source_without_403_opt_in_keeps_default_claim() -> None:
    source = Source(
        name="Hugging Face Blog",
        type="rss",
        url=FEED_URL,
        config={"retry_after_cooldown": True},
    )
    store = _store()
    _run(source, store, ALLOW, _response(FEED_URL, 200, VALID_FEED, "application/xml"))
    store.claim_retry.assert_called_once_with("Hugging Face Blog")


def test_probe_that_still_gets_403_stays_disabled() -> None:
    store = _store()
    items, errors, calls = _run(
        _source(), store, ALLOW, _response(FEED_URL, 403, b"Forbidden", "text/html")
    )
    assert items == [] and errors
    assert calls == [ROBOTS_URL, FEED_URL]
    store.finish_retry.assert_not_called()


@pytest.mark.parametrize("outcome", ["valid", "still_403"])
def test_403_cooldown_with_real_core_database(tmp_path: Path, outcome: str) -> None:
    import inspect

    from radar_core.crawl_health import CrawlHealthStore

    if "retry_statuses" not in inspect.signature(CrawlHealthStore.claim_retry).parameters:
        pytest.skip("installed radar-core predates the 403 opt-in cooldown")
    db_path = str(tmp_path / "health.duckdb")
    source = _source()
    with CrawlHealthStore(db_path, failure_threshold=1) as store:
        store.record_failure(
            source.name, "403 Client Error: Forbidden for url: " + FEED_URL, 0.0
        )
        store.flush()
        store.conn.execute(
            "UPDATE crawl_health SET updated_at = ? WHERE source_name = ?",
            [datetime.now(UTC).replace(tzinfo=None) - timedelta(days=8), source.name],
        )
    feed = (
        _response(FEED_URL, 200, VALID_FEED, "application/xml")
        if outcome == "valid"
        else _response(FEED_URL, 403, b"Forbidden", "text/html")
    )
    request, calls = _router(ALLOW, feed)
    with (
        patch("paperradar.collector.get_circuit_breaker_manager", return_value=_manager()),
        patch("requests.Session.request", request),
    ):
        items, _ = collect_sources(
            [source], category="research", max_workers=1, health_db_path=db_path
        )
        # Second run the same day: a failed probe advanced updated_at, so a
        # still-blocked source is not requested again for another week.
        calls.clear()
        collect_sources([source], category="research", max_workers=1, health_db_path=db_path)
        if outcome == "still_403":
            assert calls == []
    with CrawlHealthStore(db_path) as store:
        record = store.get_health(source.name)
        assert record is not None and record.failure_count >= 1
        assert record.disabled is (outcome != "valid")
    assert bool(items) is (outcome == "valid")


def _research_sources() -> dict[str, dict]:
    root = Path(__file__).resolve().parents[2]
    data = yaml.safe_load((root / "config/categories/research.yaml").read_text(encoding="utf-8"))
    return {src["name"]: src for src in data["sources"]}


def test_config_opts_in_import_ai_only_for_403() -> None:
    sources = _research_sources()
    import_ai = sources["Import AI"]["config"]
    assert import_ai["retry_after_cooldown"] is True
    assert import_ai["retry_after_cooldown_statuses"] == [403]
    assert import_ai["retry_after_cooldown_seconds"] >= 604800
    ai_news = sources["AI News"].get("config", {})
    assert not ai_news.get("retry_after_cooldown")
    assert not sources["The Gradient"].get("config", {}).get("retry_after_cooldown")
