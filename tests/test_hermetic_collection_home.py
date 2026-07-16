"""Regression coverage for collection-time access to Hermes state.

Test modules and pytest plugins can import Hermes modules before autouse
fixtures run.  The collection process must therefore already have a sandboxed
HERMES_HOME; otherwise import-time caches can point at the live gateway config
and state database.
"""

import os
from pathlib import Path


COLLECTION_HERMES_HOME = Path(os.environ.get("HERMES_HOME", "")).resolve()
LIVE_HERMES_HOME = (Path.home() / ".hermes").resolve()


def test_collection_uses_sandboxed_hermes_home():
    assert COLLECTION_HERMES_HOME != LIVE_HERMES_HOME
    assert COLLECTION_HERMES_HOME.name.startswith("hermes-pytest-bootstrap-")
    assert COLLECTION_HERMES_HOME.is_dir()
