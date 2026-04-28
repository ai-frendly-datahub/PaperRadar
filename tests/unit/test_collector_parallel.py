from __future__ import annotations

import os
import threading
import time
from unittest.mock import Mock, patch

import pytest

from paperradar.collector import RateLimiter, _source_min_interval, collect_sources
from paperradar.exceptions import NetworkError, SourceError
from paperradar.models import Article, Source


def _build_sources(count: int) -> list[Source]:
    return [
        Source(name=f"source_{idx}", type="rss", url=f"https://example{idx}.com/feed")
        for idx in range(count)
    ]


def _pass_through_manager() -> Mock:
    breaker = Mock()
    breaker.call.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)
    manager = Mock()
    manager.get_breaker.return_value = breaker
    return manager


def test_parallel_collection_reduces_runtime() -> None:
    sources = _build_sources(5)
    manager = _pass_through_manager()

    def delayed_collect(
        source: Source,
        *,
        category: str,
        limit: int,
        timeout: int,
        session: object | None = None,
    ) -> list[Article]:
        time.sleep(0.5)
        return [
            Article(
                title=f"article-{source.name}",
                link=f"https://example.com/{source.name}",
                summary="ok",
                published=None,
                source=source.name,
                category=category,
            )
        ]

    with (
        patch("radar.collector._collect_single", side_effect=delayed_collect),
        patch("radar.collector.get_circuit_breaker_manager", return_value=manager),
        patch.dict(os.environ, {"RADAR_MAX_WORKERS": "5"}, clear=False),
    ):
        start = time.monotonic()
        articles, errors = collect_sources(sources, category="test", min_interval_per_host=0.0)
        elapsed = time.monotonic() - start

    assert len(articles) == 5
    assert errors == []
    assert elapsed < 1.4


def test_parallel_collection_isolates_source_errors() -> None:
    sources = _build_sources(5)
    manager = _pass_through_manager()

    def selective_collect(
        source: Source,
        *,
        category: str,
        limit: int,
        timeout: int,
        session: object | None = None,
    ) -> list[Article]:
        if source.name == "source_0" or source.name == "source_3":
            return [
                Article(
                    title=f"article-{source.name}",
                    link=f"https://example.com/{source.name}",
                    summary="ok",
                    published=None,
                    source=source.name,
                    category=category,
                )
            ]
        if source.name == "source_1":
            raise SourceError(source.name, "boom")
        if source.name == "source_2":
            raise NetworkError("timeout")
        raise TimeoutError("simulated timeout")

    with (
        patch("radar.collector._collect_single", side_effect=selective_collect),
        patch("radar.collector.get_circuit_breaker_manager", return_value=manager),
        patch.dict(os.environ, {"RADAR_MAX_WORKERS": "5"}, clear=False),
    ):
        articles, errors = collect_sources(sources, category="test", min_interval_per_host=0.0)

    assert len(articles) == 2
    assert {item.source for item in articles} == {"source_0", "source_3"}
    assert len(errors) == 3


def test_max_workers_one_preserves_sequential_order() -> None:
    sources = _build_sources(5)
    manager = _pass_through_manager()

    def ordered_collect(
        source: Source,
        *,
        category: str,
        limit: int,
        timeout: int,
        session: object | None = None,
    ) -> list[Article]:
        return [
            Article(
                title=f"article-{source.name}",
                link=f"https://example.com/{source.name}",
                summary="ok",
                published=None,
                source=source.name,
                category=category,
            )
        ]

    with (
        patch("radar.collector._collect_single", side_effect=ordered_collect),
        patch("radar.collector.get_circuit_breaker_manager", return_value=manager),
        patch.dict(os.environ, {"RADAR_MAX_WORKERS": "5"}, clear=False),
    ):
        articles, errors = collect_sources(
            sources,
            category="test",
            min_interval_per_host=0.0,
            max_workers=1,
        )

    assert errors == []
    assert [item.source for item in articles] == [source.name for source in sources]


