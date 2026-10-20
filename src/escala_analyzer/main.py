"""Default entry point is authenticated SaaS; local mode is explicit."""

import logging

import uvicorn

from escala_analyzer.settings import Settings

settings = Settings()
if settings.mode == "local":
    from escala_analyzer.presentation.local import app
else:
    from escala_analyzer.api.factory import create_app

    app = create_app(settings)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("escala_analyzer.main:app", host="127.0.0.1", port=8000)
