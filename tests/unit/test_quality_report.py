from __future__ import annotations

from datetime import UTC, datetime

import pytest

from paperradar.models import Article, CategoryConfig, Paper, Source
from paperradar.quality_report import build_quality_report


pytestmark = pytest.mark.unit


def test_build_quality_report_extracts_paper_and_repository_keys() -> None:
    paper_source = Source(
        name="arXiv API Recent AI",
        type="arxiv",
        url="https://export.arxiv.org/api/query",
        trust_tier="T1_official",
        content_type="preprint",
        info_purpose=["paper_release"],
    )
    code_source = Source(
        name="Papers With Code",
        type="rss",
        url="https://paperswithcode.com/rss",
        trust_tier="T2_institutional",
        content_type="implementation",
        info_purpose=["code_repository"],
        config={"event_model": "code_repository"},
    )
    benchmark_source = Source(
        name="Benchmark Feed",
        type="api",
        url="https://example.com/benchmarks",
        trust_tier="T2_institutional",
        content_type="benchmark_leaderboard",
        config={"event_model": "benchmark_result"},
    )
    category = CategoryConfig(
        category_name="research",
        display_name="Research",
        sources=[paper_source, code_source, benchmark_source],
        entities=[],
    )
    articles = [
        Paper(
            title="Attention Is All You Need",
            link="https://arxiv.org/abs/1706.03762",
            abstract="Transformer paper.",
            authors=["A. Author"],
            published=datetime(2026, 4, 13, tzinfo=UTC),
            source="arXiv API Recent AI",
            category="research",
            arxiv_id="1706.03762",
            doi="10.48550/arXiv.1706.03762",
            citation_count=42000,
        ),
        Paper(
            title="Implementation release",
            link="https://example.com/code",
            abstract="Repository: github.com/example/attention-code.",
            authors=["B. Author"],
            published=datetime(2026, 4, 13, tzinfo=UTC),
            source="Papers With Code",
            category="research",
            arxiv_id="1706.03762",
        ),
        Paper(
            title="Benchmark update",
            link="https://example.com/benchmark",
            abstract="Benchmark: MMLU. Metric name: accuracy. Metric value: 92.5.",
            authors=["C. Author"],
            published=datetime(2026, 4, 13, tzinfo=UTC),
            source="Benchmark Feed",
            category="research",
            arxiv_id="1706.03762",
        ),
    ]

    report = build_quality_report(
        category=category,
        articles=articles,
        quality_config={
            "data_quality": {
                "quality_outputs": {
                    "tracked_event_models": [
                        "paper_release",
                        "code_repository",
                        "benchmark_result",
                    ]
                },
                "event_models": {
                    "paper_release": {
                        "required_fields": ["paper_id", "title", "source_url"]
                    },
                    "code_repository": {
                        "required_fields": ["paper_id", "repository", "source_url"]
                    },
                    "benchmark_result": {
                        "required_fields": [
                            "paper_id",
                            "benchmark_name",
                            "metric_name",
                            "metric_value",
                        ]
                    },
                },
            },
            "source_backlog": {
                "operational_candidates": [
                    {
                        "name": "OpenAlex citation API",
                        "signal_type": "citation_snapshot",
                        "activation_gate": "DOI/arXiv mapping",
                    }
                ]
            },
        },
        generated_at=datetime(2026, 4, 14, tzinfo=UTC),
    )

    summary = report["summary"]
    assert summary["paper_release_events"] == 1
    assert summary["code_repository_events"] == 1
    assert summary["benchmark_result_events"] == 1
    assert summary["paper_canonical_key_present_count"] == 1
    assert summary["repository_canonical_key_present_count"] == 1
    assert summary["benchmark_canonical_key_present_count"] == 1
    assert summary["citation_count_present_count"] == 1
    assert summary["event_required_field_gap_count"] == 0

    events = {event["event_model"]: event for event in report["events"]}
    assert events["paper_release"]["canonical_key"] == "paper:doi:10.48550-arxiv.1706.03762"
    assert events["paper_release"]["citation_count"] == 42000
    assert (
        events["code_repository"]["canonical_key"]
        == "repository:github.com:example:attention-code:paper:arxiv-1706.03762"
    )
    assert events["benchmark_result"]["canonical_key"].startswith(
        "benchmark:arxiv-1706.03762:mmlu:accuracy"
    )
    assert any(
        item["reason"] == "source_backlog_pending"
        for item in report["daily_review_items"]
    )


