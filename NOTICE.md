# Notices and Attribution

Studio Foundation contains original platform work and incorporates
third-party open-source components. The dependency and license inventory is in
`docs/architecture/dependency-licenses.md`.

## Studio Foundation WebGPU integration

The browser WebGPU integration is maintained inside this repository as an
ordered, checksum-pinned patch series under `engine/patches/`. Build tooling
applies those patches to the official Godot 4.7.1 source commit; it does not
fetch or depend on a separate LX Solutions fork.

Technical source lineage:

- Official Godot base: `godotengine/godot` commit
  `a13da4feb8d8aefc283c3763d33a2f170a18d541`
- Original WebGPU backend: `dwalter/godotwebgpu` commit
  `f329e39ce8db7acaa5c9d6628a530fb769969228`
- Historical, validated Studio Foundation 4.7.1 integration tree:
  `14f5effb72ae440a3aa575c801e4aae1a5da7fb8`
- License: MIT, with copyright retained by the respective contributors
- Emdawn WebGPU package: Dawn revision
  `ea66c0fa309f01f2ba1ec2fd2c680cc992eaf72a`, with the private-namespace fix
  backported from Dawn commit
  `2752c7d71a190c8512f38ceda922253d23876fb4`; package licenses are MIT/UIUC
  and BSD-3-Clause as included by the pinned Emscripten distribution

The committed patches are intentionally scoped to the WebGPU implementation
and its required SPIR-V/Tint sources. Unrelated changes from the historical
source branch are not part of Studio Foundation's integration. Third-party
license files required by the patched source are carried in the corresponding
patches.

The historical source repository is an attribution and engineering reference only.
Studio Foundation maintains the current 4.7.1 integration, patch curation, build
tooling, browser validation, and release evidence.

## Godot Engine

Godot Engine is the official upstream editor and engine:
`https://github.com/godotengine/godot`, MIT License. Copyright (c)
2014-present Godot Engine contributors and (c) 2007-2014 Juan Linietsky and
Ariel Manzur.