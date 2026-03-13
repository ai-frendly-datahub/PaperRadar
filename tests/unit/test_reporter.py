from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from paperradar.models import CategoryConfig, EntityDefinition, Paper, Source
from paperradar.reporter import generate_report


def test_report_generation():
    """Test HTML report generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"

        category = CategoryConfig(
            category_name="research",
            display_name="AI/ML Research",
            sources=[Source("arXiv", "arxiv", "http://arxiv.org")],
            entities=[],
        )

        paper = Paper(
            title="Test Paper",
            link="https://example.com",
            abstract="Test abstract",
            authors=["Author 1"],
            published=datetime.now(UTC),
            source="arXiv",
            category="research",
        )

        stats = {
            "sources": 1,
            "collected": 1,
            "matched": 1,
            "window_days": 7,
        }

        result = generate_report(
            category=category,
            articles=[paper],
            output_path=output_path,
            stats=stats,
            errors=[],
        )

        assert result.exists()
        assert result.read_text().find("Test Paper") > -1


def test_report_includes_cooccurrence_network_graphs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"

        category = CategoryConfig(
            category_name="research",
            display_name="AI/ML Research",
            sources=[Source("arXiv", "arxiv", "http://arxiv.org")],
            entities=[
                EntityDefinition(name="llm", display_name="LLM", keywords=["llm"]),
                EntityDefinition(name="rag", display_name="RAG", keywords=["rag"]),
            ],
        )

        now = datetime.now(UTC)
        paper_a = Paper(
            title="Paper A",
            link="https://example.com/a",
            abstract="A",
            authors=["Alice", "Bob"],
            published=now,
            source="arXiv",
            category="research",
            matched_entities={"llm": ["llm"], "rag": ["rag"]},
        )
        paper_b = Paper(
            title="Paper B",
            link="https://example.com/b",
            abstract="B",
            authors=["Alice", "Carol"],
            published=now,
            source="arXiv",
            category="research",
            matched_entities={"llm": ["llm"]},
        )

        stats = {
            "sources": 1,
            "collected": 2,
            "matched": 2,
            "window_days": 7,
        }

        result = generate_report(
            category=category,
            articles=[paper_a, paper_b],
            output_path=output_path,
            stats=stats,
            errors=[],
        )

        html = result.read_text()
        assert "Co-topic Network" in html
        assert "Co-author Network" in html
        assert "plotly" in html.lower()
