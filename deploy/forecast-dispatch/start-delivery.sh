#!/bin/sh
set -eu
cd "$(dirname "$0")"

docker info --format '{{.OSType}}'
sha256sum -c SHA256SUMS
docker load -i dispatch-image.tar.gz
dispatch_image=$(sed -n 's/^DISPATCH_IMAGE=//p' service/deploy/forecast-dispatch/.env.example | tr -d '\r')
[ -n "$dispatch_image" ] || { printf 'Missing dispatch image tag\n' >&2; exit 1; }
export DISPATCH_IMAGE="$dispatch_image"
docker compose --env-file service/deploy/forecast-dispatch/.env.example -f service/deploy/forecast-dispatch/compose.yaml up -d --no-build --pull never --wait --wait-timeout 300
printf 'Dashboard: http://127.0.0.1:%s/dashboard/\n' "${DISPATCH_PORT:-18768}"
printf 'Unified compute: http://127.0.0.1:%s/api/v1/fluxcast/compute\n' "${DISPATCH_PORT:-18768}"
