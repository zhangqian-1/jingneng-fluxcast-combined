"""Raw measured power compared only with the published calendar-day forecast."""

from __future__ import annotations

import hashlib
import json
import math

from src.day_forecast_publication import BEIJING, DAY_VARNAME, curve_digest, validate_curve
from src.errors import DispatchServiceError
from src.forecast_bridge import EVENT_KEY
from src.platform_config import STATION_MEASUREMENT_POINTS
from src.single_period_models import STEP, utc_time

POINTS = tuple(point for points in STATION_MEASUREMENT_POINTS.values() for point in points)


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def measurement(frame):
    stamp = utc_time(frame["timestamp"])
    values = {point: finite_number(frame.get(point)) for point in POINTS}
    missing = [point for point, value in values.items() if value is None]
    status = (
        "complete" if not missing else "missing" if len(missing) == len(POINTS) else "incomplete"
    )
    total = None
    if not missing:
        try:
            total = math.fsum(values.values())
        except OverflowError:
            pass
        if total is not None and not math.isfinite(total):
            total = None
    return stamp, values, missing, status, total


class ActualPower:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS measured_power_result "
                "(target TEXT PRIMARY KEY, input_hash TEXT NOT NULL, "
                "batch_id TEXT, body TEXT NOT NULL)"
            )

    @staticmethod
    def _prediction(db, stamp):
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if (
            not {"day_forecast_publication", "day_forecast_curve", "day_forecast_provenance"}
            <= tables
        ):
            return None, None, None
        day = stamp.astimezone(BEIJING).date().isoformat()
        row = db.execute(
            "SELECT p.body, c.body, c.anchor, m.batch_id, m.available_at, p.anchor, m.source "
            "FROM day_forecast_publication p JOIN day_forecast_curve c ON p.day=c.day "
            "JOIN day_forecast_provenance m ON m.day=c.day WHERE p.day=?",
            (day,),
        ).fetchone()
        if not row:
            return None, None, None
        try:
            published, candidate = json.loads(row[0]), json.loads(row[1])
            if published != candidate or curve_digest(published) != row[3]:
                return None, None, None
            midnight = stamp.astimezone(BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
            if utc_time(row[2]) != midnight - STEP:
                return None, None, None
            basis = None
            if utc_time(row[4]) >= stamp:
                # Recovery excludes forecast-day inputs. Permit only the first
                # publication's observation, not retrospective history scoring.
                if row[6] != "recovery" or utc_time(row[5]) != stamp:
                    return None, None, None
                basis = "initial_curve_comparison"
            vendor_curve = {
                "event_key": EVENT_KEY,
                "result_point": [{**p, "varname": "totalPowerForecast"} for p in published],
            }
            if any(p["varname"] != DAY_VARNAME for p in published):
                return None, None, None
            checked, _ = validate_curve(vendor_curve, utc_time(row[2]))
            match = next(p for p in checked if utc_time(p["timestamp"]) == stamp)
            return match["value"], row[3], basis
        except (KeyError, TypeError, ValueError, OverflowError, StopIteration):
            return None, None, None

    def receive(self, frame):
        stamp, values, missing, status, total = measurement(frame)
        target = stamp.isoformat()
        digest = hashlib.sha256(
            json.dumps(values, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        with self.store.connection() as db:
            previous = db.execute(
                "SELECT input_hash, body FROM measured_power_result WHERE target=?", (target,)
            ).fetchone()
            if previous:
                if previous[0] != digest:
                    raise DispatchServiceError(
                        409, "ACTUAL_POWER_CONFLICT", "同一已发布时刻的实测不得覆盖"
                    )
                return json.loads(previous[1])

            def point(name, value):
                return {"varname": name, "timestamp": target, "value": value}

            numbers, info = [], [point("dataStatus", status)]
            prediction, batch, basis = self._prediction(db, stamp)
            if missing:
                info.append(point("missingPoints", ",".join(missing)))
            elif total is None:
                info.append(point("reason", "actual_out_of_range"))
            else:
                numbers.append(point("totalPowerActual", float(total)))
                if prediction is None:
                    info.append(point("reason", "no_matching_forecast"))
                elif math.isfinite(prediction - total):
                    numbers.append(point("totalPowerDeviation", float(prediction - total)))
                    if basis:
                        info.append(point("deviationBasis", basis))
                else:
                    info.append(point("reason", "deviation_out_of_range"))
            result = {"result_point": numbers, "extra_info": info}
            db.execute(
                "INSERT INTO measured_power_result VALUES (?, ?, ?, ?)",
                (target, digest, batch, json.dumps(result, allow_nan=False)),
            )
        return result
