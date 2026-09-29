param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260923-r2",
  "filename": "forecast-dispatch-20260923-r2.zip",
  "bytes": 823622284,
  "sha256": "65265640598c521bf67b81a4cc0e6b043c88c4a83c3e93222f73f5a31c4e4bcf",
  "parts": [
    {
      "name": "forecast-dispatch-20260923-r2.zip.001",
      "bytes": 67108864,
      "sha256": "3417bfd2e24953fde88f500d3e3fba6368300208f68e56fee4c9dc06a8835bbf"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.002",
      "bytes": 67108864,
      "sha256": "d4c162f894f91726b8c79175b1d637ecfbdb38c5612cb5aa4ec30853e0903bdb"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.003",
      "bytes": 67108864,
      "sha256": "b88af9115634c66ae8ba840d2c38f9f792cfc45aed27865756b4405059844f42"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.004",
      "bytes": 67108864,
      "sha256": "b71d85702df480da0c4c908634749c5fed580b43f7e22a59f84c22f7c60aaa63"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.005",
      "bytes": 67108864,
      "sha256": "7c594713b4ff7f925271da447d99647d4c19e322e5e2278c4c00a6cd484d59e1"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.006",
      "bytes": 67108864,
      "sha256": "15b31d16f04710d152f359d15f84a5c6028d1c3bac1cbbf5baf80f583aee27dd"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.007",
      "bytes": 67108864,
      "sha256": "c033287684439eefbf72a56d327381d9dcda919e982a170d6be8209345294661"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.008",
      "bytes": 67108864,
      "sha256": "51337bd6352383f61289101031a57dcfa9361e7f76611f1f4099b49e3a7aef38"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.009",
      "bytes": 67108864,
      "sha256": "f38dd51a92efabb407c02ef1e9f3b5df108add819f3cdcebf6d61b3f3c42d0d0"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.010",
      "bytes": 67108864,
      "sha256": "2c27d5a259b13c09f4b5bbb8998935d5916c9e4174114f3c813ca2a3ced42c8d"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.011",
      "bytes": 67108864,
      "sha256": "d3d4ed45877071c943e54833d1ede4008cd878b40fd6c0a96eb76bc26d9b679a"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.012",
      "bytes": 67108864,
      "sha256": "1bb4b92295519a6b7d6b2bcf76ef425ab6a5612df9ba5931ff82a69e185c8acb"
    },
    {
      "name": "forecast-dispatch-20260923-r2.zip.013",
      "bytes": 18315916,
      "sha256": "e1023cfd4754fa7af1ce4b07ab2e2b8fc0e92ed7ecd251b813cecd03bec14eaa"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260923-r2"
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
