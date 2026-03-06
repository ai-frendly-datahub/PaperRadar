from __future__ import annotations

from .models import EntityDefinition, Paper


def apply_entity_rules(papers: list[Paper], entities: list[EntityDefinition]) -> list[Paper]:
    """Match papers against entity keywords."""
    for paper in papers:
        matched: dict[str, list[str]] = {}
        
        text_to_search = (
            f"{paper.title} {paper.abstract} {' '.join(paper.authors)}"
        ).lower()
        
        for entity in entities:
            found = []
            for keyword in entity.keywords:
                if keyword.lower() in text_to_search:
                    found.append(keyword)
            
            if found:
                matched[entity.name] = list(set(found))
        
        paper.matched_entities = matched
    
    return papers
