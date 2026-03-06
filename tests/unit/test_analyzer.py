from __future__ import annotations

from datetime import datetime, timezone

from paperradar.analyzer import apply_entity_rules
from paperradar.models import EntityDefinition, Paper


def test_entity_matching():
    """Test entity matching in papers."""
    paper = Paper(
        title="Deep Learning with Transformers",
        link="https://example.com",
        abstract="This paper discusses transformer architectures and BERT models",
        authors=["John Doe"],
        published=datetime.now(timezone.utc),
        source="arXiv",
        category="research",
    )
    
    entities = [
        EntityDefinition(
            name="Techniques",
            display_name="Key Techniques",
            keywords=["transformer", "BERT", "GPT"],
        ),
    ]
    
    result = apply_entity_rules([paper], entities)
    
    assert len(result) == 1
    assert "Techniques" in result[0].matched_entities
    assert "transformer" in result[0].matched_entities["Techniques"]


def test_no_entity_match():
    """Test paper with no entity matches."""
    paper = Paper(
        title="Random Paper",
        link="https://example.com",
        abstract="This is about something else",
        authors=["Jane Doe"],
        published=datetime.now(timezone.utc),
        source="arXiv",
        category="research",
    )
    
    entities = [
        EntityDefinition(
            name="Techniques",
            display_name="Key Techniques",
            keywords=["transformer", "BERT"],
        ),
    ]
    
    result = apply_entity_rules([paper], entities)
    
    assert len(result[0].matched_entities) == 0
