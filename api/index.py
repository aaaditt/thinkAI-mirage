"""Vercel entry point: exposes the FastAPI app as a serverless function.

Vercel serves the built frontend as static files and sends /api/* here.
Local runs do not use this file; see start.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402  (the path must be set first)

__all__ = ["app"]
