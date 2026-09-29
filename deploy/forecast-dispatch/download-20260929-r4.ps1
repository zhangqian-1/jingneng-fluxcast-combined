param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260929-r4",
  "filename": "forecast-dispatch-20260929-r4.zip",
  "bytes": 1266141131,
  "sha256": "68368745b76bf6de878d97fde99ad041024fd5102c2d4efdb76abe66fc8e6b36",
  "source_commit": "cf9887b733a3f192a6882dd5e749e3273dcf5424",
  "image": "jingneng-fluxcast-all-in-one:20260929-r4",
  "image_id": "sha256:2bcac6f95837fedd90afc73c88307a6b91f2d0c3839dbaea732f8d90230988de",
  "parts": [
    {
      "name": "forecast-dispatch-20260929-r4.zip.001",
      "bytes": 67108864,
      "sha256": "02f7c08c70a557e13c0546d0edc98c47ba707177438b753a7d17f644867f3a38"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.002",
      "bytes": 67108864,
      "sha256": "e764098cb5b2a85719ae3fd43a6e061107efd5f9dc6de312904bc36de7d259ad"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.003",
      "bytes": 67108864,
      "sha256": "3ee2594f7d8343d8aa7ff807cbaa5413665f7650e35fecdbc7ffe572861056b5"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.004",
      "bytes": 67108864,
      "sha256": "306986d7c2de3ac462d3c46831c10ac992c15dad5ccd1b83a3ef6e2c774ac555"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.005",
      "bytes": 67108864,
      "sha256": "2448b00400471f3a36cac115eb9cfd953a1839e12d47f1079caee08f9247a95b"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.006",
      "bytes": 67108864,
      "sha256": "a78e1bcbdaa9122261c847655b704cefb9b839386e5062702bd5a0c23dc63f65"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.007",
      "bytes": 67108864,
      "sha256": "e72d08d99b960926969a8215b6073eed02aefc47d30ff465f8e25a3c6fb36596"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.008",
      "bytes": 67108864,
      "sha256": "a2272a736b089e0ff42e816439efe22fc468ef97fd7b2747e768c88210fda0ae"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.009",
      "bytes": 67108864,
      "sha256": "6f96b4458e0abbb27b632895ead83ee5013ad4cebca8d5c57c705924411d420a"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.010",
      "bytes": 67108864,
      "sha256": "29e988f11237c450d121cb83e1547dc8c8b16f686a003ca0c57aabda345ea1eb"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.011",
      "bytes": 67108864,
      "sha256": "ea9ca2bba805afccf8c8343e275a3096ffc2e6821f27ec02c5ed364427ed8f2f"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.012",
      "bytes": 67108864,
      "sha256": "3eb3aaebab55648cb75b84f56f2744ef7b4cfdc9a6cfd7d770194efac2a5eb18"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.013",
      "bytes": 67108864,
      "sha256": "27e4a289c508dbf28b450841fe6e9884571f2419e9e458c3e3edbe976aefde87"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.014",
      "bytes": 67108864,
      "sha256": "c0cfbcee4a2509c6baeab9edb12c0fe986934f818d0da30f1c844179aaecf927"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.015",
      "bytes": 67108864,
      "sha256": "9ed15e6627cbe7d1011d0b6792e0cda082c440caae6bbdcaa048f25354267ee1"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.016",
      "bytes": 67108864,
      "sha256": "e69b311fea5f0171c1aee82ffb5b28715c379c8eb74ccad23dd191948e3a876f"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.017",
      "bytes": 67108864,
      "sha256": "87cd0484bd3a2e600e739ca726774e52d0fd4618ddbb9ddce5653579067a2ce7"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.018",
      "bytes": 67108864,
      "sha256": "617f679ed7fd389e3899aa66ec2c3fb7b4594601fb7be9f08601fdfa9be020a5"
    },
    {
      "name": "forecast-dispatch-20260929-r4.zip.019",
      "bytes": 58181579,
      "sha256": "717fc601fe23e7f55a9f50d266214aa3f8e5874ff0edaa9cec3213adfcc747cc"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260929-r4"
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
