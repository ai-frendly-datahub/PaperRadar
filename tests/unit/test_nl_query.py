from __future__ import annotations

from paperradar.nl_query import NLQueryParser


def test_nl_query_parser_recent():
    """Test parsing recent query."""
    parser = NLQueryParser()
    result = parser.parse("Show me recent papers")

    assert "recent" in result["filters"]


def test_nl_query_parser_citations():
    """Test parsing citations query."""
    parser = NLQueryParser()
    result = parser.parse("Find highly cited papers")

    assert "citations" in result["filters"]


def test_nl_query_parser_no_filters():
    """Test parsing query with no filters."""
    parser = NLQueryParser()
    result = parser.parse("Random query")

    assert len(result["filters"]) == 0
