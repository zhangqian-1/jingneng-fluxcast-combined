param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260929-r2",
  "filename": "forecast-dispatch-20260929-r2.zip",
  "bytes": 1266126545,
  "sha256": "d38354376394d53852e035558847513fa583b554aaa3a666ae64dab66343080e",
  "source_commit": "c9d09da927af437ad49df53e13323a9092b3889a",
  "image": "jingneng-fluxcast-all-in-one:20260929-r2",
  "image_id": "sha256:92606d0876096856f18be4d4b2bbd367613c72cd71177e0ffea1f9843043218b",
  "parts": [
    {
      "name": "forecast-dispatch-20260929-r2.zip.001",
      "bytes": 67108864,
      "sha256": "38a8ecc2dcd60d473612078c2a50b2f9b8f9aed8def9cf6721ac13fb7359b7b3"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.002",
      "bytes": 67108864,
      "sha256": "3c9e7b4857afe8872766167d7717996ba7c27ae96cadbcb90dd4fd8191335c3d"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.003",
      "bytes": 67108864,
      "sha256": "df1557ccc32d7046893aa00ae587684f9307202210c9f0706b492e9af88af6a5"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.004",
      "bytes": 67108864,
      "sha256": "70b8107e8c79cf5818281cb52371d4417eeaf55115227f738c5734bd4f440419"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.005",
      "bytes": 67108864,
      "sha256": "cb53b6e84969ed8d2db41c434990b5262b74de83f311f714c519ced4f2429a2b"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.006",
      "bytes": 67108864,
      "sha256": "336211d26aa2da46f22942aec34eb9f30945437a8cddaeb37ff69bb36e10d227"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.007",
      "bytes": 67108864,
      "sha256": "800dc2a228f446cd2e8d068e5a2f64c4d585f9bf5ab4876789daf9ce2f7bd6f8"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.008",
      "bytes": 67108864,
      "sha256": "17c742a3bfe3cf40faa1bfcc2ece44b44930518cdf80c44181230e77a71d0df2"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.009",
      "bytes": 67108864,
      "sha256": "6c6c05ba6fd8189ab637ecba2285af245da3259ddf709af30768a818c5923477"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.010",
      "bytes": 67108864,
      "sha256": "c7441ea1b8090fc3625664a1ea79126fa2ab0ebc631aa5fc45226322171f59b3"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.011",
      "bytes": 67108864,
      "sha256": "a89e6194746aee07ba7e719a498e3b4b49baa3e5d720d586b5fda2f0fb9d1034"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.012",
      "bytes": 67108864,
      "sha256": "f0efd3a0818f65df0770dcdea27a3c6bd8966d60adb8854c146e925adc1db1f1"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.013",
      "bytes": 67108864,
      "sha256": "93df2e861f4eb0a53be2481e15de09781f744ca3fd33684c659ca8ab364d57ca"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.014",
      "bytes": 67108864,
      "sha256": "f2a0bb53cdf0873ed574d8770f88ff2d32e4dad6fd84c1780abe0524ed536af4"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.015",
      "bytes": 67108864,
      "sha256": "b17f4beff7cf96ae9a970e69f1cf21a6316b9bde80d6d67828569438f16d6784"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.016",
      "bytes": 67108864,
      "sha256": "0dad9ba24da4ca4521d560136c8cf427ba8f3de00f4eaaf83307b42a5363e58e"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.017",
      "bytes": 67108864,
      "sha256": "9bb83b7781ee1784bf555a2f46dd24948aacc0e769c343d626aaf2519fd7312f"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.018",
      "bytes": 67108864,
      "sha256": "8eb1e8d34f9faa818374b732db703d4e4ff0e976e259f9d498dd96884570c3c8"
    },
    {
      "name": "forecast-dispatch-20260929-r2.zip.019",
      "bytes": 58166993,
      "sha256": "1aae0fcc4c44bd3f3d1c45ed62d9775b9a2ddc5987bdd6b565a5d907aae2bb3b"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260929-r2"
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
