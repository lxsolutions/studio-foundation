# Studio Foundation roadmap

This roadmap develops the public Godot platform through evidence-backed
milestones. Product roadmaps for individual games belong in their own
repositories.

## Current foundation

Completed or demonstrated:

- [x] Pinned official Godot 4.7.1 editor and WebGL 2 export path
- [x] Browser WebGPU templates built and visually validated from the historical
      4.7.1 integration tree
- [x] Repository-local, checksum-pinned WebGPU patch series
- [x] Rust protocol, simulation, dedicated-server, and PostgreSQL persistence
- [x] Shared Godot addon, template project, browser smoke, and visual comparison
- [x] Agent working agreements, narrow MCP operations, and local CI commands
- [x] Self-hostable Docker Compose development infrastructure

## Phase 1 - Make the standalone source model routine

- [ ] Keep `engine-fetch` independent of any LX Solutions engine fork.
- [ ] Exercise the patch-update runbook against the next official Godot ref.
- [ ] Enforce patch checksums and engine-lock validation in CI.
- [ ] Publish fresh build, browser smoke, and visual evidence after every accepted
      engine base update.
- [ ] Audit public documentation for stale fork URLs and unsupported claims.

## Phase 2 - Harden supported workflows

- [ ] Run WebGPU validation on trusted CI hardware with a real browser/GPU path.
- [ ] Add Android export and device evidence; add iOS evidence when macOS hardware
      is available.
- [ ] Expand deterministic asset validation, budgets, and import checks.
- [ ] Deploy and probe the complete identity-to-authority-to-database path.
- [ ] Establish performance budgets for representative Godot scenes and services.

## Phase 3 - Improve reuse

- [ ] Validate a second independent Godot project generated from the template.
- [ ] Version shared addons and migration guidance.
- [ ] Document stable extension points for product-specific gameplay.
- [ ] Publish compatibility and upgrade notes for each supported Godot release.
- [ ] Reduce bootstrap and CI time without weakening evidence.

## Phase 4 - Reassess from shipped evidence

After serious shipped use, review whether recurring limitations justify a
larger native module, editor plugin, renderer patch, or other architectural
change. A different client runtime remains a product-level decision unless
multiple public adopters demonstrate a shared requirement.

## Decision rule

Prefer the smallest maintainable platform change that solves a measured problem.
Keep official Godot upstream, keep browser fallback viable, and keep public
claims tied to repeatable evidence.