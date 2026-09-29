param(
    [switch]$Download,
    [string]$Destination = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$manifest = @'
{
  "version": "20260926-r3",
  "filename": "forecast-dispatch-20260926-r3.zip",
  "bytes": 1437269117,
  "sha256": "63ef101d898beeae656652e71879c2cfd3cdfb1af2d228921bf0cd09267e0763",
  "source_commit": "eeaf29efe31b7de3fecfd78d4d33fda621a6f530",
  "parts": [
    {
      "name": "forecast-dispatch-20260926-r3.zip.001",
      "bytes": 67108864,
      "sha256": "a26566cb0b74e71c3af9c9cbe4535fb8cab4d9b3bc6b77b7f0cd60d0281a2c79"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.002",
      "bytes": 67108864,
      "sha256": "00f92da18b79df66f2c1af6e180555db1ab49f9ea32857e206feec6862536938"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.003",
      "bytes": 67108864,
      "sha256": "143e4b112f9a01fcc64382eed3d9f728e67bddcf0dd6f6ffefeb4aabd6013f27"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.004",
      "bytes": 67108864,
      "sha256": "21d4a031c79a350ed6c912701ffc86701b9050e18e325947ee80ca421116acdc"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.005",
      "bytes": 67108864,
      "sha256": "30ea73f01d6ff6f0b3edc0a838c13b73914b37743420444a99eb36b6008f505c"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.006",
      "bytes": 67108864,
      "sha256": "4ef8701374cff63602136983b9f502a1b53822f472c509168db0cdaa381da120"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.007",
      "bytes": 67108864,
      "sha256": "e670006c3c869f36c2966abb135d949de75cdfcdce3627891b2c7f7cc08eee96"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.008",
      "bytes": 67108864,
      "sha256": "0d8cce9bb09b9745c141166ddaabad18c7d513db66256108e1cf3d8cceeb2824"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.009",
      "bytes": 67108864,
      "sha256": "c7e9c2f2049a062c78f096021ea026b6c270934cc7a3b3c150ca0b8cffb5c9d6"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.010",
      "bytes": 67108864,
      "sha256": "85d02b28adcbac9a875f7cf13076a69b386391c2ee60fc6687b786c341b331af"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.011",
      "bytes": 67108864,
      "sha256": "3c0df3d9ab4572398674577d4e3325602264e61783d7d8904e45c5899f4556eb"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.012",
      "bytes": 67108864,
      "sha256": "f9298629dc9a4ff75c30093eb9321e21558aedb6586752187808f72c238516cc"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.013",
      "bytes": 67108864,
      "sha256": "21a3c61f329a050d8ca200f429721f2ef3efecc898b7293845dfc0eafd1f4402"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.014",
      "bytes": 67108864,
      "sha256": "d61e5a94bc33967d7dc00181d5a0fa5ecd13aee501600aaff16c0829021cbba2"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.015",
      "bytes": 67108864,
      "sha256": "d3b38ddbf64f5445104e143dd10e099d425306346b90d2ad4a27b74f4ba6b5e2"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.016",
      "bytes": 67108864,
      "sha256": "fa86f15b04265189067f5d21d0190673e3aa7c2c1ebe5edd7b368cd221702913"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.017",
      "bytes": 67108864,
      "sha256": "64e418ce94e1d5ef98c8d2bf63bda395495e430bc30fdeed79ebb86356481c38"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.018",
      "bytes": 67108864,
      "sha256": "736572c6bf7a0a86cded78adb203b82a96445f4ea11460041d58b7a5c0caba6c"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.019",
      "bytes": 67108864,
      "sha256": "4e5b9d9e9e130ca845d031b78a1e49a90379f1715e8cd156cce8440a5c899965"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.020",
      "bytes": 67108864,
      "sha256": "01e5f89bcacc15361cf954218927453aad928fe6dcb900a046985249c29f1490"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.021",
      "bytes": 67108864,
      "sha256": "85bb9cf7dad35a14485976f4e245e8ffa134e214f517a7fe57e2d490959b8869"
    },
    {
      "name": "forecast-dispatch-20260926-r3.zip.022",
      "bytes": 27982973,
      "sha256": "d370808c4e0e993c33f434f3d6ee4f6801f056bc9eb4a394acdfcc906ab0543c"
    }
  ]
}
'@ | ConvertFrom-Json
$origin = 'http://117.78.35.35'
$baseUrl = "$origin/api/v4/projects/56/packages/generic/forecast-dispatch/20260926-r3"
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
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing $($part.name). Download all 22 parts or use -Download." }
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
