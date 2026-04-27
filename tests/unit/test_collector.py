from __future__ import annotations

from unittest.mock import patch

from paperradar.collector import collect_sources
from paperradar.models import Source


def test_collect_sources_empty():
    """Test collecting from empty sources list."""
    papers, errors = collect_sources([], category="research")

    assert len(papers) == 0
    assert len(errors) == 0


def test_collect_sources_unsupported_type():
    """Test unsupported source type."""
    source = Source(
        name="Unknown",
        type="unknown_type",
        url="http://example.com",
    )

    papers, errors = collect_sources([source], category="research", limit_per_source=5)

    assert len(papers) == 0
    assert len(errors) == 1
    assert "Unsupported source type" in errors[0]


def test_collect_sources_skips_disabled_sources():
    source = Source(
        name="Disabled Feed",
        type="rss",
        url="http://example.com/feed",
        enabled=False,
    )

    with patch("paperradar.collector._collect_single") as mock_collect:
        papers, errors = collect_sources([source], category="research", limit_per_source=5)

    assert papers == []
    assert errors == []
    mock_collect.assert_not_called()
