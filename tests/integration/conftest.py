from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from paperradar.models import CategoryConfig, EntityDefinition, Paper, Source
from paperradar.storage import RadarStorage


@pytest.fixture
def tmp_storage(tmp_path: Path) -> RadarStorage:
    """Create a temporary RadarStorage instance for testing."""
    db_path = tmp_path / "test.duckdb"
    storage = RadarStorage(db_path)
    yield storage
    storage.close()


@pytest.fixture
def sample_papers() -> list[Paper]:
    """Create sample papers with realistic academic research data."""
    now = datetime.now(UTC)
    return [
        Paper(
            title="Attention Is All You Need",
            link="https://arxiv.org/abs/1706.03762",
            abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
            authors=["Vaswani, A.", "Shazeer, N.", "Parmar, N."],
            published=now,
            source="arXiv",
            category="research",
            arxiv_id="1706.03762",
            pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
            venue="NeurIPS",
            citation_count=50000,
            categories=["cs.CL", "cs.LG"],
            keywords=["transformer", "attention", "sequence-to-sequence"],
        ),
        Paper(
            title="BERT: Pre-training of Deep Bidirectional Transformers",
            link="https://arxiv.org/abs/1810.04805",
            abstract="We introduce BERT, a new method of pre-training language representations.",
            authors=["Devlin, J.", "Chang, M.", "Lee, K."],
            published=now,
            source="arXiv",
            category="research",
            arxiv_id="1810.04805",
            pdf_url="https://arxiv.org/pdf/1810.04805.pdf",
            venue="NAACL",
            citation_count=40000,
            categories=["cs.CL"],
            keywords=["BERT", "NLP", "pre-training"],
        ),
        Paper(
            title="Language Models are Unsupervised Multitask Learners",
            link="https://arxiv.org/abs/1902.10673",
            abstract="Natural language processing tasks are typically approached with supervised learning on task-specific datasets.",
            authors=["Radford, A.", "Wu, J.", "Child, R."],
            published=now,
            source="arXiv",
            category="research",
            arxiv_id="1902.10673",
            pdf_url="https://arxiv.org/pdf/1902.10673.pdf",
            venue="OpenAI",
            citation_count=35000,
            categories=["cs.CL"],
            keywords=["GPT", "language model", "multitask"],
        ),
        Paper(
            title="Denoising Diffusion Probabilistic Models",
            link="https://arxiv.org/abs/2006.11239",
            abstract="We present high quality image synthesis results using diffusion probabilistic models.",
            authors=["Ho, J.", "Jain, A.", "Abbeel, P."],
            published=now,
            source="arXiv",
            category="research",
            arxiv_id="2006.11239",
            pdf_url="https://arxiv.org/pdf/2006.11239.pdf",
            venue="NeurIPS",
            citation_count=8000,
            categories=["cs.CV", "cs.LG"],
            keywords=["diffusion", "generative", "image synthesis"],
        ),
        Paper(
            title="An Image is Worth 16x16 Words: Transformers for Image Recognition",
            link="https://arxiv.org/abs/2010.11929",
            abstract="While the Transformer architecture has become the de-facto standard for natural language processing tasks.",
            authors=["Dosovitskiy, A.", "Beyer, L.", "Kolesnikov, A."],
            published=now,
            source="arXiv",
            category="research",
            arxiv_id="2010.11929",
            pdf_url="https://arxiv.org/pdf/2010.11929.pdf",
            venue="ICLR",
            citation_count=12000,
            categories=["cs.CV"],
            keywords=["vision transformer", "ViT", "image classification"],
        ),
    ]


@pytest.fixture
def sample_entities() -> list[EntityDefinition]:
    """Create sample entities with academic research keywords."""
    return [
        EntityDefinition(
            name="nlp_techniques",
            display_name="NLP Techniques",
            keywords=["transformer", "BERT", "GPT", "attention", "NLP"],
        ),
        EntityDefinition(
            name="cv_techniques",
            display_name="Computer Vision",
            keywords=["vision", "image", "CNN", "ViT", "detection"],
        ),
        EntityDefinition(
            name="generative_models",
            display_name="Generative Models",
            keywords=["diffusion", "generative", "GAN", "VAE", "synthesis"],
        ),
        EntityDefinition(
            name="key_researchers",
            display_name="Key Researchers",
            keywords=["Hinton", "LeCun", "Bengio", "Vaswani", "Devlin"],
        ),
        EntityDefinition(
            name="venues",
            display_name="Top Venues",
            keywords=["NeurIPS", "ICML", "ICLR", "CVPR", "NAACL"],
        ),
    ]


@pytest.fixture
def sample_config(tmp_path: Path, sample_entities: list[EntityDefinition]) -> CategoryConfig:
    """Create a sample CategoryConfig for testing."""
    sources = [
        Source(
            name="arXiv",
            type="arxiv",
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI",
        ),
    ]
    return CategoryConfig(
        category_name="research",
        display_name="AI/ML Research Papers",
        sources=sources,
        entities=sample_entities,
    )
