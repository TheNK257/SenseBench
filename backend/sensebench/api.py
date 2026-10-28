"""HTTP API. Everything SenseBench serves goes through this one FastAPI app."""

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from sensebench import __version__
from sensebench.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="SenseBench", version=__version__)

    # Plain `def`: FastAPI runs it in the threadpool, so filesystem checks never block the loop.
    @app.get("/healthz")
    def healthz():
        problems = []
        if not settings.data_dir.is_dir():
            problems.append(f"data directory does not exist: {settings.data_dir}")
        elif not os.access(settings.data_dir, os.W_OK):
            problems.append(f"data directory is not writable: {settings.data_dir}")
        if problems:
            return JSONResponse({"status": "unhealthy", "problems": problems}, status_code=503)
        return {"status": "ok", "version": __version__}

    return app
