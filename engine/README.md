# Engine integration

Official Godot is the editor and engine of record. Studio Foundation's browser
WebGPU support is an in-repository integration: committed, checksum-pinned
patches are applied to a locked official Godot commit in a disposable local
worktree. No separate LX Solutions engine fork is required.

See ADR 0002, ADR 0008, and NOTICE.md for the design boundary and source
lineage.

## Source of truth

`engine-lock.toml` records the official base commit, historical source lineage,
toolchain versions, ordered patch files, patch checksums, and build flags.
`engine/patches/` contains the reviewable integration. `engine/.cache/` contains
disposable clones and worktrees; `engine/artifacts/` contains build outputs.
Neither cache nor artifacts are source of truth.

## Commands

```sh
just engine-versions
just engine-fetch
just engine-build
just engine-rebase --dry-run --json
```

- `engine-versions` shows the lock pins, patch count, and local cache state.
- `engine-fetch` fetches only official Godot, verifies every patch checksum, and
  prepares `engine/.cache/studio-webgpu`.
- `engine-build` builds WebGPU release/debug templates from that patched tree.
  `engine-build --workspace <name>` builds an update candidate into
  `engine/artifacts/candidates/<name>/templates`.
- `engine-rebase` applies the locked patch series with three-way context to
  another official Godot ref in an isolated candidate worktree.

A candidate ref must already exist in `engine/.cache/godot-official`:

```sh
git -C engine/.cache/godot-official fetch origin 4.8-stable
just engine-rebase --official-ref 4.8-stable --dry-run --json
just engine-rebase --official-ref 4.8-stable
```

The command never resets, cleans, or deletes an existing source tree. Conflicts
remain in the candidate worktree for inspection. There is intentionally no
automatic cleanup command.

The full validation and landing procedure is in
`docs/runbooks/godot-webgpu-update.md`.