# Locked WebGPU toolchain inputs

Studio Foundation builds against the Emdawn WebGPU port shipped with the exact
Emscripten version in `../engine-lock.toml`. The SDK installation is treated as
read-only:

1. `engine-build` locates the built-in Emdawn package.
2. It verifies the package version, Dawn revision, and `webgpu.cpp` SHA-256.
3. It copies the package into `engine/.cache/toolchains/emdawnwebgpu`.
4. It verifies and applies the patch in `patches/`.
5. It verifies the patched source SHA-256 and passes that local port path to
   the Godot build.

The namespace patch is a narrow backport from Dawn commit
`2752c7d71a190c8512f38ceda922253d23876fb4`. The pinned package predates
Dawn's anonymous namespace around private implementation types. Without that
isolation, its global C++ `RefCounted` class collides with Godot's global
`RefCounted`; Emdawn allocates a smaller object and the linker may invoke
Godot's larger constructor, producing a heap buffer overflow.

This is a toolchain compatibility input, not another engine upstream. Official
Godot remains the sole engine upstream.
