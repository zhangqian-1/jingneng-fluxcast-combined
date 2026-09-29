"""Isolate the native HiGHS runtime from HTTP worker threads."""

import json
import sys

from src.errors import DispatchServiceError
from src.single_period_models import (
    ActualSnapshot,
    SingleDemandForecast,
    SingleRenewableForecast,
)
from src.single_period_solver import solve_single_period


def main():
    body = json.load(sys.stdin)
    try:
        result = solve_single_period(
            ActualSnapshot.model_validate(body["actuals"]),
            SingleRenewableForecast.model_validate(body["renewable_forecast"]),
            SingleDemandForecast.model_validate(body["demand_forecast"]),
            day_timezone=body["day_timezone"],
            price_config=body.get("price_config"),
        )
        print(json.dumps({"result": result}, allow_nan=False))
    except DispatchServiceError as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "http_status": exc.http_status,
                        "error_code": exc.error_code,
                        "detail": exc.detail,
                    }
                }
            )
        )


if __name__ == "__main__":
    main()
