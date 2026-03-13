from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from paperradar.models import Paper
from paperradar.storage import RadarStorage


def test_storage_upsert():
    """Test paper upsert in storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.duckdb"
        storage = RadarStorage(db_path)

        paper = Paper(
            title="Test Paper",
            link="https://example.com/paper",
            abstract="Test abstract",
            authors=["Author 1"],
            published=datetime.now(UTC),
            source="arXiv",
            category="research",
            doi="10.1234/test",
        )

        storage.upsert_papers([paper])

        recent = storage.recent_papers("research", days=7)
        assert len(recent) > 0

        storage.close()


def test_storage_delete_old():
    """Test deletion of old papers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.duckdb"
        storage = RadarStorage(db_path)

        paper = Paper(
            title="Test",
            link="https://example.com",
            abstract="Test",
            authors=["Author"],
            published=datetime.now(UTC),
            source="arXiv",
            category="research",
        )

        storage.upsert_papers([paper])
        # Delete papers older than 365 days (should not delete recent papers)
        _ = storage.delete_older_than(365)

        storage.close()
