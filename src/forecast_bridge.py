"""HTTP-only adapter for the unmodified seven-station forecasting delivery."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from datetime import timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import Field, model_validator

from src.errors import DispatchServiceError
from src.input_quality import write_work_log
from src.single_period_models import (
    STEP,
    ActualSnapshot,
    SingleDemandForecast,
    SingleReferencePlan,
    SingleRenewableForecast,
    StrictModel,
    utc_time,
)

EVENT_KEY = "JNH.Fluxcast.Compute"
DEMAND_BASIS = "seven_station_power_forecast_as_equivalent_supply_target"
# Also serialize concurrent first requests before the cached factory has completed.
_FORECAST_LOCK = threading.RLock()
_BRIDGE_LOCK = threading.RLock()


class SingleComputePayload(StrictModel):
    actual: ActualSnapshot
    renewable_forecast: SingleRenewableForecast
    forecast_request: dict[str, Any] = Field(description="原预测接口请求，原字段及数值透传")
    reference_plan: SingleReferencePlan | None = None

    @model_validator(mode="after")
    def aligned(self):
        try:
            json.dumps(self.forecast_request, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("预测请求必须使用标准JSON，缺测值使用null") from exc
        if self.actual.thermal_state is None:
            raise ValueError("单断面优化必须提供七站真实运行状态及启停历史")
        try:
            expected = self.actual.timestamp + STEP
        except OverflowError as exc:
            raise ValueError("预测窗口超出支持的日期范围") from exc
        for item in (self.renewable_forecast, self.reference_plan):
            if item and (
                item.snapshot_id != self.actual.snapshot_id or item.frames[0].timestamp != expected
            ):
                raise ValueError("风光/原计划必须对应同一批次及实际断面后的15分钟时段")
        frames = self.forecast_request.get("frames")
        if not isinstance(frames, list) or len(frames) != 96:
            raise ValueError("原预测服务需要96帧历史，不是96帧未来输入")
        try:
            stamps = [utc_time(f["timestamp"]) for f in frames]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("预测历史时间格式无效") from exc
        try:
            expected_history = [self.actual.timestamp - (95 - i) * STEP for i in range(96)]
        except OverflowError as exc:
            raise ValueError("预测历史超出支持的日期范围") from exc
        if stamps != expected_history:
            raise ValueError("预测历史必须为连续升序的96帧，末点与本次实际断面一致")
        return self


class ForecastClient:
    def __init__(self, base_url: str, timeout=45):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
            raise ValueError("FORECAST_BASE_URL必须是固定配置的HTTP服务地址")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.lock = _FORECAST_LOCK

    def request(self, body=None):
        path = "/api/v1/fluxcast/compute" + ("/latest" if body is None else "")
        return self._request(path, body)

    def _request(self, path, body):
        try:
            data = (
                None
                if body is None
                else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            )
        except (ValueError, TypeError) as exc:
            raise DispatchServiceError(
                422, "INVALID_FORECAST_REQUEST", "预测请求必须是标准JSON"
            ) from exc
        request = Request(
            self.base_url + path, data=data, headers={"Content-Type": "application/json"}
        )
        with self.lock:
            try:
                try:
                    response = urlopen(request, timeout=self.timeout)
                except HTTPError as exc:
                    response = exc
                with response:
                    status = response.status
                    raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("oversized response")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("not a response object")
                json.dumps(result, allow_nan=False)
                return status, result
            except (URLError, TimeoutError, OSError) as exc:
                raise DispatchServiceError(502, "FORECAST_UNAVAILABLE", "预测服务暂不可用") from exc
            except (ValueError, UnicodeError) as exc:
                raise DispatchServiceError(
                    502, "FORECAST_RESPONSE_INVALID", "预测服务返回内容无效"
                ) from exc


class DayForecastClient(ForecastClient):
    def ingest(self, body):
        return self._request("/api/v1/fluxcast/history", body)


def select_target_prediction(response, actual):
    if response.get("event_key") != EVENT_KEY:
        raise DispatchServiceError(502, "FORECAST_CONTRACT_MISMATCH", "预测响应事件标识不匹配")
    points = response.get("result_point")
    if points == [] and response.get("reason") in (
        "history_not_ready",
        "weather_history_not_ready",
    ):
        return None
    if not isinstance(points, list) or len(points) != 1:
        raise DispatchServiceError(
            502, "FORECAST_INCOMPLETE", "单点预测必须恰好返回下一15分钟的1点，不能使用旧96点批次"
        )
    expected = actual.timestamp + STEP
    for i, point in enumerate(points):
        try:
            value = point["value"]
            valid = (
                point["varname"] == "totalPowerForecast"
                and utc_time(point["timestamp"]) == expected + i * STEP
                and not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise DispatchServiceError(
                502, "FORECAST_TIME_OR_VALUE_INVALID", "预测时间轴、测点或数值不匹配"
            )
    if points[0]["value"] < 0:
        raise DispatchServiceError(
            422, "NEGATIVE_SUPPLY_TARGET", "所选预测为负，不能作为非负供电目标；保留原值待核对"
        )
    return float(points[0]["value"])


class ForecastDispatchBridge:
    def __init__(self, client, dispatch):
        self.client = client
        self.dispatch = dispatch
        self.lock = _BRIDGE_LOCK

    def compute(self, payload):
        with self.lock:
            actual = payload.actual
            # Reuse the validated actual-state history, deduplication and publication deadline.
            result = self.dispatch.submit("actuals", actual)
            with self.dispatch.store.connection() as db:
                self.dispatch.store.put(
                    db,
                    "forecast_request",
                    {
                        "snapshot_id": actual.snapshot_id,
                        "request_sha256": hashlib.sha256(
                            json.dumps(
                                payload.forecast_request, sort_keys=True, allow_nan=False
                            ).encode()
                        ).hexdigest(),
                    },
                )
            if payload.reference_plan:
                self.dispatch.submit("reference_plan", payload.reference_plan)
            result = self.dispatch.submit("renewable_forecast", payload.renewable_forecast)
            if result["status"] != "waiting_inputs":
                return self.status(actual.snapshot_id)
            status, response = self.client.request(payload.forecast_request)
            write_work_log(
                {
                    "stage": "forecast_bridge",
                    "snapshot_id": actual.snapshot_id,
                    "action": "upstream_response",
                    "http_status": status,
                    "reason": response.get("reason"),
                    "response_sha256": hashlib.sha256(
                        json.dumps(response, sort_keys=True, allow_nan=False).encode()
                    ).hexdigest(),
                }
            )
            if status != 200:
                raise DispatchServiceError(
                    502, "FORECAST_UPSTREAM_ERROR", f"预测服务返回HTTP {status}，未生成优化指令"
                )
            target = select_target_prediction(response, actual)
            if target is None:
                with self.dispatch.store.connection() as db:
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS single_forecast_wait "
                        "(snapshot_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
                    )
                    db.execute(
                        "INSERT OR REPLACE INTO single_forecast_wait VALUES (?, ?)",
                        (actual.snapshot_id, json.dumps(response, allow_nan=False)),
                    )
                return {
                    **result,
                    "status": "waiting_forecast",
                    "result_point": [],
                    "forecast_status": response,
                    "demand_basis": DEMAND_BASIS,
                }
            issued = self.dispatch.clock().astimezone(timezone.utc)
            if issued >= actual.timestamp + STEP:
                raise DispatchServiceError(
                    409, "FORECAST_DEADLINE_PASSED", "预测完成时目标时段已开始，等待新断面"
                )
            digest = hashlib.sha256(json.dumps(response, sort_keys=True).encode()).hexdigest()
            demand = SingleDemandForecast.model_validate(
                {
                    "snapshot_id": actual.snapshot_id,
                    "forecast_id": "external-" + digest,
                    "issued_at": issued,
                    "frames": [{"timestamp": actual.timestamp + STEP, "demand_mw": target}],
                }
            )
            with self.dispatch.store.connection() as db:
                self.dispatch.store.put(
                    db,
                    "forecast_origin",
                    {
                        "snapshot_id": actual.snapshot_id,
                        "demand_basis": DEMAND_BASIS,
                        "forecast_varname": "totalPowerForecast",
                        "selected_demand_mw": target,
                        "response_sha256": digest,
                    },
                )
            result = self.dispatch.submit("demand_forecast", demand)
            return self.status(actual.snapshot_id)

    def status(self, snapshot_id):
        result = self.dispatch.status(snapshot_id)
        with self.dispatch.store.connection() as db:
            origin = self.dispatch.store.inputs(db, snapshot_id).get("forecast_origin", {})
            if (
                result["status"] == "waiting_inputs"
                and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='single_forecast_wait'"
                ).fetchone()
            ):
                pending = db.execute(
                    "SELECT body FROM single_forecast_wait WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()
                if pending:
                    result = {
                        **result,
                        "status": "waiting_forecast",
                        "result_point": [],
                        "forecast_status": json.loads(pending[0]),
                    }
        return {**result, "demand_basis": DEMAND_BASIS, **origin}
