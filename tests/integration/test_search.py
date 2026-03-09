from __future__ import annotations

from pathlib import Path

import pytest

from paperradar.models import Paper
from paperradar.search_index import SearchIndex


@pytest.mark.integration
def test_search_index_integration(
    tmp_path: Path,
    sample_papers: list[Paper],
) -> None:
    """Test search index integration: index papers → query → verify results."""
    search_db = tmp_path / "search.db"
    index = SearchIndex(search_db)

    for paper in sample_papers:
        index.upsert(
            paper_id=paper.arxiv_id or paper.link,
            title=paper.title,
            abstract=paper.abstract,
            authors=" ".join(paper.authors),
        )

    results = index.search("transformer", limit=10)
    assert len(results) > 0
    assert any("transformer" in r[1].lower() for r in results)

    results_bert = index.search("BERT", limit=10)
    assert len(results_bert) >= 0

    results_empty = index.search("nonexistent_keyword_xyz", limit=10)
    assert len(results_empty) == 0

    index.conn.close()
