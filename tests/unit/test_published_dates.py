"""Published dates stay on the UTC instant when the crawler zone is Asia/Seoul."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from paperradar.collector import _extract_datetime, _extract_published
from paperradar.date_storage import snapshot_database
from paperradar.models import Article, Source
from paperradar.quality_report import write_quality_report
from paperradar.raw_logger import RawLogger
from paperradar.storage import RadarStorage

_STRUCT = time.struct_time((2026, 10, 28, 15, 0, 0, 2, 301, 0))
_KST = timezone(timedelta(hours=9))


def _seoul(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Seoul")
    time.tzset()


def _restore_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    time.tzset()


def test_feedparser_struct_stores_1500_utc_under_asia_seoul(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """2026-10-28 15:00 UTC must stay 15:00 UTC when TZ=Asia/Seoul.

    ``time.mktime`` would treat the feedparser struct as KST and store 06:00.
    """
    _seoul(monkeypatch)
    try:
        shifted = datetime.fromtimestamp(time.mktime(_STRUCT), tz=UTC)
        assert shifted == datetime(2026, 10, 28, 6, 0, tzinfo=UTC)

        published = _extract_datetime({"published_parsed": _STRUCT})
        updated = _extract_datetime({"updated_parsed": _STRUCT})
        assert published == datetime(2026, 10, 28, 15, 0, tzinfo=UTC)
        assert updated == published

        storage = RadarStorage(tmp_path / "papers.duckdb")
        try:
            storage.upsert_articles(
                [
                    Article(
                        title="UTC struct",
                        link="https://example.com/utc-struct",
                        summary="abstract",
                        published=published,
                        source="arXiv",
                        category="research",
                    )
                ]
            )
            row = storage.conn.execute("SELECT published FROM articles").fetchone()
            assert row is not None
            stored = row[0]
            assert isinstance(stored, datetime)
            assert stored.tzinfo is None
            assert (stored.year, stored.month, stored.day, stored.hour, stored.minute) == (
                2026,
                10,
                28,
                15,
                0,
            )
            loaded = storage.recent_articles("research", days=30)
            assert loaded[0].published == datetime(2026, 10, 28, 15, 0, tzinfo=UTC)
        finally:
            storage.close()
    finally:
        _restore_tz(monkeypatch)


def test_offset_string_keeps_offset_and_zoneless_kr_uses_seoul(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seoul(monkeypatch)
    try:
        offset, raw = _extract_published({"published": "Thu, 28 Oct 2026 15:00:00 +0900"})
        assert raw == "Thu, 28 Oct 2026 15:00:00 +0900"
        assert offset is not None
        assert offset.utcoffset() == timedelta(hours=9)
        assert offset.astimezone(UTC) == datetime(2026, 10, 28, 6, 0, tzinfo=UTC)

        source = Source(name="KR", type="rss", url="https://example.kr/rss")
        zoneless, _ = _extract_published({"published": "2026-10-28 15:00:00"}, source)
        assert zoneless == datetime(2026, 10, 28, 15, 0, tzinfo=_KST)
        assert zoneless is not None
        assert zoneless.astimezone(UTC) == datetime(2026, 10, 28, 6, 0, tzinfo=UTC)

        explicit = Source(
            name="Named",
            type="rss",
            url="https://example.com/rss",
            default_timezone="Asia/Seoul",
        )
        named, _ = _extract_published({"published": "2026-10-28 15:00:00"}, explicit)
        assert named == datetime(2026, 10, 28, 15, 0, tzinfo=_KST)
    finally:
        _restore_tz(monkeypatch)


def test_daily_partition_uses_seoul_calendar_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    moment = datetime(2026, 10, 28, 15, 30, tzinfo=UTC)

    class _Clock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            if tz is None:
                return moment.replace(tzinfo=None)
            return moment

    monkeypatch.setattr("paperradar.raw_logger.datetime", _Clock)
    monkeypatch.setattr("paperradar.date_storage.datetime", _Clock)

    article = Article(
        title="Partition",
        link="https://example.com/partition",
        summary="abstract",
        published=moment,
        source="arXiv",
        category="research",
    )
    raw_path = RawLogger(tmp_path / "raw").log([article], source_name="src")
    assert raw_path.parent.name == "2026-10-29"

    db_file = tmp_path / "papers.duckdb"
    db_file.write_text("fake-db")
    snapshot = snapshot_database(db_file)
    assert snapshot is not None
    assert snapshot.name == "2026-10-29.duckdb"

    paths = write_quality_report(
        {"generated_at": moment.isoformat()},
        output_dir=tmp_path / "reports",
        category_name="research",
    )
    assert paths["dated"].name == "research_20261029_quality.json"
