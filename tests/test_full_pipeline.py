"""Unit tests for full_pipeline helpers."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ORDERING CRITICAL: import AIStock core before FinRL to prevent sys.path pollution
import config  # noqa: F401
import database  # noqa: F401
import repository  # noqa: F401


def test_placeholder():
    assert True
