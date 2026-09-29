param([int]$Port = 18768, [string]$BindAddress = '127.0.0.1')
$ErrorActionPreference = 'Stop'
$deliveryRoot = $PSScriptRoot
Set-Location -LiteralPath $deliveryRoot
docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop (Linux containers) first.' }

foreach ($entry in Get-Content -LiteralPath (Join-Path $deliveryRoot 'SHA256SUMS') -Encoding UTF8) {
    $parts = $entry -split '  ', 2
    $checkedFile = [IO.Path]::GetFullPath((Join-Path $deliveryRoot $parts[1]))
    if (-not $checkedFile.StartsWith($deliveryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Invalid checksum path.'
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $checkedFile).Hash.ToLowerInvariant() -ne $parts[0]) {
        throw "Checksum mismatch: $($parts[1])"
    }
}
docker load -i (Join-Path $deliveryRoot 'dispatch-image.tar.gz')
if ($LASTEXITCODE -ne 0) { throw 'Dispatch image import failed.' }
$dispatchImage = (Get-Content -LiteralPath 'service/deploy/forecast-dispatch/.env.example' | Where-Object { $_.StartsWith('DISPATCH_IMAGE=') }) -replace '^DISPATCH_IMAGE=', ''
if (-not $dispatchImage) { throw 'Missing dispatch image tag.' }
$env:DISPATCH_IMAGE = $dispatchImage
$env:DISPATCH_PORT = [string]$Port
$env:DISPATCH_BIND = $BindAddress
docker compose --env-file service/deploy/forecast-dispatch/.env.example -f service/deploy/forecast-dispatch/compose.yaml up -d --no-build --pull never --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) { throw 'Service startup failed. Inspect docker compose logs.' }
Write-Host "Dashboard: http://127.0.0.1:$Port/dashboard/"
Write-Host "API: http://127.0.0.1:$Port/docs"
Write-Host "Unified compute: http://127.0.0.1:$Port/api/v1/fluxcast/compute"
