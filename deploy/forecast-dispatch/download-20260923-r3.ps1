param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260923-r3",
  "filename": "forecast-dispatch-20260923-r3.zip",
  "bytes": 823785068,
  "sha256": "eb684cea22db087d05ce4faeb31dcf387ac07a0209cd5be8182e7082bcf70c11",
  "source_commit": "d1bbc85270c71f235aab2d8fd3997baa97263c29",
  "parts": [
    {
      "name": "forecast-dispatch-20260923-r3.zip.001",
      "bytes": 67108864,
      "sha256": "48e8adcd2f48546b4478ae04ac11d51cfda512ea4e995f7ec622f0f96d1e45d9"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.002",
      "bytes": 67108864,
      "sha256": "eee5e31d4eab62801d0ecf5d5dd09107694be83d48fed0c84b2556617c018257"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.003",
      "bytes": 67108864,
      "sha256": "2aa86f25f3e4783031388dcb944eb2fd26e2ef495a8960c24e469b965c5c4047"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.004",
      "bytes": 67108864,
      "sha256": "06226740b34a07224aec20ac09fcf15578acc3658d759758d270c22e54b21376"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.005",
      "bytes": 67108864,
      "sha256": "6dcf2d1b73527eda2a7a871ddd8e9a2add3d45801c7a1508fb8c435e9ce9a136"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.006",
      "bytes": 67108864,
      "sha256": "01d740e33da5c68eff0b9d86f94785ee33729476c729a8264c12b15e96a324f0"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.007",
      "bytes": 67108864,
      "sha256": "691b7903bf9204a2886f550728ff2d1daa0cb3efea11a926f8943a43ded0c62e"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.008",
      "bytes": 67108864,
      "sha256": "ef242ea249ebd98bfe0896e00a4bd54e702c6140343d73679549b5dd6b8f1ee6"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.009",
      "bytes": 67108864,
      "sha256": "d2cc8c8205f17ab29fe9ddf5c804dce0e3841d827eae74de78a11c646aa3d5e4"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.010",
      "bytes": 67108864,
      "sha256": "8e34a1aa12e6f2eb31c9442d4cf6693c2716cae4ec1d11f4fd3009c4d393514b"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.011",
      "bytes": 67108864,
      "sha256": "cdbcb02e92eb71a7f6699866a16964d3da14fe4ec406f68f3f2ae5c6adb9c6ca"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.012",
      "bytes": 67108864,
      "sha256": "8f75cde47ea22fa0026164ccf07c54e86dffc2bf3fef4207b3cafed2ec2aeba9"
    },
    {
      "name": "forecast-dispatch-20260923-r3.zip.013",
      "bytes": 18478700,
      "sha256": "52d12b6f9e8662c73a2dc3e99a30b1b21e76ea83ef26df75b8da4e9d2a70ba1b"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260923-r3"
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
