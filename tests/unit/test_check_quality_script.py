from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from paperradar.models import Paper
from paperradar.storage import RadarStorage


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_quality.py"
    spec = importlib.util.spec_from_file_location("paperradar_check_quality_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_quality_artifacts_uses_latest_stored_checkpoint(
    tmp_path: Path,
    capsys,
) -> None:
    project_root = tmp_path
    (project_root / "config" / "categories").mkdir(parents=True)

    (project_root / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "database_path": "data/papers.duckdb",
                "report_dir": "reports",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_root / "config" / "categories" / "research.yaml").write_text(
        yaml.safe_dump(
            {
                "category_name": "research",
                "display_name": "Research",
                "sources": [
                    {
                        "id": "arxiv_recent_ai",
                        "name": "arXiv API Recent AI",
                        "type": "rss",
                        "url": "https://export.arxiv.org/api/query",
                        "content_type": "preprint",
                        "enabled": True,
                        "info_purpose": ["paper_release"],
                    }
                ],
                "entities": [],
                "data_quality": {
                    "quality_outputs": {
                        "tracked_event_models": ["paper_release"],
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    article_time = datetime.now(UTC) - timedelta(days=30)
    db_path = project_root / "data" / "papers.duckdb"
    with RadarStorage(db_path) as storage:
        storage.upsert_papers(
            [
                Paper(
                    title="Attention Is All You Need",
                    link="https://arxiv.org/abs/1706.03762",
                    abstract="Transformer paper.",
                    authors=["A. Author"],
                    published=article_time,
                    source="arXiv API Recent AI",
                    category="research",
                    arxiv_id="1706.03762",
                )
            ]
        )

    module = _load_script_module()
    paths, report = module.generate_quality_artifacts(project_root)

    assert Path(paths["latest"]).exists()
    assert Path(paths["dated"]).exists()
    assert report["summary"]["tracked_sources"] == 1
    assert report["summary"]["paper_release_events"] == 1

    module.PROJECT_ROOT = project_root
    module.main()
    captured = capsys.readouterr()
    assert "quality_report=" in captured.out
    assert "tracked_sources=1" in captured.out
    assert "research_signal_event_count=1" in captured.out
