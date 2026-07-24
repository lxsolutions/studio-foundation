# Security policy

## Supported versions

Security fixes are made against the current `main` branch and the exact
dependency and engine revisions recorded by its lockfiles. Older commits,
locally modified engine builds, and downstream games are not maintained by
this repository.

The Godot WebGPU export path is beta. It is suitable for evaluation and
reproducible testing; this repository does not currently promise production
support for every browser, GPU, or workload.

## Report a vulnerability

Please use GitHub's private vulnerability reporting flow:

<https://github.com/lxsolutions/studio-foundation/security/advisories/new>

Include the affected commit, reproduction steps, expected and observed
behavior, and any relevant browser, GPU, operating-system, or toolchain
versions. Do not publish exploitable details in a public issue before a fix is
available.

## Supply-chain controls

The release tooling is designed to make dependencies and generated artifacts
auditable:

- Godot and WebGPU source inputs are pinned to immutable commits.
- The ordered engine patch series and export templates are SHA-256 locked.
- The build fails if a template labeled WebGPU lacks the compiled WebGPU
  backend.
- Browser verification observes the engine's own adapter, device, and canvas
  requests and rejects a WebGPU build that creates WebGL.
- Repository guardrails reject committed secrets and unexpected generated or
  binary files.

These controls reduce accidental dependency drift and mislabeled releases.
They are not a substitute for an independent security audit. Please evaluate
the beta against your own threat model before using it with untrusted content,
credentials, personal data, or production workloads.
