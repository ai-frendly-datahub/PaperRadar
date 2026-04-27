from __future__ import annotations

import sys
from importlib import import_module


_MODULE_ALIASES = {
    "analyzer": "paperradar.analyzer",
    "collector": "paperradar.collector",
    "exceptions": "paperradar.exceptions",
    "models": "paperradar.models",
    "nl_query": "paperradar.nl_query",
    "reporter": "paperradar.reporter",
    "search_index": "radar_core.search_index",
    "storage": "paperradar.storage",
}

for _module_name, _target in _MODULE_ALIASES.items():
    sys.modules[f"{__name__}.{_module_name}"] = import_module(_target)


RadarStorage = import_module("paperradar.storage").RadarStorage


__all__ = ["RadarStorage"]
