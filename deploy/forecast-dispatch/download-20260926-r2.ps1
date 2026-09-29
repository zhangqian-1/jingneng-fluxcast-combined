param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260926-r2",
  "filename": "forecast-dispatch-20260926-r2.zip",
  "bytes": 822701595,
  "sha256": "e2fbc99bf9b846c088f6012fe3c48f34eb0570bb8c9198a52ce65f0d634d57ea",
  "source_commit": "aa5119ee63081cac2f4293822f24119d3698ddb3",
  "parts": [
    {
      "name": "forecast-dispatch-20260926-r2.zip.001",
      "bytes": 67108864,
      "sha256": "1ab6f2411832789a73e816bea3ffddbdd0f18b050eff84240f2f34f078322efa"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.002",
      "bytes": 67108864,
      "sha256": "00f92da18b79df66f2c1af6e180555db1ab49f9ea32857e206feec6862536938"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.003",
      "bytes": 67108864,
      "sha256": "3ff6a1ab73da0a06e4f80ec3bc327c17d02bebfc0d90faecc06d789c1af19b88"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.004",
      "bytes": 67108864,
      "sha256": "c8817d7933772d82954247b6b07248a5f33666922752b2f0d7017133138a3b54"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.005",
      "bytes": 67108864,
      "sha256": "77c67a94ae3b6213d50fd61ce02fd121b7399aa305f0a2adc4eff3cb9e5c9396"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.006",
      "bytes": 67108864,
      "sha256": "1d2ad44ad54c8dc83ad355b64ddc1f2ebbe6ac1d444916b9a5b6e8500e149c66"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.007",
      "bytes": 67108864,
      "sha256": "674bd4fbc2aec3021ca4e968da8b12165cd580296c63205c30be8696f291f83d"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.008",
      "bytes": 67108864,
      "sha256": "9d7f2663cd7258d68c2d30b76717bd39b02deeb01cec5e15629b2829cb2d07c6"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.009",
      "bytes": 67108864,
      "sha256": "d3173fbe48cdd759546169abca37c6edb5d40a2f4a20d6f5e6381806fc2cfcfd"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.010",
      "bytes": 67108864,
      "sha256": "6f6a7380ff4cb3b3b2fd9d57cdd2f02b305ccc51cfdfd091513ba4abba21b82f"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.011",
      "bytes": 67108864,
      "sha256": "3b7f46c143d41a800bbd0941e400bf8178abf43973d3eff719af08d9084dbba1"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.012",
      "bytes": 67108864,
      "sha256": "123c1da67b7b85b7fee1e41e1d6a6a8d63f220ed6abf7cf64d4d9be866ea9a04"
    },
    {
      "name": "forecast-dispatch-20260926-r2.zip.013",
      "bytes": 17395227,
      "sha256": "7bf5c46a7bfcf0991b3d408b0a0e1f2b6a77e735139f17a49f0f77ebc41732ab"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260926-r2"
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
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing $($part.name). Download all 13 parts or use -Download." }
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
