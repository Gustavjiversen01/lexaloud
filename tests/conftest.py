"""Pytest configuration.

Ensures the readaloud package is importable from src/ without relying on
an editable install, and registers pytest-asyncio mode so tests don't need
explicit decorators for async fixtures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Put src/ on sys.path for test discovery.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Scrub PYTHONPATH pollution (e.g. ROS) for test runs.
os.environ.pop("PYTHONPATH", None)
