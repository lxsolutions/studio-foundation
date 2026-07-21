# Launch the Asha World vertical-slice dev stack, detached so it survives the
# invoking terminal:
#   1. world-sim game server (ws://127.0.0.1:8081)
#   2. static web server for the WebGPU export (http://127.0.0.1:8070/)
# Then open the browser. Re-run any time; existing listeners are reused.
# Usage: powershell scripts/dev_play_slice.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = "python"

function Test-Port($port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.Connect("127.0.0.1", $port); $c.Close(); return $true } catch { return $false }
}

if (-not (Test-Port 8081)) {
    Write-Host "starting world-sim server on 8081 ..."
    $env:STUDIO_DEDICATED_ADDR = "127.0.0.1:8081"
    Start-Process -FilePath "cargo" -ArgumentList "run --manifest-path games/asha_world/server/Cargo.toml" `
        -WorkingDirectory $repo -WindowStyle Hidden
} else { Write-Host "world-sim already listening on 8081" }

if (-not (Test-Port 8070)) {
    Write-Host "starting web server on 8070 ..."
    Start-Process -FilePath $python -ArgumentList "tools/godot/serve_web.py --game games/asha_world --preset web-webgpu --port 8070" `
        -WorkingDirectory $repo -WindowStyle Hidden
} else { Write-Host "web server already listening on 8070" }

Start-Sleep -Seconds 5
Write-Host "open: http://127.0.0.1:8070/  (world server ws://127.0.0.1:8081)"
Start-Process "http://127.0.0.1:8070/"
