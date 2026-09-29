param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260929-r1",
  "filename": "forecast-dispatch-20260929-r1.zip",
  "bytes": 1266114607,
  "sha256": "67a0737a63319a5bc967fcaf2f933ba26cbd40533635d94b18c735562ca0b1e5",
  "source_commit": "868d63e7a47677aea818c2cc237bfc8b8c50a305",
  "image": "jingneng-fluxcast-all-in-one:868d63e",
  "image_id": "sha256:bb9b0b231946b81c05baa633ea426a08b681b5c9a9a32bc0d2e0e254c3108748",
  "parts": [
    {
      "name": "forecast-dispatch-20260929-r1.zip.001",
      "bytes": 67108864,
      "sha256": "f731efd256eddeb029d67bda48c3a825f89420fe9588ac2c6d9997c43795f0c5"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.002",
      "bytes": 67108864,
      "sha256": "7e8103e847f58885c839e3e19db75ca886ec519c8388237328fa7bedee06841e"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.003",
      "bytes": 67108864,
      "sha256": "f4579c0edd52855619c63e3760d4002365ce42c87f6fe82d45ae2b88dd0f4644"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.004",
      "bytes": 67108864,
      "sha256": "8cee0e7e0f7150013e76ea656b780faae1e2f79ba0496cb1561da7793fa1da56"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.005",
      "bytes": 67108864,
      "sha256": "e910c2ae132cd051b2ef0464cb6e1c2b5d41ba3d3f58b3807071bd742910abc4"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.006",
      "bytes": 67108864,
      "sha256": "04dcafdb1d49672ad9b62015340fc0c37a01bd85ce5096570aedd3060594a303"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.007",
      "bytes": 67108864,
      "sha256": "0bcb9d27b1a293505cbe0aad4569efb997c828e41b8578e37293991e199e8265"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.008",
      "bytes": 67108864,
      "sha256": "83f82a052996c281ae054145cccbe75ca10b6bb28ff6a86a42d59c8ee02eeff1"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.009",
      "bytes": 67108864,
      "sha256": "8c46f01f291741b12c9b10c8fcdf8b65152891d38162f7fdb26a410947df729f"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.010",
      "bytes": 67108864,
      "sha256": "32107dccd10116b993be8d5a660e38a5276dd9f96c37ef6b0755c469285be954"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.011",
      "bytes": 67108864,
      "sha256": "62c369b675767c84fb5139869904d2ae965004cf6486d36a56a7d3b8489ee7d8"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.012",
      "bytes": 67108864,
      "sha256": "8d80883ec131c14ad4e6f9e072afcda033ea743888b8f16d7946b93a16c40cd0"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.013",
      "bytes": 67108864,
      "sha256": "f528ed38aa2a57ff770d62078f13f5f04dd8b79c8c79816a18df4281d21ccb08"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.014",
      "bytes": 67108864,
      "sha256": "d0221cb6ccea99c3edf419a6ee9ad9bd0b6b8b5da4bd888afbeb7e720412dfa9"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.015",
      "bytes": 67108864,
      "sha256": "8374bc83c80328fa5303800d1bb10f2c1ebf346ac055d977949400203588d474"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.016",
      "bytes": 67108864,
      "sha256": "63973eaf5df1cb6567ed982aeed9995647ae854adabea5bd09f328b360318ffa"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.017",
      "bytes": 67108864,
      "sha256": "d370bec41c0f06109d620dc1a36b5746a9f13c2ff6d1e50492444acdda3435af"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.018",
      "bytes": 67108864,
      "sha256": "2f3b07933c19b0ba539c7864952ce4be2c40a2b141ed5e1b4dde73d578fced4a"
    },
    {
      "name": "forecast-dispatch-20260929-r1.zip.019",
      "bytes": 58155055,
      "sha256": "1644f0e2e5d28b759a2196942b48c227b03af2ac6f76b0e37823a169d5088f39"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260929-r1"
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
