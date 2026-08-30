"""Starlette host app for the MissMinutes field terminal.

Gradio mounts at "/" (app.py's __main__). The terminal is inline SVG —
no iframe, no CDN, no static scene routes remain.
"""
from __future__ import annotations

from starlette.applications import Starlette

routes: list = []

scene_app = Starlette(routes=routes)
