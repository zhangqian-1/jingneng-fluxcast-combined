param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260929-r5",
  "filename": "forecast-dispatch-20260929-r5.zip",
  "bytes": 1266158209,
  "sha256": "5584fa9d3135e288ec74002af3dff6f480aff77edca5c0c1cc8dc7a8f2141963",
  "source_commit": "8f931dc062911f5815cf620db064459ba28e543c",
  "image": "jingneng-fluxcast-all-in-one:20260929-r5",
  "image_id": "sha256:a6c600445b3761527f9d6e10cd42e10dbcd5a6a18da28cbfb99c12653c879d08",
  "parts": [
    {
      "name": "forecast-dispatch-20260929-r5.zip.001",
      "bytes": 67108864,
      "sha256": "fc60d6cc40c9c65474cfa47a4fd41b842afa025b5b057817e8fcb7631071f37d"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.002",
      "bytes": 67108864,
      "sha256": "8a70febd135fcc7f0387b2a5b27bf97b1b8f4cb7a2af8f3a2ebc7c245e09a2d8"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.003",
      "bytes": 67108864,
      "sha256": "9991e3b154c5bf3752bb8292a0fc5daf99739e0fdd0027d3e0ea2a59d8296066"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.004",
      "bytes": 67108864,
      "sha256": "ccbbf344209e0f0125edc86f3b02f7645318d900de0bd0248e2981c07719c5cf"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.005",
      "bytes": 67108864,
      "sha256": "259901cb2efc5d9b58a8e74b9aaf9fe89d25870adc712a2e3ea2c6baeea31dab"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.006",
      "bytes": 67108864,
      "sha256": "6f1eea9696dd1323040b2d60b936ad032504b3faef059db7af0f425b8342cc4c"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.007",
      "bytes": 67108864,
      "sha256": "651cf913caaa6f1f930c0ee37aee5967c66aa9343d0dc438d4dcd863ef18b9a9"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.008",
      "bytes": 67108864,
      "sha256": "6cd603e43269cff777f2228c642c852a2fe668063fccf37b95af3dee0f70d1b2"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.009",
      "bytes": 67108864,
      "sha256": "0ce7c0856610d9a7861fc278292569c564f4a1586567160592a97d8de483991e"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.010",
      "bytes": 67108864,
      "sha256": "d9f1e954d8aaa0cbb5d84cdc0bb719e22df5dbf02182d53cb2642214a7187e11"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.011",
      "bytes": 67108864,
      "sha256": "57c741a8c75f469dcb4a84b6c0e38ad9bbb69a7974d2c0f57b3229788e082fc0"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.012",
      "bytes": 67108864,
      "sha256": "0ac8d0be8124f6c9bf7473fe7b96ae0d12c97b8743b81a08887afade46c48688"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.013",
      "bytes": 67108864,
      "sha256": "58a2d2b216ef7de1bee7643dd4faff778d2c2d9123ba21a319d7aa1a4885c68a"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.014",
      "bytes": 67108864,
      "sha256": "88728882517edb49822514cd4c06c3587904196f47f6b1659c5e62beda55d4ec"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.015",
      "bytes": 67108864,
      "sha256": "57cdb1e728dbb814e08e5040dcea33d1dcb1e1caf9e5f0c41510c6bdd634ff37"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.016",
      "bytes": 67108864,
      "sha256": "a7f9abf5ce1384d55a2c7752bff208becf651d2c167145709b6f265e9af4a2c8"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.017",
      "bytes": 67108864,
      "sha256": "5e817de08b2ec6e525503d42620e2e0027f77b6991ffbe41696abe8636797597"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.018",
      "bytes": 67108864,
      "sha256": "6771f8cadd352be2f7b4dcb4cefa36b52daaa789f5a85dc0c65a252e9355e0f1"
    },
    {
      "name": "forecast-dispatch-20260929-r5.zip.019",
      "bytes": 58198657,
      "sha256": "02cf9ef449a0d66b672566ab206375253ef435c05702a58bfbe43f4eeed96480"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260929-r5"
$directory = [IO.Path]::GetFullPath($Destination)
if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory | Out-Null }
$target = Join-Path $directory $manifest.filename
if (Test-Path -LiteralPath $target) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant() -eq $manifest.sha256) {
        Write-Host "Already verified: $target"
        return
    }
    throw "Output already exists with a different hash: $target"
}
$missing = @($manifest.parts | Where-Object { -not (Test-Path -LiteralPath (Join-Path $directory $_.name)) })
if ($Download -and $missing.Count -gt 0) {
    if (-not $Credential) { $Credential = Get-Credential -Message "Sign in to GitLab at $origin" }
    if (-not $Credential) { throw 'GitLab credentials are required to download this private package.' }
    $page = Invoke-WebRequest -UseBasicParsing -Uri "$origin/users/sign_in" -SessionVariable gitlabSession
    $token = [regex]::Match($page.Content, 'name="authenticity_token"[^>]*value="([^"]+)"').Groups[1].Value
    if (-not $token) { throw 'GitLab sign-in form changed; download the parts in your browser.' }
    $fields = @{'authenticity_token'=$token; 'user[login]'=$Credential.UserName; 'user[password]'=$Credential.GetNetworkCredential().Password}
    try { Invoke-WebRequest -UseBasicParsing -Uri "$origin/users/sign_in" -Method Post -WebSession $gitlabSession -Body $fields | Out-Null }
    finally { $fields.Clear() }
    Invoke-RestMethod -Uri "$origin/api/v4/user" -WebSession $gitlabSession | Out-Null
    foreach ($part in $missing) {
        $path = Join-Path $directory $part.name
        $partial = "$path.download"
        if (Test-Path -LiteralPath $partial) { throw "Partial file exists; remove it before retrying: $partial" }
        Write-Host "Downloading $($part.name)"
        Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/$($part.name)" -WebSession $gitlabSession -OutFile $partial -TimeoutSec 180
        if ((Get-Item -LiteralPath $partial).Length -ne $part.bytes -or (Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant() -ne $part.sha256) { throw "Download checksum mismatch: $($part.name)" }
        Move-Item -LiteralPath $partial -Destination $path
    }
}
foreach ($part in $manifest.parts) {
    $path = Join-Path $directory $part.name
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing $($part.name). Download all 19 parts or use -Download." }
    if ((Get-Item -LiteralPath $path).Length -ne $part.bytes -or (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant() -ne $part.sha256) { throw "Part checksum mismatch: $($part.name)" }
}
$partial = "$target.assembling"
$stream = [IO.File]::Open($partial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    foreach ($part in $manifest.parts) {
        $partStream = [IO.File]::OpenRead((Join-Path $directory $part.name))
        try { $partStream.CopyTo($stream) } finally { $partStream.Dispose() }
    }
} finally { $stream.Dispose() }
if ((Get-Item -LiteralPath $partial).Length -ne $manifest.bytes -or (Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'Combined ZIP checksum mismatch.' }
Move-Item -LiteralPath $partial -Destination $target
Write-Host "Verified delivery: $target"
Write-Host "SHA256: $($manifest.sha256)"
Write-Host 'Extract the ZIP, then run start.ps1 (Windows) or sh start.sh (Linux).'
