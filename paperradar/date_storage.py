from __future__ import annotations

import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb


def snapshot_database(
    db_path: Path,
    *,
    snapshot_date: date | None = None,
    snapshot_root: Path | None = None,
) -> Path | None:
    if not db_path.exists():
        return None

    if snapshot_date is None:
        snapshot_date = datetime.now(UTC).date()

    if snapshot_root is None:
        snapshot_root = db_path.parent / "daily"

    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_root / f"{snapshot_date.isoformat()}.duckdb"

    shutil.copy2(db_path, snapshot_path)
    return snapshot_path


def _has_record_rows(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            tables = {str(row[0]) for row in conn.execute("SHOW TABLES").fetchall()}
            if "papers" in tables:
                row = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
                if row and int(row[0]) > 0:
                    return True
            if "articles" in tables:
                row = conn.execute("SELECT COUNT(*) FROM articles").fetchone()
                return bool(row and int(row[0]) > 0)
        finally:
            conn.close()
    except duckdb.Error:
        return False
    return False


def latest_snapshot_path(db_path: Path, *, snapshot_root: Path | None = None) -> Path | None:
    roots = (
        [snapshot_root]
        if snapshot_root is not None
        else [db_path.parent / "snapshots", db_path.parent / "daily"]
    )
    snapshots: list[tuple[date, Path]] = []

    for root in roots:
        if root is None or not root.exists():
            continue
        for child in root.iterdir():
            if child.is_dir():
                try:
                    snapshot_date = date.fromisoformat(child.name)
                except ValueError:
                    continue
                candidate = child / db_path.name
            elif child.is_file() and child.suffix == ".duckdb":
                try:
                    snapshot_date = date.fromisoformat(child.stem)
                except ValueError:
                    continue
                candidate = child
            else:
                continue
            if candidate.exists():
                snapshots.append((snapshot_date, candidate))

    if not snapshots:
        return None

    return max(snapshots, key=lambda item: item[0])[1]


def resolve_read_database_path(
    db_path: Path, *, snapshot_root: Path | None = None
) -> Path:
    if _has_record_rows(db_path):
        return db_path

    snapshot_path = latest_snapshot_path(db_path, snapshot_root=snapshot_root)
    if snapshot_path is not None and _has_record_rows(snapshot_path):
        return snapshot_path

    if db_path.exists():
        return db_path
    if snapshot_path is not None:
        return snapshot_path
    return db_path


def cleanup_date_directories(base_dir: Path, *, keep_days: int, today: date | None = None) -> int:
    if today is None:
        today = datetime.now(UTC).date()

    cutoff = today - timedelta(days=keep_days)
    removed = 0

    if not base_dir.exists():
        return 0

    for item in base_dir.iterdir():
        if not item.is_dir():
            continue

        try:
            stamp: date | None = None
            if len(item.name) == 10 and item.name.count("-") == 2:
                stamp = date.fromisoformat(item.name)
        except ValueError:
            continue

        if stamp and stamp < cutoff:
            shutil.rmtree(item)
            removed += 1

    return removed


def cleanup_dated_reports(report_dir: Path, *, keep_days: int, today: date | None = None) -> int:
    if today is None:
        today = datetime.now(UTC).date()

    cutoff = today - timedelta(days=keep_days)
    removed = 0

    if not report_dir.exists():
        return 0

    for item in report_dir.glob("*_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].html"):
        try:
            date_str = item.stem.split("_")[-1]
            if len(date_str) == 8:
                stamp = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=UTC).date()
                if stamp < cutoff:
                    item.unlink()
                    removed += 1
        except (ValueError, IndexError):
            continue

    return removed
