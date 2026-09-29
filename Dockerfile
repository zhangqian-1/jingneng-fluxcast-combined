ARG POWER_FORECAST_IMAGE=ghcr.io/zhangqian-1/jingneng-power-forecast:7station-single-step-v1-amd64-a9614ff30661-36149015922-1
ARG DAY_FORECAST_IMAGE=ghcr.io/zhangqian-1/jingneng-power-forecast-observations:7station-platform-v1-amd64-ba6d7d35b873-36563145280-1
FROM ${DAY_FORECAST_IMAGE} AS forecast_day
FROM ${POWER_FORECAST_IMAGE} AS runtime

USER root
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 \
    FORECAST_BASE_URL=http://127.0.0.1:8001 \
    DAY_FORECAST_BASE_URL=http://127.0.0.1:8002 \
    SINGLE_PERIOD_DB_PATH=/app/runtime/single-period.sqlite3 \
    WORK_LOG_PATH=/app/runtime/logs/work.jsonl

# Keep original prediction code/models byte-for-byte, with separate caches.
RUN mkdir -p /opt/forecast-single \
    && mv /app/app /app/models /app/requirements.txt /opt/forecast-single/ \
    && python -m venv --without-pip /opt/day-venv \
    && python -m pip install --no-cache-dir "uv==0.12.3"
COPY --from=forecast_day /app/app /opt/forecast-day/app
COPY --from=forecast_day /app/models /opt/forecast-day/models
COPY --from=forecast_day /app/requirements.txt /opt/forecast-day/requirements.txt
# Both predictor environments use CPython 3.11. Preserve the day model's packages,
# including its different SQLAlchemy/filelock versions, in its own environment.
COPY --from=forecast_day /usr/local/lib/python3.11/site-packages /opt/day-venv/lib/python3.11/site-packages

COPY pyproject.toml uv.lock ./
RUN uv sync --python /usr/local/bin/python --frozen --no-dev --no-install-project
COPY api.py start.sh ./
COPY src ./src
COPY config ./config
COPY data ./data
COPY dashboard ./dashboard
RUN uv sync --python /usr/local/bin/python --frozen --no-dev \
    && chmod 0755 start.sh \
    && chmod 0644 pyproject.toml uv.lock api.py \
    && chmod -R a+rX src config data dashboard /opt/forecast-single /opt/forecast-day \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/output /app/runtime /opt/forecast-single/runtime /opt/forecast-day/runtime \
    && chown -R app:app /app/output /app/runtime /opt/forecast-single/runtime /opt/forecast-day/runtime

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=15s --start-period=300s --retries=3 \
    CMD ["/app/.venv/bin/python", "-m", "src.container_runtime", "--healthcheck"]
CMD ["/app/.venv/bin/python", "-m", "src.container_runtime"]
