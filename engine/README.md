# Engine integration

Official Godot remains the editor of record. This directory pins and builds the
studio-owned WebGPU browser backend without vendoring either engine source tree
into the repository. See ADR 0002 and ADR 0008 for the boundary.

## Source of truth

`engine-lock.toml` records exact official/fork commits, toolchain versions, and
build flags. `engine/.cache/` contains disposable Git clones and merge worktrees;
`engine/artifacts/` contains reproducible build outputs. Neither is source of
truth.

## Commands

```sh
just engine-versions
just engine-fetch
just engine-build
just engine-rebase --dry-run --json
```

- `engine-versions` compares pins with local cache availability.
- `engine-fetch` checks out the exact official and fork commits.
- `engine-build` builds release/debug WebGPU web templates from the fork pin.
  `engine-build --workspace <name>` builds a candidate into
  `engine/artifacts/candidates/<name>/templates` without replacing pinned artifacts.
- `engine-rebase` prepares the next official-engine merge in an isolated
  worktree under `engine/.cache/rebases/`.

The current pins are already aligned, so the default rebase command reports
`up_to_date` and creates nothing. For a future official release already fetched
into `engine/.cache/godot-official`, pass its tag or commit:

```sh
just engine-rebase --official-ref 4.8-stable --dry-run --json
just engine-rebase --official-ref 4.8-stable
```

The command never resets, cleans, deletes, or checks out over the pinned fork
tree. A divergent target gets its own branch and worktree. Merge conflicts are
left intact as a successful `conflicts` preparation state for:

```sh
python engine/scripts/classify_conflicts.py \
  --fork-dir engine/.cache/rebases/godot-webgpu-4.8-stable --json
```

There is intentionally no automatic cleanup command: inspect and preserve the
merge until the full validation gate in `docs/runbooks/godot-fork-rebase.md`
passes and the new pin lands through review.