def test_rate_limiter_is_thread_safe() -> None:
    limiter = RateLimiter(min_interval=0.0)
    assert hasattr(limiter, "_lock")

    errors: list[Exception] = []

    def worker() -> None:
        try:
            for _ in range(500):
                limiter.acquire()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []


def test_arxiv_sources_use_official_minimum_interval() -> None:
    arxiv_rss = Source(
        name="arXiv CS.AI",
        type="rss",
        url="https://export.arxiv.org/rss/cs.AI",
    )
    arxiv_api = Source(
        name="arXiv API Recent AI",
        type="arxiv",
        url="https://export.arxiv.org/api/query?search_query=cat:cs.AI",
    )
    regular = Source(
        name="Regular Feed",
        type="rss",
        url="https://example.com/feed",
    )

    assert _source_min_interval(arxiv_rss, 0.5) == 3.0
    assert _source_min_interval(arxiv_api, 0.5) == 3.0
    assert _source_min_interval(regular, 0.5) == 0.5


def test_same_host_collection_is_serialized(tmp_path) -> None:
    sources = [
        Source(name="source_a", type="rss", url="https://same.example/feed-a"),
        Source(name="source_b", type="rss", url="https://same.example/feed-b"),
    ]
    manager = _pass_through_manager()
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def delayed_collect(
        source: Source,
        *,
        category: str,
        limit: int,
        timeout: int,
        session: object | None = None,
    ) -> list[Article]:
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with active_lock:
            active -= 1
        return [
            Article(
                title=f"article-{source.name}",
                link=f"https://example.com/{source.name}",
                summary="ok",
                published=None,
                source=source.name,
                category=category,
            )
        ]

    with (
        patch("radar.collector._collect_single", side_effect=delayed_collect),
        patch("radar.collector.get_circuit_breaker_manager", return_value=manager),
        patch.dict(os.environ, {"RADAR_MAX_WORKERS": "2"}, clear=False),
    ):
        articles, errors = collect_sources(
            sources,
            category="test",
            min_interval_per_host=0.0,
            health_db_path=str(tmp_path / "health.duckdb"),
        )

    assert len(articles) == 2
    assert errors == []
    assert max_active == 1


def test_env_var_radar_max_workers_is_used() -> None:
    sources = _build_sources(2)
    manager = _pass_through_manager()
    mock_future = Mock()
    mock_future.result.return_value = ([], [])

    with (
        patch("radar.collector._collect_single", return_value=[]),
        patch("radar.collector.get_circuit_breaker_manager", return_value=manager),
        patch("radar.collector.ThreadPoolExecutor") as mock_executor,
        patch.dict(os.environ, {"RADAR_MAX_WORKERS": "7"}, clear=False),
    ):
        executor_instance = mock_executor.return_value.__enter__.return_value
        executor_instance.submit.return_value = mock_future
        collect_sources(sources, category="test", min_interval_per_host=0.0)

    mock_executor.assert_called_once_with(max_workers=7)


@pytest.mark.parametrize("env_value,expected_workers", [("999", 10), ("-3", 1), ("invalid", 5)])
def test_max_workers_is_capped_and_validated(env_value: str, expected_workers: int) -> None:
    sources = _build_sources(2)
    manager = _pass_through_manager()
    mock_future = Mock()
    mock_future.result.return_value = ([], [])

    with (
        patch("radar.collector._collect_single", return_value=[]),
        patch("radar.collector.get_circuit_breaker_manager", return_value=manager),
        patch("radar.collector.ThreadPoolExecutor") as mock_executor,
        patch.dict(os.environ, {"RADAR_MAX_WORKERS": env_value}, clear=False),
    ):
        executor_instance = mock_executor.return_value.__enter__.return_value
        executor_instance.submit.return_value = mock_future
        _, _ = collect_sources(sources, category="test", min_interval_per_host=0.0)

    if expected_workers == 1:
        mock_executor.assert_not_called()
    else:
        mock_executor.assert_called_once_with(max_workers=expected_workers)
