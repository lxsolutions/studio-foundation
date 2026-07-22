# Studio Foundation positioning

Studio Foundation is a public, Godot-first platform for small teams that want
repeatable game creation, export, backend, and validation workflows.

## What it is

- A pinned Godot distribution layer, not a new engine
- Shared GDScript services and project templates
- A reproducible browser WebGPU integration with WebGL 2 fallback
- Rust/PostgreSQL authority and simulation building blocks
- Blender asset processing and cross-platform export tooling
- Agent-readable commands, tests, evidence, and contribution agreements

## What it is not

- A fork or replacement for the Godot editor
- A general wrapper around multiple client engines
- The canonical runtime architecture for every LX Solutions product
- A claim that browser WebGPU has reached parity with native rendering
- A substitute for product-specific game design

Private products may make different runtime decisions, including Babylon.js or
Capacitor. Those choices do not change this repository unless they are proposed,
implemented, and accepted here through an ADR.

## Who it serves

The primary audience is a small Godot team that values:

1. one shared project per game across supported targets;
2. self-hostable services and permissive dependencies;
3. deterministic source, build, and release inputs;
4. explicit browser fallback behavior;
5. workflows that humans and coding agents can run the same way.

## How public claims are made

A capability is described as supported only when the command, environment, and
result are recorded in `BOOTSTRAP_REPORT.md`. Experimental paths are labeled
beta. Hardware-specific claims require hardware evidence.

The practical advantage is operational coherence: the editor, addons, browser
integration, backend, asset pipeline, tests, and release evidence are maintained
as one reviewable system.