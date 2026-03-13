from __future__ import annotations

import tempfile
from pathlib import Path

from paperradar.analyzer import apply_entity_rules
from paperradar.config_loader import load_settings
from paperradar.models import EntityDefinition, Paper
from paperradar.reporter import generate_report
from paperradar.storage import RadarStorage


def test_full_pipeline():
    """Test complete pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create minimal config
        config_dir = tmpdir_path / "config"
        config_dir.mkdir()

        config_file = config_dir / "config.yaml"
        config_file.write_text(f"""
database_path: {tmpdir_path}/papers.duckdb
report_dir: {tmpdir_path}/reports
raw_data_dir: {tmpdir_path}/raw
search_db_path: {tmpdir_path}/search.db
""")

        settings = load_settings(config_file)

        # Create test papers
        papers = [
            Paper(
                title="Test Paper 1",
                link="https://example.com/1",
                abstract="About transformers",
                authors=["Author 1"],
                published=None,
                source="arXiv",
                category="research",
            ),
        ]

        # Apply entity rules
        entities = [
            EntityDefinition(
                name="Techniques",
                display_name="Techniques",
                keywords=["transformer", "BERT"],
            ),
        ]

        analyzed = apply_entity_rules(papers, entities)

        # Store
        storage = RadarStorage(settings.database_path)
        storage.upsert_papers(analyzed)
        storage.close()

        # Generate report
        from paperradar.models import CategoryConfig

        category = CategoryConfig(
            category_name="research",
            display_name="Research",
            sources=[],
            entities=entities,
        )

        output = generate_report(
            category=category,
            articles=analyzed,
            output_path=settings.report_dir / "test.html",
            stats={"sources": 1, "collected": 1, "matched": 1, "window_days": 7},
            errors=[],
        )

        assert output.exists()
