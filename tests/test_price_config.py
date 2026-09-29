"""Price edits must be atomic, durable and unable to change an existing snapshot."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import api
from src.price_config import PRICE_FIELDS, PRICE_PATH
from src.single_period_store import SinglePeriodStore
from tests.test_platform_contract import platform_chain as platform_chain
from tests.test_platform_contract import platform_payload
from tests.test_single_forecast_bridge import prediction


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SINGLE_PERIOD_DB_PATH", str(tmp_path / "prices.sqlite3"))
    return TestClient(api.app, raise_server_exceptions=False)


def update_of(current):
    return {"expected_version": current["version"], "stations": deepcopy(current["stations"])}


def test_read_write_noop_and_stale_edit(client):
    response = client.get(PRICE_PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    before = response.json()
    assert before["version"] == 0 and before["updated_at"] is None
    assert len(before["stations"]) == 7
    assert all(set(s) == {"code", *PRICE_FIELDS} for s in before["stations"])
    same = update_of(before)
    same["stations"].reverse()
    assert client.put(PRICE_PATH, json=same).json() == before
    changed = update_of(before)
    changed["stations"][0]["gen_cost_yuan_per_kwh"] += 0.1
    response = client.put(PRICE_PATH, json=changed)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["version"] == 1 and after["updated_at"].endswith("Z")
    assert after["stations"] == changed["stations"]
    assert client.get(PRICE_PATH).json() == after
    stale = client.put(PRICE_PATH, json=changed)
    assert stale.status_code == 409
    assert stale.json()["current_version"] == 1
    assert set(stale.json()) == {"error_code", "detail", "current_version"}
    assert client.get(PRICE_PATH).json() == after


@pytest.mark.parametrize("value", [True, False, "0.5", None, 0, -1])
def test_invalid_numeric_values_do_not_partially_save(client, value):
    before = client.get(PRICE_PATH).json()
    changed = update_of(before)
    changed["stations"][0]["gen_cost_yuan_per_kwh"] = 0.55
    changed["stations"][-1]["buy_price_yuan_per_kwh"] = value
    response = client.put(PRICE_PATH, json=changed)
    assert response.status_code == 422, response.text
    assert set(response.json()) == {"error_code", "detail"}
    assert client.get(PRICE_PATH).json() == before


@pytest.mark.parametrize(
    "damage", ["gas", "missing", "duplicate", "unknown", "version_bool", "version_float"]
)
def test_only_fourteen_prices_and_valid_version_are_accepted(client, damage):
    before = client.get(PRICE_PATH).json()
    changed = update_of(before)
    if damage == "gas":
        changed["stations"][0]["gas_price_yuan_per_m3"] = 2.64
    elif damage == "missing":
        changed["stations"].pop()
    elif damage == "duplicate":
        changed["stations"][-1] = deepcopy(changed["stations"][0])
    elif damage == "unknown":
        changed["stations"][0]["code"] = "UNKNOWN"
    elif damage == "version_bool":
        changed["expected_version"] = False
    else:
        changed["expected_version"] = 0.0
    assert client.put(PRICE_PATH, json=changed).status_code == 422
    assert client.get(PRICE_PATH).json() == before


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_is_rejected(client, number):
    before = client.get(PRICE_PATH).json()
    body = json.dumps(update_of(before)).replace("0.48", number, 1)
    assert (
        client.put(
            PRICE_PATH, content=body, headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    assert client.get(PRICE_PATH).json() == before


def test_malformed_json_and_query_parameters(client):
    assert (
        client.put(
            PRICE_PATH, content="{", headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert client.get(PRICE_PATH + "?source_id=2").status_code == 422


def test_simultaneous_edits_cannot_overwrite_each_other(client):
    before = client.get(PRICE_PATH).json()
    requests = [update_of(before), update_of(before)]
    requests[0]["stations"][0]["gen_cost_yuan_per_kwh"] = 0.51
    requests[1]["stations"][0]["gen_cost_yuan_per_kwh"] = 0.52
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda body: client.put(PRICE_PATH, json=body), requests))
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert client.get(PRICE_PATH).json() == winner


def test_log_failure_rolls_back_edit(client, monkeypatch, tmp_path):
    before = client.get(PRICE_PATH).json()
    changed = update_of(before)
    changed["stations"][0]["gen_cost_yuan_per_kwh"] = 0.51
    monkeypatch.setenv("WORK_LOG_PATH", str(tmp_path))
    response = client.put(PRICE_PATH, json=changed)
    assert response.status_code == 503
    assert client.get(PRICE_PATH).json() == before


def test_upgrade_binds_existing_snapshots_to_default_version(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE rolling_input (snapshot_id TEXT, kind TEXT, body TEXT NOT NULL, "
            "PRIMARY KEY(snapshot_id,kind))"
        )
        db.execute("INSERT INTO rolling_input VALUES ('old', 'actuals', '{}')")
    store = SinglePeriodStore(path)
    with store.connection() as db:
        assert store.inputs(db, "old")["price_config"]["version"] == 0


def test_corrupt_saved_prices_are_not_replaced_with_defaults(client, tmp_path):
    assert client.get(PRICE_PATH).status_code == 200
    with sqlite3.connect(tmp_path / "prices.sqlite3") as db:
        db.execute("UPDATE price_overrides SET body='invalid-json' WHERE version=0")
    response = client.get(PRICE_PATH)
    assert response.status_code == 503
    assert response.json()["error_code"] == "PRICE_CONFIG_UNAVAILABLE"
    assert set(response.json()) == {"error_code", "detail"}


def test_new_price_applies_only_to_new_snapshot_and_real_solver(platform_chain, monkeypatch):
    client, upstream, bridge, now = platform_chain
    monkeypatch.setenv("SINGLE_PERIOD_DB_PATH", str(bridge.dispatch.store.path))
    before = client.get(PRICE_PATH).json()
    upstream.response = {
        "event_key": "JNH.Fluxcast.Compute",
        "result_point": [],
        "reason": "history_not_ready",
    }
    payload = platform_payload()
    assert client.post("/api/v1/fluxcast/compute", json=payload).status_code == 202
    changed = update_of(before)
    for station in changed["stations"]:
        station["gen_cost_yuan_per_kwh"] *= 2
        station["buy_price_yuan_per_kwh"] *= 3
    assert client.put(PRICE_PATH, json=changed).status_code == 200
    upstream.response = prediction()
    old = client.post("/api/v1/fluxcast/compute", json=payload)
    assert old.status_code == 200, old.text
    assert client.post("/api/v1/fluxcast/compute", json=payload).json() == old.json()
    with bridge.dispatch.store.connection() as db:
        saved_old = bridge.dispatch.store.result(db, "platform-20260921T100000Z")
    assert saved_old["price_version"] == 0
    next_stamp = now[0].replace(second=0) + timedelta(minutes=15)
    now[0] = next_stamp + timedelta(seconds=1)
    upstream.response["result_point"][0]["timestamp"] = (
        next_stamp + timedelta(minutes=15)
    ).isoformat()
    response = client.post("/api/v1/fluxcast/compute", json=platform_payload(next_stamp))
    assert response.status_code == 200, response.text
    with bridge.dispatch.store.connection() as db:
        saved_new = bridge.dispatch.store.result(db, "platform-20260921T101500Z")
    assert saved_new["price_version"] == 1
    expected = {s["code"]: s for s in changed["stations"]}
    for unit in saved_new["_audit"]["units"]:
        for key in PRICE_FIELDS:
            assert unit[key] == expected[unit["name"]][key]
    assert saved_new["step_metrics"]["objectiveYuan"] > saved_old["step_metrics"]["objectiveYuan"]
    # Reopening the service uses persisted configuration, not deployment defaults.
    reopened = SinglePeriodStore(bridge.dispatch.store.path)
    with reopened.connection() as db:
        assert reopened.inputs(db, "platform-20260921T100000Z")["price_config"]["version"] == 0
        assert reopened.inputs(db, "platform-20260921T101500Z")["price_config"]["version"] == 1
