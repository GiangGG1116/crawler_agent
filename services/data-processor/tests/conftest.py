"""Pytest configuration for data-processor tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.main import app

    return TestClient(app)
