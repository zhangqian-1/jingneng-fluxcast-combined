from __future__ import annotations

from src.platform_config import (
    KNOWN_SOURCE_IDS,
    RENEWABLE_FARM_IDS,
    STATION_CODES,
    STATION_MEASUREMENT_POINTS,
    platform_point_name,
)


def test_measurement_schema_matches_every_explicit_platform_document_row() -> None:
    assert sum(len(points) for points in STATION_MEASUREMENT_POINTS.values()) == 19
    assert set(STATION_MEASUREMENT_POINTS) == set(STATION_CODES)
    assert STATION_MEASUREMENT_POINTS["JYRD"] == (
        "JYRD_LOADCTL:GTMWSEL1_1.OUT",
        "JYRD_LOADCTL:GTMWSEL1_2.OUT",
        "JYRD_30DCS01:FU101.PNT",
    )


def test_platform_point_name_only_replaces_periods() -> None:
    assert platform_point_name("JYRD_LOADCTL:GTMWSEL1_1.OUT") == "JYRD_LOADCTL:GTMWSEL1_1_OUT"
    assert platform_point_name("GARD_11MBY0100000BJ01XQ01") == "GARD_11MBY0100000BJ01XQ01"


def test_documented_source_ids_are_exact() -> None:
    assert KNOWN_SOURCE_IDS == {
        2: "JYRD",
        3: "JQRD",
        4: "JFRD",
        5: "GARD",
        6: "JXRD",
        7: "WLRD",
        8: "SZRD",
    }


def test_renewable_farm_ids_match_platform_document() -> None:
    assert RENEWABLE_FARM_IDS == (
        1,
        2,
        3,
        4,
        7,
        8,
        10,
        11,
        12,
        13,
        16,
        17,
        19,
        20,
        21,
        22,
        23,
        28,
        29,
    )
