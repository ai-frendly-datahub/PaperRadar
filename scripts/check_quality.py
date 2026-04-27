#!/usr/bin/env python3
"""Run DuckDB checks and write PaperRadar quality JSON."""

from __future__ import annotations

from datetime import UTC, date, datetime
import sys
from pathlib import Path
from typing import Any

import duckdb
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RADAR_CORE_ROOT = PROJECT_ROOT.parent / "radar-core"
if RADAR_CORE_ROOT.exists():
    sys.path.insert(0, str(RADAR_CORE_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from paperradar.config_loader import (  # noqa: E402
    load_category_config,
    load_category_quality_config,
)
from paperradar.quality_report import build_quality_report, write_quality_report  # noqa: E402
from paperradar.storage import RadarStorage  # noqa: E402


CATEGORY_NAME = "research"


def _project_path(project_root: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else project_root / path


def _load_runtime_config(project_root: Path) -> dict[str, Any]:
    raw = yaml.safe_load((project_root / "config" / "config.yaml").read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _coerce_date(value: object) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def _latest_article_date(db_path: Path, category_name: str) -> date | None:
    if not db_path.exists():
        return None
    try:
        with duckdb.connect(str(db_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT MAX(COALESCE(published, collected_at))
                FROM articles
                WHERE category = ?
                """,
                [category_name],
            ).fetchone()
    except duckdb.Error:
        return None
    if not row:
        return None
    return _coerce_date(row[0])


def _lookback_days(target_date: date | None, *, minimum_days: int = 14) -> int:
    if target_date is None:
        return minimum_days
    age_days = (datetime.now(UTC).date() - target_date).days + 1
    return max(minimum_days, age_days)


def generate_quality_artifacts(
    project_root: Path = PROJECT_ROOT,
    *,
    category_name: str = CATEGORY_NAME,
) -> tuple[dict[str, Path], dict[str, Any]]:
    runtime_config = _load_runtime_config(project_root)
    db_path = _project_path(
        project_root,
        str(runtime_config.get("database_path", "data/papers.duckdb")),
    )
    report_dir = _project_path(
        project_root,
        str(runtime_config.get("report_dir", "reports")),
    )
    categories_dir = project_root / "config" / "categories"
    category = load_category_config(category_name, categories_dir=categories_dir)
    quality_config = load_category_quality_config(category_name, categories_dir=categories_dir)
    lookback_days = _lookback_days(_latest_article_date(db_path, category.category_name))
    with RadarStorage(db_path) as storage:
        articles = storage.recent_articles(
            category.category_name,
            days=lookback_days,
            limit=max(500, len(category.sources) * 20),
        )

    report = build_quality_report(
        category=category,
        articles=articles,
        errors=[],
        quality_config=quality_config,
    )
    paths = write_quality_report(
        report,
        output_dir=report_dir,
        category_name=category.category_name,
    )
    return paths, report


def main() -> None:
    runtime_config = _load_runtime_config(PROJECT_ROOT)
    db_path = _project_path(
        PROJECT_ROOT,
        str(runtime_config.get("database_path", "data/papers.duckdb")),
    )

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    _run_db_checks(db_path)
    paths, report = generate_quality_artifacts(PROJECT_ROOT)
    _print_summary(report, article_count=len(report.get("events", [])), latest_path=paths["latest"])


def _run_db_checks(db_path: Path) -> None:
    with duckdb.connect(str(db_path), read_only=True) as con:
        total = con.execute("SELECT COUNT(*) FROM articles").fetchone()
        total_count = int(total[0] if total else 0)
        print(f"Total records: {total_count}")

        print("\n=== Missing Field Check ===\n")
        null_conditions = {
            "title": "title IS NULL OR title = ''",
            "link": "link IS NULL OR link = ''",
            "summary": "summary IS NULL OR summary = ''",
            "published": "published IS NULL",
        }
        for field, condition in null_conditions.items():
            missing = con.execute(f"SELECT COUNT(*) FROM articles WHERE {condition}").fetchone()
            missing_count = int(missing[0] if missing else 0)
            rate = (missing_count / total_count * 100.0) if total_count else 0.0
            print(f"  {field}: {missing_count} / {total_count} ({rate:.1f}%)")

        duplicates = con.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT link
                FROM articles
                GROUP BY link
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()
        print("\n=== Duplicate URL Check ===\n")
        print(f"  duplicate links: {int(duplicates[0] if duplicates else 0)}")

        date_row = con.execute(
            """
            SELECT
                MIN(COALESCE(published, collected_at)),
                MAX(COALESCE(published, collected_at)),
                SUM(CASE WHEN published > CURRENT_TIMESTAMP THEN 1 ELSE 0 END)
            FROM articles
            """
        ).fetchone()
        print("\n=== Date Check ===\n")
        print(f"  oldest: {_row_value(date_row, 0)}")
        print(f"  newest: {_row_value(date_row, 1)}")
        print(f"  future dates: {_row_value(date_row, 2) or 0}")


def _print_summary(report: dict[str, Any], *, article_count: int, latest_path: Path) -> None:
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        return
    print(f"scoped_articles={article_count}")
    print(f"quality_report={latest_path}")
    print(f"tracked_sources={summary.get('tracked_sources', 0)}")
    print(f"fresh_sources={summary.get('fresh_sources', 0)}")
    print(f"stale_sources={summary.get('stale_sources', 0)}")
    print(f"missing_sources={summary.get('missing_sources', 0)}")
    print(f"not_tracked_sources={summary.get('not_tracked_sources', 0)}")
    print(f"research_signal_event_count={summary.get('research_signal_event_count', 0)}")


def _row_value(row: object, index: int) -> object:
    if isinstance(row, tuple) and len(row) > index:
        return row[index]
    return None


if __name__ == "__main__":
    main()
