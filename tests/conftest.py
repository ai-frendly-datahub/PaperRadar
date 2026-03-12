from __future__ import annotations

import pytest

from paperradar.logger import setup_logging


@pytest.fixture(scope="session", autouse=True)
def configure_test_logging() -> None:
    setup_logging()


@pytest.fixture(autouse=True)
def reconfigure_logging_per_test() -> None:
    setup_logging()
