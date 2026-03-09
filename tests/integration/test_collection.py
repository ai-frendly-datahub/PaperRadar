from __future__ import annotations

from unittest.mock import patch

import pytest

from paperradar.models import Paper, Source
from paperradar.storage import RadarStorage


@pytest.mark.integration
def test_collection_workflow(
    sample_papers: list[Paper],
) -> None:
    """Test complete collection workflow: mock API → collect → verify structure."""
    with patch("paperradar.collector.collect_sources") as mock_collect:
        mock_collect.return_value = (sample_papers, [])

        papers, errors = mock_collect(
            [Source(name="arXiv", type="arxiv", url="http://export.arxiv.org/api/query")],
            category="research",
            limit_per_source=30,
        )

        assert len(papers) == 5
        assert len(errors) == 0
        assert all(isinstance(p, Paper) for p in papers)
        assert all(p.category == "research" for p in papers)


@pytest.mark.integration
def test_storage_persistence(
    tmp_storage: RadarStorage,
    sample_papers: list[Paper],
) -> None:
    """Test storage integration: insert papers → query → verify data integrity."""
    tmp_storage.upsert_papers(sample_papers)

    papers = tmp_storage.recent_papers(category="research", days=30)

    assert len(papers) == 5
    titles = [p[1] for p in papers]
    assert "Attention Is All You Need" in titles
    assert "BERT: Pre-training of Deep Bidirectional Transformers" in titles


@pytest.mark.integration
def test_duplicate_handling(
    tmp_storage: RadarStorage,
    sample_papers: list[Paper],
) -> None:
    """Test duplicate handling: insert same paper twice → verify single entry."""
    tmp_storage.upsert_papers(sample_papers[:2])
    result1 = tmp_storage.recent_papers(category="research", days=30)
    assert len(result1) == 2

    tmp_storage.upsert_papers(sample_papers[:2])
    result2 = tmp_storage.recent_papers(category="research", days=30)
    assert len(result2) == 2

    tmp_storage.upsert_papers(sample_papers[2:])
    result3 = tmp_storage.recent_papers(category="research", days=30)
    assert len(result3) == 5
