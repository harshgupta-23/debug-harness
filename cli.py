#!/usr/bin/env python3
"""Convenience root CLI entrypoint for the Deterministic Code-Graph Harness."""

import sys
from pathlib import Path

# Add src to sys.path so it works out of the box
src_path = Path(__file__).resolve().parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from code_harness.cli import app

if __name__ == "__main__":
    app()
