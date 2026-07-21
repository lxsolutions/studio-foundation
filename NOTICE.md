# Notices and Attribution

This project's distribution layers incorporate third-party open-source
components. Full dependency/license inventory: `docs/architecture/dependency-licenses.md`.

## Asha WebGPU backend (vendored fork)

`engine` pins and builds a **studio-maintained fork** of the Godot WebGPU export
backend, hosted at `https://github.com/lxsolutions/godot-webgpu`.

- **Upstream source:** `https://github.com/dwalter/godotwebgpu`
- **License:** MIT (same as Godot Engine). Copyright retained by upstream authors.
- **Provenance note:** The upstream backend is largely **AI-generated** (per its
  own README) and carries no published release line. The studio vendors and
  maintains a `webgpu-4.7.1` port. Per ADR 0002 this code is treated as
  *untrusted input*: every change (ours or upstream) must pass the studio's full
  test + visual-regression gate before it is used in any export.

## Godot Engine

Primary engine, used unmodified as a clean upstream (never forked).
`https://github.com/godotengine/godot` — MIT License. Copyright (c) 2014-present
Godot Engine contributors; (c) 2007-2014 Juan Linietsky, Ariel Manzur.
