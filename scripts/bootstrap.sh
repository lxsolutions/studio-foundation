#!/bin/sh
# Studio Foundation bootstrap — Linux / macOS / WSL2. User-scope installs only;
# anything needing sudo or a GUI is printed as a manual step. Idempotent.
set -u
cd "$(dirname "$0")/.."
MANUAL=""
note() { MANUAL="$MANUAL\n * $1"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo '== Rust (rustup)'
if [ -x "$HOME/.cargo/bin/cargo" ] || have cargo; then echo 'already installed'; else
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
fi

echo '== uv'
if have uv; then echo 'already installed'; else
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo '== just'
if have just; then echo 'already installed'; else
  if have cargo; then cargo install just; else "$HOME/.cargo/bin/cargo" install just || note 'just: https://just.systems/man/en/packages.html'; fi
fi

echo '== Python tool environment'
uv sync --project tools --group dev || "$HOME/.local/bin/uv" sync --project tools --group dev

echo '== .env'
[ -f .env ] || cp .env.example .env

echo '== git guardrail hooks'
git config core.hooksPath .githooks

echo '== browser test harness (optional)'
if have npm; then (cd tests/browser && npm ci --no-audit --no-fund); else
  note 'Node.js 22 LTS — for Playwright browser smoke tests'
fi

note 'Godot editor (pinned in engine/engine-lock.toml): https://godotengine.org/download or distro package; set GODOT_BIN in .env if not on PATH'
note 'Blender LTS: https://www.blender.org/download/ (or distro package); set BLENDER_BIN in .env if not on PATH'
note 'Docker engine + compose plugin (distro packages; Linux may need group setup)'
note 'Android SDK + JDK 17 — only for Android export validation'
if [ "$(uname)" = "Darwin" ]; then note 'Xcode — required for iOS compile/signing'; else note 'iOS builds require macOS + Xcode'; fi
note 'Engine builds (WebGPU fork) additionally need Emscripten (see engine/README.md)'

printf '\n== Bootstrap done. Manual requirements remaining ==%b\n' "$MANUAL"
echo
echo 'Now run: just doctor'
