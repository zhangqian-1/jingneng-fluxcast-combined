"""Public entry point: original prediction followed by one-period optimization."""

from __future__ import annotations

import logging
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.actual_power import ActualPower
from src.day_forecast_publication import DayForecastPublisher
from src.day_forecast_recovery import DayForecastRecovery
from src.errors import DispatchServiceError
from src.forecast_bridge import (
    EVENT_KEY,
    DayForecastClient,
    ForecastClient,
    ForecastDispatchBridge,
    SingleComputePayload,
)
from src.input_quality import WorkLogError, write_work_log
from src.platform_adapter import PlatformComputePayload, _output_timestamp, compute_platform
from src.price_config import (
    PRICE_PATH,
    PriceSnapshot,
    PriceUpdate,
    PriceVersionConflict,
    current_prices,
    save_prices,
)
from src.runtime_config import REPOSITORY_ROOT, output_directory
from src.single_period_models import Identifier
from src.single_period_service import SinglePeriodService
from src.single_period_store import SinglePeriodStore

logger = logging.getLogger(__name__)
app = FastAPI(
    title="JN Forecast + Single-period Dispatch",
    version="0.2.2",
    description="Seven-station prediction + one 15-minute optimization; 27 power targets.",
)
app.mount(
    "/dashboard", StaticFiles(directory=REPOSITORY_ROOT / "dashboard", html=True), name="dashboard"
)


def _error_response(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error_code": code,
            "detail": detail,
            "event_key": EVENT_KEY,
            "result_point": [],
            "extra_info": [],
        },
    )


@app.exception_handler(WorkLogError)
async def work_log_error_handler(request: Request, exc: WorkLogError) -> JSONResponse:
    if request.url.path == PRICE_PATH:
        return _price_error(503, "PRICE_CONFIG_UNAVAILABLE", "价格操作日志不可用，未保存修改")
    return _error_response(503, "WORK_LOG_UNAVAILABLE", "工作日志无法写入，请检查日志目录权限")


def _logged_error_response(exc: DispatchServiceError) -> JSONResponse:
    try:
        write_work_log(
            {"stage": "single_period_request", "action": "rejected", "error_code": exc.error_code}
        )
    except WorkLogError:
        return _error_response(503, "WORK_LOG_UNAVAILABLE", "工作日志无法写入，请检查日志目录权限")
    return _error_response(exc.http_status, exc.error_code, exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    malformed = any(e.get("type") == "json_invalid" for e in exc.errors())
    if request.url.path == PRICE_PATH:
        fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
        return _price_error(
            400 if malformed else 422,
            "INVALID_JSON" if malformed else "PRICE_VALIDATION_ERROR",
            "请求JSON无法解析" if malformed else "价格字段不符合约定: " + ", ".join(fields),
        )
    return _logged_error_response(
        DispatchServiceError(
            400 if malformed else 422,
            "INVALID_JSON" if malformed else "REQUEST_VALIDATION_ERROR",
            "请求JSON无法解析" if malformed else "请求字段不符合接口约定",
        )
    )


@app.exception_handler(DispatchServiceError)
async def dispatch_error_handler(request: Request, exc: DispatchServiceError) -> JSONResponse:
    if request.url.path == PRICE_PATH:
        response = _price_error(exc.http_status, exc.error_code, exc.detail)
        if isinstance(exc, PriceVersionConflict):
            return JSONResponse(
                status_code=409,
                content={
                    "error_code": exc.error_code,
                    "detail": exc.detail,
                    "current_version": exc.current_version,
                },
            )
        return response
    return _logged_error_response(exc)


@app.exception_handler(sqlite3.Error)
async def storage_error_handler(request: Request, exc: sqlite3.Error) -> JSONResponse:
    logger.error("Single-period storage failed", exc_info=exc)
    if request.url.path == PRICE_PATH:
        return _price_error(503, "PRICE_CONFIG_UNAVAILABLE", "价格配置存储不可用")
    return _logged_error_response(
        DispatchServiceError(503, "SINGLE_PERIOD_STORAGE_ERROR", "单断面存储暂不可用")
    )


def _price_error(status, code, detail):
    return JSONResponse(status_code=status, content={"error_code": code, "detail": detail})


def _price_store(request):
    if request.query_params:
        raise DispatchServiceError(422, "PRICE_VALIDATION_ERROR", "价格接口不接受查询参数")
    try:
        return SinglePeriodStore(
            Path(
                os.getenv(
                    "SINGLE_PERIOD_DB_PATH", str(output_directory() / "single-period.sqlite3")
                )
            )
        )
    except (OSError, ValueError) as exc:
        raise DispatchServiceError(503, "PRICE_CONFIG_UNAVAILABLE", "价格配置不可用") from exc


@app.get(PRICE_PATH, tags=["prices"], response_model=PriceSnapshot)
def get_prices(request: Request):
    with _price_store(request).connection() as db:
        result = current_prices(db)
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


@app.put(PRICE_PATH, tags=["prices"], response_model=PriceSnapshot)
def put_prices(payload: PriceUpdate, request: Request):
    with _price_store(request).connection() as db:
        result = save_prices(db, payload)
        write_work_log(
            {
                "stage": "price_config",
                "action": "validated_for_save",
                "expected_version": payload.expected_version,
                "result_version": result["version"],
            }
        )
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "jn-algorithm-fluxcast", "mode": "single_period"}


