from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.api.v1 import auth, devices, events, health, ingest, me, patients, reports
from backend.app.core.db import init_db

log = logging.getLogger("smartcane")


def create_app() -> FastAPI:
    app = FastAPI(title="Smart Cane API", version="0.1.0",
                  description="Prototype - not a medical device. Mobility trends only.")

    @app.on_event("startup")
    def _startup():
        init_db()

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException):
        d = exc.detail
        err = d if isinstance(d, dict) and "code" in d else {"code": f"http_{exc.status_code}", "message": str(d)}
        return JSONResponse({"error": err}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def val_exc(_: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Invalid request", "details": details}},
                            status_code=422)

    app.include_router(health.router)
    for r in (auth, me, patients, events, ingest, devices, reports, health):
        app.include_router(r.router, prefix="/v1")
    return app


app = create_app()
