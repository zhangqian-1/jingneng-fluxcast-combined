"""Immutable inputs and one published step per actual snapshot, persisted in SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.errors import DispatchServiceError
from src.price_config import bind_prices, initialize_prices, snapshot_prices
from src.single_period_models import utc_time


# SQLite table names are retained for existing single-period databases.
class SinglePeriodStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS rolling_input ("
                "snapshot_id TEXT, kind TEXT, body TEXT NOT NULL, "
                "PRIMARY KEY(snapshot_id, kind))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS rolling_result ("
                "snapshot_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS rolling_failure "
                "(snapshot_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS rolling_input_history "
                "(digest TEXT PRIMARY KEY, snapshot_id TEXT, kind TEXT, body TEXT NOT NULL)"
            )
            initialize_prices(db)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=35, isolation_level=None)
        try:
            # Across processes, serialize the input selection/solve/publication transaction.
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def put(db, kind, payload):
        snapshot_id = payload["snapshot_id"]
        body = json.dumps(payload, sort_keys=True, allow_nan=False)
        db.execute(
            "INSERT OR IGNORE INTO rolling_input_history VALUES (?, ?, ?, ?)",
            (hashlib.sha256(body.encode()).hexdigest(), snapshot_id, kind, body),
        )
        previous = db.execute(
            "SELECT body FROM rolling_input WHERE snapshot_id=? AND kind=?", (snapshot_id, kind)
        ).fetchone()
        if previous:
            if previous[0] != body:
                old = json.loads(previous[0])
                unpublished = SinglePeriodStore.result(db, snapshot_id) is None
                enrich_state = (
                    kind == "actuals"
                    and old.get("thermal_state") is None
                    and payload.get("thermal_state") is not None
                    and {k: v for k, v in old.items() if k != "thermal_state"}
                    == {k: v for k, v in payload.items() if k != "thermal_state"}
                )
                newer_forecast = (
                    kind.endswith("_forecast")
                    and old["forecast_id"] != payload["forecast_id"]
                    and utc_time(payload["issued_at"]) > utc_time(old["issued_at"])
                )
                if unpublished and (enrich_state or newer_forecast):
                    db.execute("DELETE FROM rolling_failure WHERE snapshot_id=?", (snapshot_id,))
                    db.execute(
                        "UPDATE rolling_input SET body=? WHERE snapshot_id=? AND kind=?",
                        (body, snapshot_id, kind),
                    )
                    return True
                raise DispatchServiceError(
                    409, "SINGLE_PERIOD_INPUT_CONFLICT", "同一断面的同类输入不可覆盖，请检查批次"
                )
            return False
        db.execute("INSERT INTO rolling_input VALUES (?, ?, ?)", (snapshot_id, kind, body))
        bind_prices(db, snapshot_id)
        return True

    @staticmethod
    def latest_actual(db, excluding, *, with_state=False):
        state_filter = "AND json_type(body, '$.thermal_state')='object' " if with_state else ""
        row = db.execute(
            "SELECT body FROM rolling_input WHERE kind='actuals' AND snapshot_id<>? "
            + state_filter
            + "ORDER BY json_extract(body, '$.timestamp') DESC LIMIT 1",
            (excluding,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def inputs(db, snapshot_id):
        result = {
            kind: json.loads(body)
            for kind, body in db.execute(
                "SELECT kind, body FROM rolling_input WHERE snapshot_id=?", (snapshot_id,)
            )
        }
        prices = snapshot_prices(db, snapshot_id)
        if result and prices is None:
            raise DispatchServiceError(503, "PRICE_CONFIG_UNAVAILABLE", "断面缺少绑定的价格版本")
        if prices is not None:
            result["price_config"] = prices
        return result

    @staticmethod
    def result(db, snapshot_id):
        row = db.execute(
            "SELECT body FROM rolling_result WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def save_result(db, snapshot_id, result):
        db.execute(
            "INSERT INTO rolling_result VALUES (?, ?)",
            (snapshot_id, json.dumps(result, allow_nan=False)),
        )

    @staticmethod
    def update_comparison(db, snapshot_id, result):
        db.execute(
            "UPDATE rolling_result SET body=? WHERE snapshot_id=?",
            (json.dumps(result, allow_nan=False), snapshot_id),
        )

    @staticmethod
    def failure(db, snapshot_id):
        row = db.execute(
            "SELECT body FROM rolling_failure WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def save_failure(db, snapshot_id, result):
        db.execute(
            "INSERT OR REPLACE INTO rolling_failure VALUES (?, ?)",
            (snapshot_id, json.dumps(result, allow_nan=False)),
        )