@lru_cache(maxsize=1)
def get_forecast_bridge() -> ForecastDispatchBridge:
    """Share the upstream lock and service across requests in this worker."""
    try:
        return ForecastDispatchBridge(
            ForecastClient(os.getenv("FORECAST_BASE_URL", "http://127.0.0.1:18769")),
            SinglePeriodService(
                Path(
                    os.getenv(
                        "SINGLE_PERIOD_DB_PATH", str(output_directory() / "single-period.sqlite3")
                    )
                )
            ),
        )
    except (OSError, sqlite3.Error, ZoneInfoNotFoundError, ValueError) as exc:
        logger.exception("Single-period service initialization failed")
        raise DispatchServiceError(
            503, "SINGLE_PERIOD_CONFIGURATION_ERROR", "单断面服务配置或存储不可用，请检查服务日志"
        ) from exc


@app.post("/api/v1/fluxcast/forecast/compute", tags=["forecast"])
def forecast_proxy(payload: dict[str, Any]) -> JSONResponse:
    bridge = get_forecast_bridge()
    with bridge.lock:
        status, result = bridge.client.request(payload)
        state = "not_accepted"
        if status == 200:
            _, state = _daily_points(payload, bridge, successful=False)
    return JSONResponse(result, status_code=status, headers={"X-Fluxcast-Day-Forecast": state})


@lru_cache(maxsize=1)
def get_day_forecast_client():
    return DayForecastClient(os.getenv("DAY_FORECAST_BASE_URL", "http://127.0.0.1:8002"))


@lru_cache(maxsize=1)
def get_day_forecast_recovery():
    return DayForecastRecovery()


def _daily_points(request, bridge, *, successful):
    client = get_day_forecast_client()
    if client is None:  # Explicit dependency injection for isolated optimizer tests.
        return [], "disabled"
    return DayForecastPublisher(
        client,
        bridge.dispatch.store,
        recovery=get_day_forecast_recovery(),
        clock=bridge.dispatch.clock,
    ).process(request, successful=successful, now=bridge.dispatch.clock())


@app.get("/api/v1/fluxcast/forecast/latest", tags=["forecast"])
def forecast_latest() -> JSONResponse:
    status, result = get_forecast_bridge().client.request()
    return JSONResponse(result, status_code=status, headers={"Cache-Control": "no-store"})


@app.post("/api/v1/fluxcast/compute", tags=["platform"])
def platform_compute(payload: PlatformComputePayload, request: Request) -> JSONResponse:
    if "source_id" in request.query_params:
        raise DispatchServiceError(
            422, "FULL_FLEET_REQUIRED", "当前约定为全场站单次请求，不使用source_id逐站调用"
        )
    bridge = get_forecast_bridge()
    with bridge.lock:
        client = get_day_forecast_client()
        publisher = (
            DayForecastPublisher(
                client,
                bridge.dispatch.store,
                recovery=get_day_forecast_recovery(),
                clock=bridge.dispatch.clock,
            )
            if client
            else None
        )
        forecast_request = payload.forecast_request()
        # Complete forecast I/O before the solver's deadline validation, so a slow
        # day model cannot turn an on-time solve into a stale dispatch response.
        model_status = publisher.observe(forecast_request) if publisher else "disabled"
        status, body = compute_platform(payload, bridge)
        daily, state = (
            publisher.process(
                forecast_request,
                successful=status == 200,
                now=bridge.dispatch.clock(),
                model_status=model_status,
            )
            if publisher
            else ([], "disabled")
        )
        body["result_point"].extend(
            {
                **point,
                "timestamp": _output_timestamp(point["timestamp"], payload.frames[-1]["timestamp"]),
            }
            for point in daily
        )
        if status == 200:
            measured = ActualPower(bridge.dispatch.store).receive(forecast_request["frames"][-1])
            for field in ("result_point", "extra_info"):
                body[field].extend(
                    {
                        **point,
                        "timestamp": _output_timestamp(
                            point["timestamp"], payload.frames[-1]["timestamp"]
                        ),
                    }
                    for point in measured[field]
                )
    return JSONResponse(
        body,
        status_code=status,
        headers={"X-Fluxcast-Day-Forecast": state, "Cache-Control": "no-store"},
    )


@app.post("/api/v1/fluxcast/single-period/compute", tags=["single-period"], deprecated=True)
def single_period_compute(payload: SingleComputePayload) -> JSONResponse:
    result = get_forecast_bridge().compute(payload)
    status = 200 if result["status"] == "completed" else 202
    if result["status"] in ("expired", "superseded"):
        status = 409
    elif result["status"] == "failed":
        status = result["http_status"]
    return JSONResponse(result, status_code=status)


@app.get("/api/v1/fluxcast/single-period/status/{snapshot_id}", tags=["single-period"])
def single_period_status(snapshot_id: Identifier) -> JSONResponse:
    return JSONResponse(
        get_forecast_bridge().status(snapshot_id), headers={"Cache-Control": "no-store"}
    )
