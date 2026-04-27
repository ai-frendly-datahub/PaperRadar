from __future__ import annotations

import json
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
        assert result.read_text(encoding="utf-8").find("Test Paper") > -1


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

        html = result.read_text(encoding="utf-8")
        assert "Co-topic Network" in html
        assert "Co-author Network" in html
        assert "plotly" in html.lower()


def test_report_includes_paper_quality_panel() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "research_report.html"

        category = CategoryConfig(
            category_name="research",
            display_name="AI/ML Research",
            sources=[Source("arXiv", "arxiv", "http://arxiv.org")],
            entities=[],
        )
        paper = Paper(
            title="Test Paper",
            link="https://arxiv.org/abs/1706.03762",
            abstract="Test abstract",
            authors=["Author 1"],
            published=datetime(2026, 4, 13, tzinfo=UTC),
            source="arXiv",
            category="research",
            arxiv_id="1706.03762",
        )
        quality_report = {
            "generated_at": "2026-04-13T00:00:00+00:00",
            "summary": {
                "research_signal_event_count": 1,
                "paper_canonical_key_present_count": 1,
                "repository_canonical_key_present_count": 0,
                "benchmark_canonical_key_present_count": 0,
                "event_required_field_gap_count": 1,
                "daily_review_item_count": 1,
            },
            "events": [
                {
                    "event_model": "paper_release",
                    "source": "arXiv",
                    "canonical_key": "paper:arxiv:1706.03762",
                    "citation_count": 10,
                }
            ],
            "daily_review_items": [
                {
                    "reason": "missing_required_fields",
                    "event_model": "code_repository",
                    "source": "Papers With Code",
                    "required_field_gaps": ["repository"],
                }
            ],
        }

        result = generate_report(
            category=category,
            articles=[paper],
            output_path=output_path,
            stats={"sources": 1, "collected": 1, "matched": 1, "window_days": 7},
            errors=[],
            quality_report=quality_report,
        )

        html = result.read_text(encoding="utf-8")
        assert "Paper Quality" in html
        assert "paper_release" in html
        assert "paper:arxiv:1706.03762" in html
        assert "missing_required_fields" in html

        dated_html = next(
            Path(tmpdir).glob("research_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].html")
        )
        dated_text = dated_html.read_text(encoding="utf-8")
        assert "Paper Quality" in dated_text
        assert "missing_required_fields" in dated_text

        summary_path = next(
            Path(tmpdir).glob(
                "research_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_summary.json"
            )
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["ontology"]["repo"] == "PaperRadar"
        assert summary["ontology"]["ontology_version"] == "0.1.0"
        assert "paper.paper_release" in summary["ontology"]["event_model_ids"]
