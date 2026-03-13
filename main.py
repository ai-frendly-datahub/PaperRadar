from __future__ import annotations

import argparse
from datetime import UTC
from pathlib import Path

from paperradar.analyzer import apply_entity_rules
from paperradar.collector import collect_sources
from paperradar.common.validators import validate_article
from paperradar.config_loader import load_category_config, load_settings
from paperradar.models import Paper
from paperradar.raw_logger import RawLogger
from paperradar.reporter import generate_report
from paperradar.search_index import SearchIndex
from paperradar.storage import RadarStorage


def _send_notifications(
    *,
    category_name: str,
    sources_count: int,
    collected_count: int,
    matched_count: int,
    errors_count: int,
    report_path: Path,
) -> None:
    import os
    from datetime import datetime

    email_to = os.environ.get("NOTIFICATION_EMAIL")
    webhook_url = os.environ.get("NOTIFICATION_WEBHOOK")

    if not email_to and not webhook_url:
        return

    from paperradar.notifier import (
        CompositeNotifier,
        EmailNotifier,
        NotificationPayload,
        WebhookNotifier,
    )

    payload = NotificationPayload(
        category_name=category_name,
        sources_count=sources_count,
        collected_count=collected_count,
        matched_count=matched_count,
        errors_count=errors_count,
        timestamp=datetime.now(UTC),
        report_url=str(report_path),
    )

    notifiers: list[object] = []
    if email_to:
        notifiers.append(
            EmailNotifier(
                smtp_host=os.environ.get("SMTP_HOST", "localhost"),
                smtp_port=int(os.environ.get("SMTP_PORT", "587")),
                smtp_user=os.environ.get("SMTP_USER", ""),
                smtp_password=os.environ.get("SMTP_PASSWORD", ""),
                from_addr=os.environ.get("SMTP_FROM", ""),
                to_addrs=[email_to],
            )
        )
    if webhook_url:
        notifiers.append(WebhookNotifier(url=webhook_url))

    if notifiers:
        composite = CompositeNotifier(notifiers)
        _ = composite.send(payload)


def run(
    *,
    category: str,
    config_path: Path | None = None,
    categories_dir: Path | None = None,
    per_source_limit: int = 30,
    recent_days: int = 7,
    timeout: int = 15,
    keep_days: int = 90,
    keep_raw_days: int = 180,
    keep_report_days: int = 90,
    snapshot_db: bool = False,
) -> Path:
    """Execute the paper collection pipeline."""
    settings = load_settings(config_path)
    category_cfg = load_category_config(category, categories_dir=categories_dir)

    print(
        f"[PaperRadar] Collecting '{category_cfg.display_name}' from {len(category_cfg.sources)} sources..."
    )
    collected, errors = collect_sources(
        category_cfg.sources,
        category=category_cfg.category_name,
        limit_per_source=per_source_limit,
        timeout=timeout,
    )

    raw_logger = RawLogger(settings.raw_data_dir)
    for source in category_cfg.sources:
        source_papers = [p for p in collected if p.source == source.name]
        if source_papers:
            _ = raw_logger.log(source_papers, source_name=source.name)

    analyzed = apply_entity_rules(collected, category_cfg.entities)

    validated_articles: list[Paper] = []
    validation_errors: list[str] = []
    for article in analyzed:
        is_valid, validation_msgs = validate_article(article)
        if is_valid:
            validated_articles.append(article)
        else:
            validation_errors.append(f"{article.link}: {', '.join(validation_msgs)}")

    errors.extend(validation_errors)

    storage = RadarStorage(settings.database_path)
    storage.upsert_papers(validated_articles)
    _ = storage.delete_older_than(keep_days)

    with SearchIndex(settings.search_db_path) as search_idx:
        for paper in validated_articles:
            search_idx.upsert(
                paper.doi or paper.arxiv_id or paper.link,
                paper.title,
                paper.abstract,
                " ".join(paper.authors),
            )

    _ = storage.recent_papers(category_cfg.category_name, days=recent_days)
    storage.close()

    stats = {
        "sources": len(category_cfg.sources),
        "collected": len(collected),
        "matched": sum(1 for p in collected if p.matched_entities),
        "validated": len(validated_articles),
        "window_days": recent_days,
    }

    output_path = settings.report_dir / f"{category_cfg.category_name}_report.html"
    _ = generate_report(
        category=category_cfg,
        articles=validated_articles[:50],
        output_path=output_path,
        stats=stats,
        errors=errors,
    )
    print(f"[PaperRadar] Report generated at {output_path}")
    if errors:
        print(f"[PaperRadar] {len(errors)} source(s) had issues. See report for details.")

    _send_notifications(
        category_name=category_cfg.category_name,
        sources_count=len(category_cfg.sources),
        collected_count=len(collected),
        matched_count=sum(1 for p in collected if p.matched_entities),
        errors_count=len(errors),
        report_path=output_path,
    )

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PaperRadar: Academic paper collection")
    _ = parser.add_argument("--category", required=True, help="Category name (e.g., 'research')")
    _ = parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    _ = parser.add_argument(
        "--categories-dir", type=Path, default=None, help="Custom categories directory"
    )
    _ = parser.add_argument(
        "--per-source-limit", type=int, default=30, help="Max papers per source"
    )
    _ = parser.add_argument("--recent-days", type=int, default=7, help="Report window (days)")
    _ = parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout (seconds)")
    _ = parser.add_argument("--keep-days", type=int, default=90, help="Retention window (days)")
    _ = parser.add_argument(
        "--keep-raw-days", type=int, default=180, help="Retention window for raw JSONL directories"
    )
    _ = parser.add_argument(
        "--keep-report-days", type=int, default=90, help="Retention window for dated HTML reports"
    )
    _ = parser.add_argument(
        "--snapshot-db",
        action="store_true",
        default=False,
        help="Create a dated DuckDB snapshot after each run",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(
        category=args.category,
        config_path=args.config,
        categories_dir=args.categories_dir,
        per_source_limit=args.per_source_limit,
        recent_days=args.recent_days,
        timeout=args.timeout,
        keep_days=args.keep_days,
        keep_raw_days=args.keep_raw_days,
        keep_report_days=args.keep_report_days,
        snapshot_db=args.snapshot_db,
    )
