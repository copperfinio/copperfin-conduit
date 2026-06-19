[CmdletBinding()]
param(
    [int] $Port = 20129,
    [string] $HostAddress = "127.0.0.1",
    [switch] $Smoke,
    [switch] $CacheProbe,
    [switch] $QuickTunnel,
    [switch] $InstallCloudflared,
    [switch] $Foreground
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$python = Get-Command "python" -ErrorAction SilentlyContinue
if (!$python) {
    $python = Get-Command "py" -ErrorAction SilentlyContinue
}
if (!$python) {
    throw "Python was not found on PATH."
}

$argsList = @(
    "-m", "conduit.cli",
    "start",
    "--port", "$Port",
    "--host", "$HostAddress"
)

if ($Foreground) {
    $argsList += "--foreground"
} else {
    $argsList += "--background"
}

& $python.Source @argsList

if ($Smoke -or $CacheProbe) {
    $smokeArgs = @(
        "-m", "conduit.cli",
        "smoke",
        "--root-url", "http://$($HostAddress):$($Port)"
    )
    if ($CacheProbe) {
        $smokeArgs += "--cache-probe"
    }
    & $python.Source @smokeArgs
}

if ($QuickTunnel) {
    $tunnelArgs = @(
        "-m", "conduit.cli",
        "tunnel",
        "--host", "$HostAddress",
        "--port", "$Port"
    )
    if ($InstallCloudflared) {
        $tunnelArgs += "--install-cloudflared"
    }
    & $python.Source @tunnelArgs
}
