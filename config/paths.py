"""Stable paths for both source runs and a frozen Windows application."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "SelectionCopilot"
