# Runbook: Host a browser export

This runbook describes the transport requirements for a generated Godot browser
build. It does not prescribe a hosting vendor or product deployment.

## Export

Use the mechanics-neutral template or pass a consuming project explicitly:

```sh
just export-browser-webgpu GAME=templates/godot-game
# Release-safe fallback:
just export-browser-webgl GAME=templates/godot-game
```

The export appears under `<game>/project/exports/<preset>/`.

## Required HTTP behavior

Serve the directory as static files with:

- HTTPS outside localhost
- correct MIME types for `.wasm`, JavaScript, and packed resources
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Embedder-Policy: require-corp`
- a stable base path that matches the generated asset URLs
- no HTML fallback for missing `.wasm` or `.pck` files

The repository's local server implements these headers:

```sh
just serve-web GAME=templates/godot-game
```

## Validate before publishing

```sh
just run-browser-smoke
just capture-web --game templates/godot-game --preset web-webgpu
```

For WebGPU claims, validation must confirm `navigator.gpu`, a usable adapter,
and an active WebGPU canvas context. A successful page load alone is not WebGPU
evidence.

## Product boundary

A consuming repository owns its domain name, CDN, reverse proxy, authentication,
backend topology, secrets, rollout, and rollback. Do not add those
product-specific choices to Studio Foundation.
