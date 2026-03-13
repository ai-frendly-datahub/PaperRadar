from __future__ import annotations

from datetime import UTC, datetime

from paperradar.models import Paper, Source


def test_paper_creation():
    """Test Paper model creation."""
    paper = Paper(
        title="Test Paper",
        link="https://example.com/paper",
        abstract="Test abstract",
        authors=["Author 1", "Author 2"],
        published=datetime.now(UTC),
        source="arXiv",
        category="research",
    )

    assert paper.title == "Test Paper"
    assert len(paper.authors) == 2
    assert paper.source == "arXiv"


def test_paper_with_arxiv_id():
    """Test Paper with arXiv ID."""
    paper = Paper(
        title="Test",
        link="https://arxiv.org/abs/2301.00001",
        abstract="Test",
        authors=["Author"],
        published=None,
        source="arXiv",
        category="research",
        arxiv_id="2301.00001",
    )

    assert paper.arxiv_id == "2301.00001"


def test_source_creation():
    """Test Source model creation."""
    source = Source(
        name="arXiv",
        type="arxiv",
        url="http://export.arxiv.org/api/query",
    )

    assert source.name == "arXiv"
    assert source.type == "arxiv"
