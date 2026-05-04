"""Project-wide pytest configuration."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add --run-integration flag to the pytest CLI.

    Args:
        parser: The pytest argument parser.
    """
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require real HTTP and SQLite resources.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration-marked tests unless --run-integration is passed.

    Args:
        config: The pytest configuration object.
        items: The collected test items.
    """
    if config.getoption("--run-integration"):
        return
    skip_marker = pytest.mark.skip(reason="pass --run-integration to run integration tests")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)
