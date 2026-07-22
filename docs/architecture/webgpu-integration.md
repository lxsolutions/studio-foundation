# WebGPU integration: provenance and Studio Foundation work

Studio Foundation does not claim to have invented its Godot WebGPU backend.
The original backend code is MIT-licensed work from
[`dwalter/godotwebgpu`](https://github.com/dwalter/godotwebgpu), pinned for
lineage at commit `f329e39ce8db7acaa5c9d6628a530fb769969228`.

It is also inaccurate to describe Studio Foundation as merely a copy of that
repository. The available historical source line was a useful starting implementation,
but it was not a usable release for Studio Foundation's Godot 4.7.1 target.
Studio Foundation completed the forward port, corrected integration failures,
scoped the result, and made it one component of a broader reproducible platform.

The historical source repository is not strategically required: Studio Foundation owns
the maintained integration and can replace or rewrite any part of it under the
MIT license. Its name is preserved here because honest ancestry strengthens the
project; it does not define the project's identity or ongoing roadmap.

## Why a forward port was required

At the pinned historical source commit:

- the available backend line was based on Godot 4.6.2, while Studio Foundation
  authored and exported projects with official Godot 4.7.1;
- the 4.6.2 template read pack format v3 while the 4.7.1 editor wrote v4, causing
  `Pack version unsupported: 4` at browser startup;
- no aligned 4.7 release line was available for Studio Foundation to consume;
- integrating the backend with official 4.7.1 required resolution of 119
  conflicts across renderer, platform, dependency, and engine changes; and
- after that integration, two additional 4.7.1 API/renderer compile failures
  still had to be diagnosed and corrected.

Copying that historical source commit could therefore neither load nor render the project's
4.7.1 export. Studio Foundation's maintained result is the completed 4.7.1 port
plus its reproducible build, fallback, and validation system. Detailed command
and runtime evidence is preserved in `BOOTSTRAP_REPORT.md`.

## Upstream model

Studio Foundation has one engine upstream:
[`godotengine/godot`](https://github.com/godotengine/godot). The WebGPU patches
are Studio Foundation's maintained delta against that upstream. Other
repositories named in this document are source lineage, not upstreams,
submodules, remotes, or build dependencies.

## Responsibility boundary

| Area | Origin or owner |
|---|---|
| Initial Godot WebGPU backend implementation | `dwalter/godotwebgpu`; retained with MIT attribution |
| Port from the available 4.6.2 line to official Godot 4.7.1 | Studio Foundation |
| Resolution of 119 upstream integration conflicts | Studio Foundation |
| 4.7.1 API and renderer fixes after the merge | Studio Foundation |
| Selection of build-relevant changes and exclusion of unrelated branch changes | Studio Foundation |
| Checksummed, repository-local patch packaging | Studio Foundation |
| Official-base source preparation and update tooling | Studio Foundation |
| Release/debug template build and artifact layout | Studio Foundation |
| WebGPU browser boot, screenshot, visual comparison, and benchmark gates | Studio Foundation |
| WebGL 2 fallback policy and Godot-facing platform abstractions | Studio Foundation |
| Shared Godot addon, templates, Rust authority, persistence, assets, CI, and agent workflows | Studio Foundation |

The integration is therefore derivative open-source engineering with clear
lineage, plus substantial maintenance, porting, validation, and platform work.
It is not a clean-room backend, and the project does not market it as one.

## Reviewable patch scope

The locked series currently contains:

| Patch | Purpose | Files | Added | Deleted |
|---|---|---:|---:|---:|
| `0001-studio-webgpu-engine.patch` | Engine, renderer, browser platform, and build integration | 72 | 18,888 | 188 |
| `0002-studio-webgpu-spirv.patch` | Required vendored SPIR-V headers/tools | 397 | 155,766 | 10 |
| `0003-studio-webgpu-tint.patch` | Required vendored Tint source and license | 824 | 202,514 | 0 |

The third-party line counts are reported separately so dependency source is not
misrepresented as Studio Foundation-authored code. The first patch is the
reviewable Godot integration surface: 30 files under `servers/rendering`, 26
under `drivers/webgpu`, 7 under `platform/web`, and a small set of build,
resource, and startup hooks.

## Reproduce and inspect

```sh
just engine-versions
just engine-fetch
git -C engine/.cache/studio-webgpu status --short
git apply --numstat engine/patches/0001-studio-webgpu-engine.patch
just engine-build
just engine-validate
```

`engine-fetch` retrieves official Godot only. It rejects missing, altered,
uppercase, or path-escaping patch entries before source preparation. The
separate LX Solutions engine repository is not required.

Build and runtime evidence is recorded in `BOOTSTRAP_REPORT.md`. Exact source
and toolchain pins live in `engine/engine-lock.toml`. Attribution lives in
`NOTICE.md`.