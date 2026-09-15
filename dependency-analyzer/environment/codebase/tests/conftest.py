"""Shared test configuration and fixtures."""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_storage():
    """Provide a temporary storage path."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        yield d
