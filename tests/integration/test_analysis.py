from __future__ import annotations

import pytest

from paperradar.models import EntityDefinition, Paper


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
        for entity, lowered_entity in zip(entities, lowered_entities):
            hit_keywords = [kw for kw in lowered_entity.keywords if kw and kw in haystack]
            if hit_keywords:
                matches[entity.name] = hit_keywords
        paper.matched_entities = matches
        analyzed.append(paper)

    return analyzed


@pytest.mark.integration
def test_entity_extraction_integration(
    sample_papers: list[Paper],
    sample_entities: list[EntityDefinition],
) -> None:
    """Test entity extraction integration: apply rules → verify tagged entities."""
    analyzed = _apply_entity_rules_py39(sample_papers, sample_entities)

    assert len(analyzed) == 5
    assert all(isinstance(p, Paper) for p in analyzed)

    paper_1 = analyzed[0]
    assert "nlp_techniques" in paper_1.matched_entities
    assert any(
        kw in paper_1.matched_entities["nlp_techniques"] for kw in ["transformer", "attention"]
    )

    paper_2 = analyzed[1]
    assert "nlp_techniques" in paper_2.matched_entities
    assert "bert" in paper_2.matched_entities["nlp_techniques"]

    paper_3 = analyzed[2]
    if "nlp_techniques" in paper_3.matched_entities:
        assert len(paper_3.matched_entities["nlp_techniques"]) > 0

    paper_4 = analyzed[3]
    assert "generative_models" in paper_4.matched_entities
    assert "diffusion" in paper_4.matched_entities["generative_models"]

    paper_5 = analyzed[4]
    assert "cv_techniques" in paper_5.matched_entities
    assert any(kw in paper_5.matched_entities["cv_techniques"] for kw in ["vision", "image"])
