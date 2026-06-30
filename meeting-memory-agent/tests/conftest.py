"""Pytest configuration for the nested project layout."""

from __future__ import annotations

import sys
from pathlib import Path


# WHAT THIS DOES: Adds the project package directory to sys.path for test imports.
# WHY THIS WAY: The repository nests the actual Python package inside meeting-memory-agent/,
# so pytest needs that directory on the import path to resolve ingestion/security modules.
# SECURITY NOTE: This only changes the local test process import path; it does not affect runtime code.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
