from __future__ import annotations

import tempfile
from datetime import datetime, timezone
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
            published=datetime.now(timezone.utc),
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
