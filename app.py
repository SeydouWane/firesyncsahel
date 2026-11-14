"""Entrypoint for serverless hosting (Vercel detects `app` in app.py).

Locally, use `python -m firesync serve` instead.
"""
from firesync.api.app import app  # noqa: F401
