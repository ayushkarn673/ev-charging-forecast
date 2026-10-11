"""
FastAPI prediction service (Phase 4) - historical replay of one-hour-ahead LSTM forecasts.

Run : uv run uvicorn api:app --host 127.0.0.1 --port 8000      (from ml-service/)
Docs: http://127.0.0.1:8000/docs

The model, scalers, feature metadata and observation store are loaded once at startup.
"""
from __future__ import annotations

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import logging  # noqa: E402
import re  # noqa: E402
from datetime import date  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from prediction_service import ForecastError, ForecastService  # noqa: E402
from schemas import ErrorResponse, HealthResponse, NextHourRequest, NextHourResponse  # noqa: E402

log = logging.getLogger("api")


def _camel(key: str) -> str:
    return re.sub(r"_([a-z0-9])", lambda m: m.group(1).upper(), key)


def camelize(obj):
    """Recursively convert dict keys to camelCase (for the metadata endpoints)."""
    if isinstance(obj, dict):
        return {_camel(k) if isinstance(k, str) else k: camelize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [camelize(v) for v in obj]
    return obj


def create_app(service: ForecastService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service if service is not None else ForecastService.from_files()
        log.info("Loaded %s with %d observation hours", app.state.service.model_info()["model_id"],
                 len(app.state.service.observations))
        yield

    app = FastAPI(
        title="EV Charging Demand Forecast API",
        version="1.0.0",
        description="One-hour-ahead LSTM utilization forecasts for the Caltech ACN site, served in "
                    "HISTORICAL REPLAY mode (ACN-Data, Nov 2018 - Feb 2020). Not live data.",
        lifespan=lifespan,
    )

    def get_service(request: Request) -> ForecastService:
        svc = getattr(request.app.state, "service", None)
        if svc is None:
            raise HTTPException(status_code=503, detail={"code": "MODEL_NOT_LOADED", "message": "model not loaded"})
        return svc

    @app.exception_handler(ForecastError)
    async def forecast_error_handler(_: Request, exc: ForecastError):
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    @app.get("/health", response_model=HealthResponse)
    def health(request: Request):
        svc = getattr(request.app.state, "service", None)
        return HealthResponse(
            status="ok" if svc is not None else "unavailable",
            model_loaded=svc is not None,
            model_id=svc.model_info()["model_id"] if svc else None,
            observations_loaded=len(svc.observations) if svc else 0,
            loaded_at_utc=svc.loaded_at_utc if svc else None,
        )

    @app.get("/model-info")
    def model_info(request: Request):
        return camelize(get_service(request).model_info())

    @app.get("/available-dates")
    def available_dates(request: Request):
        return camelize(get_service(request).available_dates())

    @app.get("/evaluation")
    def evaluation(request: Request):
        return camelize(get_service(request).evaluation_summary())

    @app.get("/evaluation/series")
    def evaluation_series(request: Request, start: date, end: date):
        return camelize(get_service(request).evaluation_series(start, end))

    @app.post("/predict/next-hour", response_model=NextHourResponse,
              responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
    def predict_next_hour(body: NextHourRequest, request: Request):
        return get_service(request).predict_next_hour(body.forecast_time, body.site_id)

    return app


app = create_app()
