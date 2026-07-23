# Studio Foundation bootstrap — Windows (native; WSL2 users run scripts/bootstrap.sh inside WSL).
# Installs USER-SCOPE tools only. Anything needing elevation or a GUI installer is
# reported as a manual step, never auto-run. Safe to re-run (idempotent).
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$manual = @()

function Step($name, $script) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $script
}

Step 'winget available?' {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        $script:manual += 'winget (App Installer from Microsoft Store) — needed for tool installs'
    }
}

Step 'just (task runner)' {
    $just = Get-Command just -ErrorAction SilentlyContinue
    if (-not $just) { $just = Test-Path "$env:LOCALAPPDATA\Microsoft\WinGet\Links\just.exe" }
    if (-not $just) { winget install --id Casey.Just -e --accept-source-agreements --accept-package-agreements --disable-interactivity }
    else { Write-Host 'already installed' }
}

Step 'Rust (rustup, windows-gnu host — no MSVC required)' {
    if (Test-Path "$env:USERPROFILE\.cargo\bin\cargo.exe") { Write-Host 'already installed' }
    else {
        $tmp = Join-Path $env:TEMP 'rustup-init.exe'
        Invoke-WebRequest -Uri 'https://win.rustup.rs/x86_64' -OutFile $tmp
        & $tmp -y --profile minimal --default-toolchain stable-x86_64-pc-windows-gnu
    }
    # windows-gnu quirk: rustc finds raw-dylib's dlltool via PATH only, but rustup
    # ships it in the toolchain's self-contained dir. Put that dir on the user PATH.
    $sc = Join-Path $env:USERPROFILE '.rustup\toolchains\stable-x86_64-pc-windows-gnu\lib\rustlib\x86_64-pc-windows-gnu\bin\self-contained'
    if (Test-Path (Join-Path $sc 'dlltool.exe')) {
        $cur = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($cur -notlike '*self-contained*') {
            [Environment]::SetEnvironmentVariable('Path', "$cur;$sc", 'User')
            Write-Host "added dlltool dir to user PATH: $sc"
        }
    }
}

Step 'uv (Python env manager)' {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements --disable-interactivity
    } else { Write-Host 'already installed' }
}

Step 'Python tool environment (tools/)' {
    uv sync --project tools --group dev
}

Step 'Godot (pinned in engine/engine-lock.toml)' {
    $probe = python tools\doctor\doctor.py --json | ConvertFrom-Json | Where-Object { $_.name -eq 'godot' }
    if ($probe.state -ne 'ok') {
        winget install --id GodotEngine.GodotEngine -e --accept-source-agreements --accept-package-agreements --disable-interactivity
    } else { Write-Host $probe.detail }
}

Step '.env' {
    if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host 'created .env from .env.example' }
    else { Write-Host 'exists' }
}

Step 'git guardrail hooks' {
    git config core.hooksPath .githooks
}

Step 'browser test harness (optional, needs Node)' {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Push-Location tests\browser; npm ci --no-audit --no-fund; Pop-Location
    } else {
        $script:manual += 'Node.js 22 LTS (winget install OpenJS.NodeJS.LTS) — for Playwright browser smoke tests'
    }
}

# ---- Manual items (never auto-installed) ----
$manual += 'Docker Desktop — start it before `just services-up` (winget install Docker.DockerDesktop; needs WSL2)'
$manual += 'Blender LTS — GUI/MSI installer may elevate: winget install BlenderFoundation.Blender'
$manual += 'Android Studio + SDK + JDK 17 — only for Android export validation'
$manual += 'iOS builds require a macOS machine with Xcode (not possible on Windows)'
$manual += 'WebGPU template builds additionally need Emscripten (see engine/README.md)'

Write-Host "`n== Bootstrap done. Manual requirements remaining ==" -ForegroundColor Yellow
$manual | ForEach-Object { Write-Host " * $_" }
Write-Host "`nNow run: just doctor" -ForegroundColor Green
