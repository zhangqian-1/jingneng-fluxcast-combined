from datetime import datetime, timedelta, timezone

from src.platform_config import RENEWABLE_FARM_IDS, STATION_CODES


def actual_payload():
    now = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    now = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    return {
        "snapshot_id": "measured-001",
        "timestamp": now.isoformat(),
        "thermal_mw": {code: 0.0 for code in STATION_CODES},
        "renewable_mw": {str(farm): 1.0 for farm in RENEWABLE_FARM_IDS},
    }


def complete_actual():
    payload = actual_payload()
    payload["thermal_state"] = {
        code: {
            "running": False,
            "state_since": "2026-09-20T00:00:00Z",
            "starts_today": 0,
            "stops_today": 0,
        }
        for code in STATION_CODES
    }
    return payload


def forecasts(actual):
    stamp = datetime.fromisoformat(actual["timestamp"].replace("Z", "+00:00"))
    common = {"snapshot_id": actual["snapshot_id"], "issued_at": stamp.isoformat()}
    return {
        kind: {
            **common,
            "forecast_id": kind + "-001",
            "frames": [
                {
                    "timestamp": (stamp + timedelta(minutes=15 * (n + 1))).isoformat(),
                    **(
                        {"demand_mw": 0.0}
                        if kind == "demand"
                        else {
                            "power_mw": dict.fromkeys(
                                map(str, RENEWABLE_FARM_IDS),
                                0.0,
                            )
                        }
                    ),
                }
                for n in range(1)
            ],
        }
        for kind in ("renewable", "demand")
    }
