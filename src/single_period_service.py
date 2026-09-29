"""Collect independent actual/forecast inputs; never substitute actuals for predictions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.errors import DispatchServiceError
from src.input_quality import write_work_log
from src.runtime_config import REPOSITORY_ROOT
from src.single_period_comparison import compare_plan
from src.single_period_models import STEP, ActualSnapshot, utc_time
from src.single_period_store import SinglePeriodStore


class SinglePeriodService:
    def __init__(self, path: Path, clock=None):
        self.horizon_steps = 1
        self.store = SinglePeriodStore(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.day_timezone = os.getenv("DISPATCH_DAY_TIMEZONE", "Asia/Shanghai")
        ZoneInfo(self.day_timezone)

    def _solve(self, inputs):
        worker = subprocess.run(
            [sys.executable, "-m", "src.single_period_worker"],
            input=json.dumps(
                {**inputs, "day_timezone": self.day_timezone, "horizon_steps": self.horizon_steps},
                allow_nan=False,
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=25,
            cwd=REPOSITORY_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if worker.returncode:
            raise RuntimeError(f"单断面求解进程失败: {worker.returncode}; {worker.stderr[-2000:]}")
        response = json.loads(worker.stdout)
        if "error" in response:
            raise DispatchServiceError(**response["error"])
        return response["result"]

    def submit(self, kind, model):
        if kind != "actuals" and len(model.frames) != self.horizon_steps:
            raise DispatchServiceError(422, "HORIZON_MISMATCH", "输入时段数与当前服务模式不一致")
        with self.store.connection() as db:
            if kind == "actuals":
                if model.timestamp > self.clock() or self.clock() >= model.timestamp + STEP:
                    raise DispatchServiceError(
                        409, "ACTUAL_TIME_INVALID", "实际断面尚未到达或下一计划生效时间已过"
                    )
                other = self.store.latest_actual(db, model.snapshot_id)
                if other:
                    previous = ActualSnapshot.model_validate(other)
                    if previous.timestamp >= model.timestamp:
                        raise DispatchServiceError(
                            409, "ACTUAL_OUT_OF_ORDER", "不接受旧断面或同一时刻的另一编号"
                        )
                self._check_current_state(model)
                history = self.store.latest_actual(db, model.snapshot_id, with_state=True)
                if history:
                    self._check_history(ActualSnapshot.model_validate(history), model)
            elif model.issued_at > self.clock():
                raise DispatchServiceError(
                    422, "FORECAST_FROM_FUTURE", "预测发布时间晚于服务当前时间"
                )
            created = self.store.put(db, kind, model.model_dump(mode="json"))
            inputs = self.store.inputs(db, model.snapshot_id)
            if "actuals" in inputs:
                actual = ActualSnapshot.model_validate(inputs["actuals"])
                for name in ("renewable_forecast", "demand_forecast"):
                    if (
                        name in inputs
                        and utc_time(inputs[name]["frames"][0]["timestamp"])
                        != actual.timestamp + STEP
                    ):
                        raise DispatchServiceError(
                            422, "FORECAST_TIME_MISMATCH", "预测首时段必须为实际断面后的15分钟边界"
                        )
            if created:
                write_work_log(
                    {
                        "stage": "single_period_input",
                        "action": "received",
                        "snapshot_id": model.snapshot_id,
                        "kind": kind,
                    }
                )
            result = self._status(db, model.snapshot_id)
            if kind == "reference_plan" and created and result["status"] == "completed":
                archive = self.store.result(db, model.snapshot_id)
                self._compare(inputs, archive)
                self.store.update_comparison(db, model.snapshot_id, archive)
                return self._status(db, model.snapshot_id)
            if result["status"] != "waiting_inputs" or result["missing_inputs"]:
                return result
            if self.clock() >= actual.timestamp + STEP:
                raise DispatchServiceError(
                    409, "SINGLE_PERIOD_DEADLINE_PASSED", "本轮计划生效时刻已过，等待新实际断面"
                )
            event = {"stage": "single_period_dispatch", "snapshot_id": model.snapshot_id}
            write_work_log({**event, "action": "started"})
            try:
                solved = self._solve(inputs)
            except Exception as exc:
                write_work_log({**event, "action": "failed", "reason": str(exc)})
                failure = {
                    **result,
                    "status": "failed",
                    "http_status": exc.http_status
                    if isinstance(exc, DispatchServiceError)
                    else 503,
                    "error_code": exc.error_code
                    if isinstance(exc, DispatchServiceError)
                    else "SINGLE_PERIOD_SOLVE_FAILED",
                    "detail": exc.detail
                    if isinstance(exc, DispatchServiceError)
                    else "单断面优化未获得有效可行解，请检查工作日志",
                }
                self.store.save_failure(db, model.snapshot_id, failure)
                return failure
            if self.clock() >= actual.timestamp + STEP:
                write_work_log({**event, "action": "expired_after_solve"})
                raise DispatchServiceError(
                    409, "SINGLE_PERIOD_DEADLINE_PASSED", "计算完成时生效时刻已过，不发布过期建议"
                )
            archive = {
                **result,
                **solved,
                "status": "completed",
                "missing_inputs": [],
                "generated_at": self.clock().isoformat(),
                "actual": inputs["actuals"],
                "business_timezone": self.day_timezone,
                "forecast_ids": {
                    k: inputs[k]["forecast_id"] for k in ("renewable_forecast", "demand_forecast")
                },
            }
            self._compare(inputs, archive)
            if self.clock() >= actual.timestamp + STEP:
                write_work_log({**event, "action": "expired_before_publication"})
                raise DispatchServiceError(
                    409, "SINGLE_PERIOD_DEADLINE_PASSED", "核算完成时生效时刻已过，不发布过期建议"
                )
            archive["generated_at"] = self.clock().isoformat()
            self.store.save_result(db, model.snapshot_id, archive)
            write_work_log(
                {
                    **event,
                    "action": "completed",
                    "publish_steps": 1,
                    "horizon_steps": self.horizon_steps,
                }
            )
            return {k: v for k, v in archive.items() if k != "_audit"}

    def _compare(self, inputs, archive):
        plan = inputs.get("reference_plan")
        if plan is None:
            archive["comparison"] = {"status": "not_provided"}
            return
        try:
            archive["comparison"] = compare_plan(plan, inputs, archive)
        except ValueError as exc:
            archive["comparison"] = {
                "status": "unavailable",
                "plan_id": plan["plan_id"],
                "reason": str(exc),
            }
        write_work_log(
            {
                "stage": "single_period_comparison",
                "snapshot_id": archive["snapshot_id"],
                "action": archive["comparison"]["status"],
                "plan_id": plan["plan_id"],
                "reason": archive["comparison"].get("reason", ""),
            }
        )

    def _check_current_state(self, actual):
        if actual.thermal_state is None:
            return
        zone = ZoneInfo(self.day_timezone)
        today = actual.timestamp.astimezone(zone).date()
        for state in actual.thermal_state.values():
            if state.state_since.astimezone(zone).date() == today:
                observed_count = state.starts_today if state.running else state.stops_today
                if observed_count < 1:
                    raise DispatchServiceError(
                        422, "STATE_HISTORY_CONFLICT", "当日状态切换必须计入当日启停次数"
                    )

    def _check_history(self, previous, actual):
        if previous.thermal_state is None or actual.thermal_state is None:
            return
        zone = ZoneInfo(self.day_timezone)
        same_day = (
            previous.timestamp.astimezone(zone).date() == actual.timestamp.astimezone(zone).date()
        )
        for code, current in actual.thermal_state.items():
            old = previous.thermal_state[code]
            if current.state_since < old.state_since:
                raise DispatchServiceError(
                    422, "STATE_HISTORY_CONFLICT", "运行状态开始时间不得倒退"
                )
            transitioned = current.running != old.running or current.state_since != old.state_since
            if transitioned and current.state_since <= previous.timestamp:
                raise DispatchServiceError(
                    422, "STATE_HISTORY_CONFLICT", "状态切换时间与上一实际断面矛盾"
                )
            if same_day:
                minimum_starts = old.starts_today + int(current.running and not old.running)
                minimum_stops = old.stops_today + int(old.running and not current.running)
                # Same final state with a new start time implies at least a full cycle.
                if transitioned and current.running == old.running:
                    minimum_starts += 1
                    minimum_stops += 1
                if current.starts_today < minimum_starts or current.stops_today < minimum_stops:
                    raise DispatchServiceError(
                        422, "STATE_HISTORY_CONFLICT", "同一运行日启停计数不得清零或遗漏已发生切换"
                    )

    def status(self, snapshot_id):
        with self.store.connection() as db:
            return self._status(db, snapshot_id)

    def _status(self, db, snapshot_id):
        inputs = self.store.inputs(db, snapshot_id)
        missing = [
            kind
            for kind in ("actuals", "renewable_forecast", "demand_forecast")
            if kind not in inputs
        ]
        actual = ActualSnapshot.model_validate(inputs["actuals"]) if "actuals" in inputs else None
        if actual and actual.thermal_state is None:
            missing.append("thermal_state")
        result = {
            "status": "waiting_inputs",
            "snapshot_id": snapshot_id,
            "missing_inputs": missing,
            "step_minutes": 15,
            "horizon_steps": self.horizon_steps,
            "publish_steps": 1,
        }
        if actual:
            result["effective_at"] = (actual.timestamp + STEP).isoformat()
            other = self.store.latest_actual(db, snapshot_id)
            if other and utc_time(other["timestamp"]) > actual.timestamp:
                return {**result, "status": "superseded"}
        saved = self.store.result(db, snapshot_id)
        if saved:
            if saved.get("horizon_steps") != 1:
                raise DispatchServiceError(
                    503,
                    "SINGLE_PERIOD_DATABASE_MISMATCH",
                    "数据库包含旧优化模式，请使用单断面专用数据库",
                )
            if self.clock() >= utc_time(saved["valid_until"]):
                return {**result, "status": "expired"}
            return {k: v for k, v in saved.items() if k != "_audit"}
        if actual and self.clock() >= actual.timestamp + STEP:
            return {**result, "status": "expired"}
        failure = self.store.failure(db, snapshot_id)
        if failure:
            return failure
        return result
