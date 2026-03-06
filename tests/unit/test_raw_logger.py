from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from paperradar.models import Paper
from paperradar.raw_logger import RawLogger


def test_raw_logger_log():
    """Test raw logger JSONL output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        logger = RawLogger(raw_dir)
        
        paper = Paper(
            title="Test Paper",
            link="https://example.com",
            abstract="Test abstract",
            authors=["Author 1"],
            published=datetime.now(timezone.utc),
            source="arXiv",
            category="research",
        )
        
        log_file = logger.log([paper], source_name="test_source")
        
        assert log_file.exists()
        
        # Verify JSONL format
        with open(log_file) as f:
            line = f.readline()
            data = json.loads(line)
            assert data["title"] == "Test Paper"
            assert data["source"] == "arXiv"
