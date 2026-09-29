"""Publish one complete Beijing calendar-day curve through the dispatch response."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from src.errors import DispatchServiceError
from src.forecast_bridge import EVENT_KEY
from src.input_quality import write_work_log
from src.single_period_models import STEP, utc_time

DAY_VARNAME = "totalPowerForecastDayAhead"
BEIJING = ZoneInfo("Asia/Shanghai")


def curve_digest(curve):
    encoded = json.dumps(curve, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate_curve(body, anchor):
    if body.get("event_key") != EVENT_KEY:
        raise ValueError("event_key")
    points = body.get("result_point")
    if points == [] and body.get("reason") in ("history_not_ready", "weather_history_not_ready"):
        return [], body["reason"]
    if not isinstance(points, list) or len(points) != 96:
        raise ValueError("96 points required")
    checked = []
    for n, point in enumerate(points):
        stamp = anchor + (n + 1) * STEP
        if (
            point["varname"] != "totalPowerForecast"
            or utc_time(point["timestamp"]) != stamp
            or type(point["value"]) not in (float, int)
            or not math.isfinite(point["value"])
            or point["value"] < 0
        ):
            raise ValueError("invalid prediction axis or value")
        checked.append(
            {"varname": DAY_VARNAME, "timestamp": stamp.isoformat(), "value": float(point["value"])}
        )
    return checked, "ready"


class DayForecastPublisher:
    def __init__(self, client, store, *, recovery=None, clock=None):
        self.client, self.store = client, store
        self.recovery = recovery
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS day_forecast_curve "
                "(day TEXT PRIMARY KEY, anchor TEXT NOT NULL, body TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS day_forecast_publication "
                "(day TEXT PRIMARY KEY, anchor TEXT NOT NULL, body TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS day_forecast_provenance "
                "(day TEXT PRIMARY KEY, batch_id TEXT NOT NULL, available_at TEXT NOT NULL, "
                "source TEXT NOT NULL)"
            )

    def _capture(self, day, cutoff, generate, source):
        # Keep generation and insertion under the existing cross-process transaction.
        # Old curves lacking provenance are never assigned a fabricated creation time.
        with self.store.connection() as db:
            if db.execute("SELECT 1 FROM day_forecast_curve WHERE day=?", (day,)).fetchone():
                return "ready"
            body = generate()
            if not body.get("result_point") and body.get("reason") in (
                "history_not_ready",
                "weather_history_not_ready",
                "recovery_history_not_ready",
                "recovery_weather_history_not_ready",
                "recovery_unavailable",
                "recovery_invalid_response",
            ):
                return body["reason"]
            try:
                curve, _ = validate_curve(body, cutoff)
                if not curve:
                    raise ValueError("Empty day curve")
                available = self.clock().astimezone(timezone.utc).isoformat()
                db.execute(
                    "INSERT INTO day_forecast_curve VALUES (?, ?, ?)",
                    (day, cutoff.isoformat(), json.dumps(curve, allow_nan=False)),
                )
                db.execute(
                    "INSERT INTO day_forecast_provenance VALUES (?, ?, ?, ?)",
                    (day, curve_digest(curve), available, source),
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                return "recovery_invalid_response" if source == "recovery" else "invalid_response"
        return "recovered" if source == "recovery" else "ready"

    def observe(self, request):
        anchor = utc_time(request["frames"][-1]["timestamp"])
        # Ingest all 35 points on every call; only the day boundary requests inference.
        try:
            status, body = self.client.ingest(request)
            if status != 200:
                raise DispatchServiceError(502, "DAY_FORECAST_UPSTREAM_ERROR", "全天预测服务未成功")
            model_status = body.get("reason")
            if (
                body.get("event_key") != EVENT_KEY
                or body.get("result_point") != []
                or model_status
                not in ("history_updated", "history_not_ready", "weather_history_not_ready")
            ):
                raise ValueError("Invalid history-only response")
            start = (anchor + STEP).astimezone(BEIJING)
            if model_status == "history_updated" and start.time() == time(0):

                def predict():
                    status, body = self.client.request(request)
                    if status != 200:
                        raise DispatchServiceError(
                            502, "DAY_FORECAST_UPSTREAM_ERROR", "全天预测服务未成功"
                        )
                    return body

                model_status = self._capture(start.date().isoformat(), anchor, predict, "midnight")
        except DispatchServiceError:
            model_status = "unavailable"
        except (KeyError, TypeError, ValueError, OverflowError):
            model_status = "invalid_response"
        if self.recovery is not None:
            local_start = anchor.astimezone(BEIJING).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day = local_start.date().isoformat()
            with self.store.connection() as db:
                exists = db.execute(
                    "SELECT 1 FROM day_forecast_curve WHERE day=?", (day,)
                ).fetchone()
            if not exists:
                model_status = self._recover(day, local_start - STEP)
        return model_status

    def _recover(self, day, cutoff):
        state = self._capture(
            day, cutoff.astimezone(timezone.utc), lambda: self.recovery.recover(day), "recovery"
        )
        write_work_log(
            {
                "stage": "day_forecast_recovery",
                "action": state,
                "day": day,
                "history_cutoff": cutoff.isoformat(),
            }
        )
        return state

    def process(self, request, *, successful, now, model_status=None):
        anchor = utc_time(request["frames"][-1]["timestamp"])
        local = anchor.astimezone(BEIJING)
        day, identity = local.date().isoformat(), anchor.isoformat()
        with self.store.connection() as db:
            published = db.execute(
                "SELECT anchor, body FROM day_forecast_publication WHERE day=?", (day,)
            ).fetchone()
        if successful and published and published[0] == identity:
            return json.loads(published[1]), "replayed"
        if model_status is None:
            model_status = self.observe(request)

        if not successful:
            result, state = [], "optimization_pending"
        elif published:
            result, state = [], "already_published"
        elif local.date() != now.astimezone(BEIJING).date():
            result, state = [], "outside_publication_day"
        elif anchor > now:
            result, state = [], "future_observation"
        else:
            # The transaction is the cross-process arbiter: at most one anchor
            # owns this day's batch. Replay the winner on response-loss retries.
            with self.store.connection() as db:
                existing = db.execute(
                    "SELECT anchor, body FROM day_forecast_publication WHERE day=?", (day,)
                ).fetchone()
                candidate = db.execute(
                    "SELECT body FROM day_forecast_curve WHERE day=?", (day,)
                ).fetchone()
                if existing:
                    result, state = (
                        (json.loads(existing[1]), "replayed")
                        if existing[0] == identity
                        else ([], "already_published")
                    )
                elif candidate:
                    db.execute(
                        "INSERT INTO day_forecast_publication VALUES (?, ?, ?)",
                        (day, identity, candidate[0]),
                    )
                    result, state = json.loads(candidate[0]), "published"
                else:
                    result, state = (
                        [],
                        "day_curve_missing"
                        if model_status in ("ready", "history_updated")
                        else model_status,
                    )
        write_work_log(
            {
                "stage": "day_forecast_publication",
                "action": state,
                "model_status": model_status,
                "day": day,
                "anchor": anchor.astimezone(timezone.utc).isoformat(),
                "points": len(result),
            }
        )
        return result, state
