# Runbook: Update the Studio Foundation WebGPU patch series

The WebGPU integration is an ordered patch series applied to official Godot
(ADR 0002). Every update is prepared in an isolated worktree, reviewed, built,
and compared with the maintained WebGL fallback before lock data changes.

## Current state

`engine/engine-lock.toml` pins official Godot 4.7.1 commit
`a13da4feb8d8aefc283c3763d33a2f170a18d541` and seven committed patch files.
The original backend lineage is `dwalter/godotwebgpu` commit
`f329e39ce8db7acaa5c9d6628a530fb769969228`. The historical validated 4.7.1
tree is `14f5effb72ae440a3aa575c801e4aae1a5da7fb8`. Neither historical
repository is fetched during normal source preparation.

Verify lock and local cache state:

```sh
just engine-versions
just engine-rebase --dry-run --json
```

The current locked base reports `up_to_date` and creates no candidate worktree.

## Prepare another official Godot ref

1. Prepare the locked source and official clone:

   ```sh
   just engine-fetch
   ```

2. Fetch the proposed official tag or commit without changing the lock:

   ```sh
   git -C engine/.cache/godot-official fetch origin <official-tag-or-commit>
   ```

3. Inspect the plan:

   ```sh
   just engine-rebase --official-ref <official-tag-or-commit> --dry-run --json
   ```

4. Apply the patches to an isolated candidate:

   ```sh
   just engine-rebase --official-ref <official-tag-or-commit>
   ```

   A clean application reports `patches_applied`. A three-way conflict reports
   `conflicts` and leaves the worktree intact for review. The command never
   resets, deletes, or cleans an existing workspace.

5. For conflicts, inspect the exact patch and official change before resolving:

   ```sh
   git -C engine/.cache/rebases/<workspace> status
   git -C engine/.cache/rebases/<workspace> diff --cc
   python engine/scripts/classify_conflicts.py      --source-dir engine/.cache/rebases/<workspace> --json
   ```

   Renderer and third-party changes always require manual review. Do not use a
   blanket ours/theirs resolution.

## Mandatory candidate gate

1. Resolve conflicts and ensure `git diff --check` is clean apart from documented
   third-party whitespace.
2. Build candidate templates with
   `just engine-build --workspace <workspace>`.
3. Run `just test`.
4. Run `just export-browser-webgl`.
5. Point the WebGPU preset at the candidate templates, then run
   `just export-browser-webgpu` and `just run-browser-smoke`.
6. Capture WebGL and WebGPU output and run `just engine-validate`.
7. Run `just benchmark-scene` and record the results.

A candidate is not accepted merely because it compiles. It must load the
current pack format, render a non-blank canvas, stay within the documented
visual tolerance, and leave WebGL green.

## Land the update

1. Regenerate the scoped patch series against the new official base. Do not add
   unrelated changes from a historical branch.
2. Recalculate every patch SHA-256, record the accepted release/debug
   template byte counts and SHA-256 values, and update `engine/engine-lock.toml`.
3. Update ADR 0002, NOTICE.md, and BOOTSTRAP_REPORT.md with the new base,
   lineage, commands, and measured evidence.
4. Run `just release-validate --allow-dirty` and `just ci-local`.
5. Land the Studio Foundation change through review. There is no second
   repository or branch to publish.

If official Godot supplies a WebGPU backend that passes these gates, remove the
local integration and retain WebGL as the fallback until the official path is
equally well evidenced.