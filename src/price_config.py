"""Versioned seven-station generation/purchase prices, bound once per snapshot."""

import json
from datetime import datetime, timezone
from typing import Annotated

from pydantic import Field, StrictInt, StrictStr, model_validator

from src.errors import DispatchServiceError
from src.platform_config import STATION_CODES
from src.runtime_config import REPOSITORY_ROOT
from src.single_period_models import StrictModel

PRICE_PATH = "/api/v1/fluxcast/config/prices"
PRICE_FIELDS = ("gen_cost_yuan_per_kwh", "buy_price_yuan_per_kwh")
PriceValue = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]


class StationPrice(StrictModel):
    code: StrictStr
    gen_cost_yuan_per_kwh: PriceValue
    buy_price_yuan_per_kwh: PriceValue


class PriceStations(StrictModel):
    stations: list[StationPrice] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def full_fleet(self):
        if {s.code for s in self.stations} != set(STATION_CODES):
            raise ValueError("必须完整覆盖七站，不得缺少、重复或增加未知场站")
        self.stations.sort(key=lambda s: STATION_CODES.index(s.code))
        return self


class PriceUpdate(PriceStations):
    expected_version: Annotated[StrictInt, Field(ge=0)]


class PriceSnapshot(PriceStations):
    version: Annotated[StrictInt, Field(ge=0)]
    updated_at: StrictStr | None


class PriceVersionConflict(DispatchServiceError):
    def __init__(self, version):
        super().__init__(409, "PRICE_VERSION_CONFLICT", "价格配置已更新，请重新读取并核对后保存")
        self.current_version = version


def initialize_prices(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS price_overrides "
        "(version INTEGER PRIMARY KEY, body TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS snapshot_prices "
        "(snapshot_id TEXT PRIMARY KEY, version INTEGER NOT NULL)"
    )
    if db.execute("SELECT 1 FROM price_overrides LIMIT 1").fetchone() is None:
        defaults = json.loads(
            (REPOSITORY_ROOT / "config/station_parameters.json").read_text("utf-8")
        )
        snapshot = PriceSnapshot(
            version=0,
            updated_at=None,
            stations=[
                {"code": s["code"], **{k: s[k] for k in PRICE_FIELDS}} for s in defaults["stations"]
            ],
        )
        db.execute("INSERT INTO price_overrides VALUES (0,?)", (snapshot.model_dump_json(),))
        # Upgrade existing pending/completed snapshots with their original defaults.
        db.execute(
            "INSERT OR IGNORE INTO snapshot_prices SELECT DISTINCT snapshot_id,0 FROM rolling_input"
        )


def current_prices(db):
    row = db.execute("SELECT body FROM price_overrides ORDER BY version DESC LIMIT 1").fetchone()
    return _decode_snapshot(row)


def _decode_snapshot(row):
    try:
        if row is None:
            raise ValueError("Missing price version")
        return PriceSnapshot.model_validate_json(row[0]).model_dump()
    except (ValueError, TypeError) as exc:
        raise DispatchServiceError(
            503, "PRICE_CONFIG_UNAVAILABLE", "已存价格配置缺失或不合法"
        ) from exc


def save_prices(db, update):
    current = current_prices(db)
    if update.expected_version != current["version"]:
        raise PriceVersionConflict(current["version"])
    stations = [s.model_dump() for s in update.stations]
    if stations == current["stations"]:
        return current
    saved = PriceSnapshot(
        version=current["version"] + 1,
        updated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        stations=stations,
    ).model_dump()
    db.execute(
        "INSERT INTO price_overrides VALUES (?,?)",
        (saved["version"], json.dumps(saved, allow_nan=False)),
    )
    return saved


def bind_prices(db, snapshot_id):
    db.execute(
        "INSERT OR IGNORE INTO snapshot_prices SELECT ?,MAX(version) FROM price_overrides",
        (snapshot_id,),
    )


def snapshot_prices(db, snapshot_id):
    row = db.execute(
        "SELECT p.body FROM snapshot_prices s JOIN price_overrides p "
        "ON p.version=s.version WHERE s.snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    return _decode_snapshot(row) if row else None
