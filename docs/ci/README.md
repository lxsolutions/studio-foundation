# Continuous integration

Two hosted workflows run on every push and pull request. Both are
toolchain-free — no Godot, no Emscripten, no GPU, no database — so they finish in
seconds, cannot become flaky gates, and run identically for a fork or a
first-time reader with no access to studio hardware.

The heavy suites (Godot, Rust, the engine build) belong to the self-hosted
`validate.yml` described in [`tools/ci/validate_workflows.py`](../../tools/ci/validate_workflows.py),
which is not installed here.

## [`patch-series.yml`](../../.github/workflows/patch-series.yml)

The repository's central claim is a transparent, checksum-locked patch series
over an official Godot commit. Two jobs enforce it mechanically rather than by
habit:

- **checksums and ordering** — [`verify_patch_series.py`](../../engine/scripts/verify_patch_series.py)
  fails if any patch in `engine/patches/` drifts from the SHA-256 recorded in
  `engine/engine-lock.toml`, if a patch file exists that the lock does not cover,
  or if the series stops being ordered and contiguous.
- **applies to a clean tree** — [`verify_patch_apply.py`](../../engine/scripts/verify_patch_apply.py)
  clones pristine official Godot at the locked base commit and applies the whole
  series. Checksums cannot tell you a patch actually *applies*: patch 0016 once
  shipped a modification hunk for a file no patch creates — it existed only as
  untracked local state in the tree it was generated from — and the fast job
  passed it while `git apply` failed on every clean checkout. This job is slower
  because it needs the real base tree, which is exactly why it catches what the
  fast one structurally cannot.

Run the fast one locally at any time:

```sh
just engine-verify-patches
```

The checker's own failure paths are covered by
`engine/scripts/tests/test_verify_patch_series.py`, which runs under
`just engine-test`.

## [`checks.yml`](../../.github/workflows/checks.yml)

- **workflow and secret policy** — [`validate_workflows.py`](../../tools/ci/validate_workflows.py)
  enforces the studio's CI security contract on `.github/workflows/` itself:
  every action pinned to a full 40-character commit, no self-hosted job
  reachable from an untrusted pull request. Then
  [`secret_scan.py`](../../tools/ci/secret_scan.py) scans for committed secrets.
- **python unit suites** — the stdlib-only suites: engine scripts (including the
  patch checker's own failure paths — the gate that guards the gate), studio-mcp,
  infra, the asset pipeline, bforge's schema and MCP surface, and the
  cross-language protocol golden fixtures.

Locally: `just lint-workflows`, `just test-python`, `just test-protocol`.

## Notes

Both workflows pin every action to a full commit SHA with the version in a
trailing comment. That is not decoration — `validate_workflows.py` rejects a tag
reference, and CI runs that checker against its own directory. Bump a pin by
resolving the tag to its commit, not by writing the tag.

A missing `.github/workflows/` directory now **fails** the policy job. It
previously returned success with "policy validation skipped", which made the
checker green for precisely as long as the repository had no CI at all — the one
state in which the trust and action-pin policy protects nothing.
