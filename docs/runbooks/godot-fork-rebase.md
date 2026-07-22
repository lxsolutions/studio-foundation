# Runbook: Merge a new official Godot release into the WebGPU backend

The WebGPU backend is isolated from the official editor and treated as untrusted
input (ADR 0002). Every update is prepared in a dedicated worktree, reviewed,
built, and compared against the always-green WebGL fallback before any lock pin
changes.

## Current state

The original 4.7.1 port is complete. The maintained fork is
`lxsolutions/godot-webgpu`, branch `webgpu-4.7.1`, pinned at
`14f5effb72ae440a3aa575c801e4aae1a5da7fb8`. Official Godot 4.7.1 commit
`a13da4feb8d8aefc283c3763d33a2f170a18d541` is an ancestor of that fork pin.
Release/debug templates build, the exported pack boots, browser WebGPU renders,
and the cross-renderer visual gate passes. The old 119-conflict merge described
in earlier versions of this runbook is finished; `rebase-4.7.1-conflicts.txt` is
retained only as historical evidence and classifier input.

Verify the current ancestry without changing Git state:

```sh
just engine-rebase --dry-run --json
```

Expected status: `up_to_date`, with no worktree created.

## Prepare the next official release

1. Ensure the pinned caches exist:

   ```sh
   just engine-fetch
   ```

2. Fetch the proposed official tag or commit into the official cache. This does
   not change `engine-lock.toml`:

   ```sh
   git -C engine/.cache/godot-official fetch origin <official-tag-or-commit>
   ```

3. Inspect the plan. Dry-run mode never fetches into the fork object store,
   creates a branch, or creates a worktree:

   ```sh
   just engine-rebase --official-ref <official-tag-or-commit> --dry-run --json
   ```

4. Prepare the candidate merge:

   ```sh
   just engine-rebase --official-ref <official-tag-or-commit>
   ```

   The pinned fork checkout remains untouched. The command creates a branch and
   worktree under `engine/.cache/rebases/`. A clean merge reports `merge_ready`;
   expected merge conflicts report `conflicts` and remain unresolved in that
   worktree. Re-running the same command reports the existing worktree state.

5. Classify before resolving anything automatically:

   ```sh
   python engine/scripts/classify_conflicts.py \
     --fork-dir engine/.cache/rebases/<workspace> --json
   ```

   Review the classification, then optionally apply only the mechanical and
   base-lag recommendations with `--apply-safe`. Fork-touched renderer files
   require a hand union; never blanket-resolve them.

## Mandatory candidate gate

Run all checks against the candidate worktree before changing a pin:

1. `git -C engine/.cache/rebases/<workspace> diff --check`
2. Resolve all conflicts and commit the merge in the candidate branch.
3. `just engine-build --workspace <workspace>`
   Candidate template zips land in `engine/artifacts/candidates/<workspace>/templates`
   and do not replace pinned artifacts.
4. `just test`
5. `just export-browser-webgl`
6. Temporarily point the WebGPU export preset at the candidate templates, then
   `just export-browser-webgpu` and `just run-browser-smoke`.
7. Capture both renderers and compare them with the documented cross-renderer
   tolerance: `just engine-validate`.
8. Run the headless CPU benchmark and record it: `just benchmark-scene`.

A candidate is not accepted merely because it compiles. It must load the current
pack format, render a non-blank WebGPU canvas, stay within visual tolerance, and
leave the WebGL fallback green.

## Land the update

After the gate passes:

1. Push the reviewed candidate branch to `lxsolutions/godot-webgpu`.
2. Update `engine/engine-lock.toml` with the exact fork commit, official base,
   toolchain changes, and artifact checksums.
3. Update ADR 0002 and `BOOTSTRAP_REPORT.md` with commands and measured evidence.
4. Open a focused PR. Never merge directly and never delete the candidate
   worktree until the pin and evidence have landed.

If a rebase falls more than two minor releases behind, remains broken for more
than 90 days, or official Godot ships a WebGPU backend that passes these gates,
apply ADR 0002's abandon/switch rule and retain WebGL as the shipping fallback.