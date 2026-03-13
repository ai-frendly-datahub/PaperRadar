from __future__ import annotations

from pathlib import Path

import pytest

from paperradar.models import EntityDefinition, Paper
from paperradar.reporter import generate_report


def _apply_entity_rules_py39(papers: list[Paper], entities: list[EntityDefinition]) -> list[Paper]:
    """Apply entity rules (Python 3.9 compatible version)."""
    analyzed: list[Paper] = []
    lowered_entities = [
        EntityDefinition(
            name=e.name,
            display_name=e.display_name,
            keywords=[kw.lower() for kw in e.keywords],
        )
        for e in entities
    ]

    for paper in papers:
        haystack = f"{paper.title}\n{paper.abstract}".lower()
        matches: dict[str, list[str]] = {}
        for entity, lowered_entity in zip(entities, lowered_entities, strict=False):
            hit_keywords = [kw for kw in lowered_entity.keywords if kw and kw in haystack]
            if hit_keywords:
                matches[entity.name] = hit_keywords
        paper.matched_entities = matches
        analyzed.append(paper)

    return analyzed


@pytest.mark.integration
def test_report_generation(
    tmp_path: Path,
    sample_papers: list[Paper],
    sample_entities: list[EntityDefinition],
    sample_config,
) -> None:
    """Test report generation: generate HTML → verify file exists + contains expected content."""
    analyzed = _apply_entity_rules_py39(sample_papers, sample_entities)

    output_path = tmp_path / "report.html"
    stats = {"total_papers": len(analyzed), "sources": 1}

    result = generate_report(
        category=sample_config,
        articles=analyzed,
        output_path=output_path,
        stats=stats,
        errors=[],
    )

    assert result.exists()
    assert result.suffix == ".html"

    content = result.read_text(encoding="utf-8")
    assert "AI/ML Research Papers" in content
    assert "Attention Is All You Need" in content
    assert "BERT" in content
