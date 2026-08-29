"""Gradio iframe wrapper for the Three.js timeline scene.

Serves ui/scene.html (self-contained, CDN three.js) so it can live inside
app.py's Blocks page as an <iframe> and still use ES modules + import maps.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, PlainTextResponse
from starlette.routing import Route

UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"


def _file_response(name: str) -> FileResponse | PlainTextResponse:
    path = UI_DIR / name
    if not path.is_file():
        return PlainTextResponse("not found", status_code=404)
    media, _ = mimetypes.guess_type(path.name)
    return FileResponse(path, media_type=media or "text/plain", headers={"Cache-Control": "public, max-age=3600"})


async def _scene(request):
    return _file_response("scene.html")


async def _scene_js(request):
    return _file_response("timeline_scene.js")


async def _scene_css(request):
    return _file_response("scene.css")


routes = [
    Route("/scene", _scene, methods=["GET"]),
    Route("/scene/timeline_scene.js", _scene_js, methods=["GET"]),
    Route("/scene/scene.css", _scene_css, methods=["GET"]),
]

scene_app = Starlette(routes=routes)
