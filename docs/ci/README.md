# Continuous integration

## `patch-series.yml` — not yet installed

[`patch-series.yml`](patch-series.yml) runs `engine/scripts/verify_patch_series.py`
on every push and pull request: it fails the build if any patch in
`engine/patches/` drifts from the SHA-256 recorded in `engine/engine-lock.toml`,
if a patch file exists that the lock does not cover, or if the series stops being
ordered and contiguous.

That is the repository's central claim — a transparent, checksum-locked patch
series over an official Godot commit — so it is worth enforcing mechanically
rather than by habit.

It lives here instead of `.github/workflows/` because GitHub refuses a push that
creates or updates a workflow file unless the credentials carry the `workflow`
OAuth scope, which the token used to land it did not have.

To enable it:

```sh
mkdir -p .github/workflows
git mv docs/ci/patch-series.yml .github/workflows/patch-series.yml
git commit -m "ci: enforce the WebGPU patch series"
git push
```

The job needs no toolchain — no Godot, no Emscripten, no GPU — and finishes in
seconds, so it cannot become a flaky gate. You can run exactly what it runs at
any time:

```sh
just engine-verify-patches
```

The checker's own failure paths are covered by
`engine/scripts/tests/test_verify_patch_series.py`, which runs under
`just engine-test`.