def test_build_quality_report_flags_title_proxy_and_required_gaps() -> None:
    source = Source(
        name="OpenAI Blog",
        type="rss",
        url="https://openai.com/news/rss.xml",
        content_type="model_release",
        config={"event_model": "paper_release"},
    )
    category = CategoryConfig(
        category_name="research",
        display_name="Research",
        sources=[source],
        entities=[],
    )
    article = Paper(
        title="Model system card update",
        link="https://example.com/update",
        abstract="No DOI or arXiv ID.",
        authors=[],
        published=datetime(2026, 4, 13, tzinfo=UTC),
        source="OpenAI Blog",
        category="research",
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["paper_release"]},
                "event_models": {
                    "paper_release": {
                        "required_fields": ["paper_id", "title", "source_url", "doi"]
                    }
                },
            }
        },
        generated_at=datetime(2026, 4, 14, tzinfo=UTC),
    )

    event = report["events"][0]
    assert event["canonical_key_status"] == "title_proxy"
    assert "doi" in event["required_field_gaps"]
    assert any(
        item["reason"] == "title_proxy_canonical_key"
        for item in report["daily_review_items"]
    )


def test_build_quality_report_trims_noisy_arxiv_label() -> None:
    source = Source(
        name="arXiv CS.AI",
        type="rss",
        url="https://export.arxiv.org/rss/cs.AI",
        content_type="preprint",
        info_purpose=["paper_release"],
    )
    category = CategoryConfig(
        category_name="research",
        display_name="Research",
        sources=[source],
        entities=[],
    )
    article = Paper(
        title="LABBench2",
        link="https://arxiv.org/abs/2604.09554",
        abstract=(
            "arXiv: 2604.09554v1 Announce Type: new Abstract: "
            "Benchmark details continue here."
        ),
        authors=[],
        published=datetime(2026, 4, 13, tzinfo=UTC),
        source="arXiv CS.AI",
        category="research",
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["paper_release"]},
                "event_models": {
                    "paper_release": {
                        "required_fields": ["paper_id", "title", "source_url"]
                    }
                },
            }
        },
        generated_at=datetime(2026, 4, 14, tzinfo=UTC),
    )

    event = report["events"][0]
    assert event["arxiv_id"] == "2604.09554v1"
    assert event["canonical_key"] == "paper:arxiv:2604.09554v1"


def test_citation_snapshot_uses_collected_at_for_freshness() -> None:
    source = Source(
        name="OpenAlex AI Citation Feed",
        type="openalex",
        url="https://api.openalex.org/works",
        content_type="citation_signal",
        info_purpose=["citation"],
        config={"event_model": "citation_snapshot"},
    )
    category = CategoryConfig(
        category_name="research",
        display_name="Research",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Older but high-impact paper",
        link="https://doi.org/10.1145/example",
        summary="DOI: 10.1145/example. Citation count: 1234.",
        published=datetime(2020, 1, 1, tzinfo=UTC),
        collected_at=datetime(2026, 4, 22, tzinfo=UTC),
        source="OpenAlex AI Citation Feed",
        category="research",
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["citation_snapshot"]},
                "freshness_sla": {"citation_snapshot_days": 14},
                "event_models": {
                    "citation_snapshot": {
                        "required_fields": ["paper_id", "citation_count", "source"]
                    }
                },
            }
        },
        generated_at=datetime(2026, 4, 23, tzinfo=UTC),
    )

    assert report["summary"]["fresh_sources"] == 1
    assert report["summary"]["citation_snapshot_events"] == 1
    assert report["summary"]["citation_count_present_count"] == 1
    assert report["sources"][0]["status"] == "fresh"


def test_disabled_source_preserves_skip_reason() -> None:
    source = Source(
        name="Broken RSS",
        type="rss",
        url="https://example.com/rss.xml",
        enabled=False,
        content_type="academic",
        config={
            "skip_reason": "Endpoint returned 404 during source audit.",
            "reenable_gate": "Add parser smoke test.",
        },
    )
    category = CategoryConfig(
        category_name="research",
        display_name="Research",
        sources=[source],
        entities=[],
    )

    report = build_quality_report(
        category=category,
        articles=[],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["paper_release"]}
            }
        },
        generated_at=datetime(2026, 4, 23, tzinfo=UTC),
    )

    assert report["summary"]["skipped_disabled_sources"] == 1
    assert report["sources"][0]["status"] == "skipped_disabled"
    assert report["sources"][0]["skip_reason"] == "Endpoint returned 404 during source audit."
