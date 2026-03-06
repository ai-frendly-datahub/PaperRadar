from __future__ import annotations

import tempfile
from pathlib import Path

from paperradar.config_loader import load_category_config, load_settings


def test_load_settings():
    """Test loading settings from config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.yaml"
        config_file.write_text("""
database_path: data/papers.duckdb
report_dir: reports
raw_data_dir: data/raw
search_db_path: data/search.db
""")
        
        settings = load_settings(config_file)
        
        assert settings.database_path == Path("data/papers.duckdb")
        assert settings.report_dir == Path("reports")


def test_load_category_config():
    """Test loading category configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        categories_dir = Path(tmpdir)
        config_file = categories_dir / "test.yaml"
        config_file.write_text("""
category_name: test
display_name: Test Category

sources:
  - name: Source1
    type: arxiv
    url: http://example.com

entities:
  - name: Entity1
    display_name: Entity 1
    keywords: [keyword1, keyword2]
""")
        
        config = load_category_config("test", categories_dir=categories_dir)
        
        assert config.category_name == "test"
        assert config.display_name == "Test Category"
        assert len(config.sources) == 1
        assert len(config.entities) == 1
