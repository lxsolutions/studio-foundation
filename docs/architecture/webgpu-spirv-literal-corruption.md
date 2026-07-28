# WebGPU: `flatten_binding_arrays` corrupts std430 layout literals

- Status: **diagnosed, fix written, NOT yet built or verified**
- Found: 2026-07-28, by `tools/gauntlet` against Chariot Club's `web-webgpu` export
- Affects: `drivers/webgpu/spirv_preprocess.cpp`, shipped via
  `engine/patches/0001-studio-webgpu-engine.patch`

## Symptom

Chariot Club's `web-webgpu` export renders a black screen. It never obtains a
rendering context; shader translation aborts:

```
Tint SPIR-V→WGSL failed: var: struct size (32) is smaller than the end of the
last member (224)
  %instances:ref<storage, InstanceDataBuffer_1_1_a64, read_write> @binding_point(1, 2)
```

The `web-webgl` export is unaffected — `project.godot` sets
`renderer/rendering_method.web="gl_compatibility"`, so it never touches
RenderingDevice.

Measured, both exports freshly built:

| export | applicationRenderer | boot | black% | console errors |
|---|---|---|---|---|
| `web-webgl` | `webgl2` | 2.3 s | 0.07–0.25 | 0 |
| `web-webgpu` | `no-context-requested` | 18.9 s | **98.94–99.13** | **25** |

`fps p50` was **60** on the broken build, because it was drawing nothing. A
performance gate passes this; only a pixel gate catches it.

## Diagnosis

Raising the harness's console-error truncation from 400 to 8000 characters was
what made this solvable: it revealed the failure is not one struct but **four**,
all reporting the *same* impossible numbers.

```
InstanceDataBuffer_1_1_a64  @(1,2)   size 32, last member ends 224
OmniLights_1_1_a64          @(0,6)   size 32, last member ends 224
SpotLights_1_1_a64          @(0,8)   size 32, last member ends 224
AreaLights_1_1_a64          @(0,10)  size 32, last member ends 224
```

`InstanceData`, `LightData` and `AreaLight` have completely different layouts and
cannot all be 32 bytes ending at 224. **Identical constants across unrelated
types means the values are substituted, not computed.**

Ruled out first:

- **Not the GLSL.** `InstanceData` in
  `forward_clustered/scene_forward_clustered_inc.glsl` is byte-identical between
  `godot-official` and `studio-webgpu`. Its std430 layout is 176 bytes (208 with
  `USE_DOUBLE_PRECISION`). Nothing asks for 32.
- **Not `strip_restrict_decoration`.** It removes only Restrict (19),
  InputAttachmentIndex (43) and Volatile (21), and its operand offsets are correct.

## Root cause

`flatten_binding_arrays` performs a blunt whole-word ID substitution across every
instruction, replacing any operand word equal to a flattened array type ID with
that array's element type ID. Its own comment says so:

> *"comprehensive ID replacement across all instructions. Every operand word that
> matches an array type ID gets replaced with the element type ID."*

It excludes literal operands for exactly three opcodes — `OpConstant`,
`OpSpecConstant`, `OpSwitch` — and **not** for the decoration opcodes:

- `OpDecorate <target-id> <decoration> <literal…>` — carries **ArrayStride**,
  Binding, DescriptorSet
- `OpMemberDecorate <struct-id> <member-idx> <decoration> <literal…>` — carries
  **Offset**

So a layout literal whose *numeric value* happens to equal a flattened array
type ID is silently rewritten to that array's element type ID. Every buffer
whose stride collided with the same ID ends up with the same wrong size — which
is precisely the observed signature.

`OpName` / `OpMemberName` have the same exposure: their packed UTF-8 string words
can coincidentally equal a type ID.

## Fix

In `flatten_binding_arrays`, in the block that computes `has_literals` /
`literal_start`, add the decoration and name opcodes. Word 1 is the only ID in
each; everything after is literal.

```cpp
} else if (op == OP_DECORATE) {
        // OpDecorate <target-id> <decoration> <literal...>
        // Only word 1 is an ID. Words 2+ are the decoration enum and its
        // LITERAL operands -- ArrayStride, Offset, Binding, DescriptorSet.
        has_literals = true;
        literal_start = 2;
} else if (op == OP_MEMBER_DECORATE) {
        // OpMemberDecorate <struct-id> <member-index> <decoration> <literal...>
        has_literals = true;
        literal_start = 2;
} else if (op == OP_NAME || op == OP_MEMBER_NAME) {
        // Word 1 is the target ID; the rest is a packed UTF-8 string whose
        // words can coincidentally equal a type ID.
        has_literals = true;
        literal_start = 2;
}
```

`OP_MEMBER_NAME` is not currently declared; add it beside `OP_NAME`:

```cpp
static constexpr uint16_t OP_MEMBER_NAME = 6;
```

The change is conservative in the strict sense: it only *stops* substituting
words that were never IDs. Substituting a literal can never be correct, so this
cannot regress a case that previously worked.

## How to land it

The generated tree at `engine/.cache/studio-webgpu/` is rebuilt from the patch
series, so editing it does not persist. Per ADR 0002 / ADR 0008 the change goes
into **`engine/patches/0001-studio-webgpu-engine.patch`**, which is the patch that
adds `drivers/webgpu/spirv_preprocess.cpp` (77 references; 0002 has none).

Then: refresh patch checksums in `engine/engine-lock.toml`, `just engine-fetch`,
`just engine-build`, re-export, and confirm with

```bash
node tools/gauntlet/harness/shotset.mjs --remote smeagol --serve-port 8098 \
  --url http://127.0.0.1:8098/games/chariot/project/exports/web-webgpu/index.html \
  --source games/chariot/project --build games/chariot/project/exports/web-webgpu \
  --out runs/chariot-webgpu-fixed
```

Success is `applicationRenderer: webgpu` with `black%` in the low single digits
and zero console errors — matching the `web-webgl` control.

## Interim option

If a shipping fix is needed before the engine work lands, force Forward **Mobile**
for the WebGPU web target. All four failing buffers are Forward+ (clustered)
shaders, and existing studio evidence is that Mobile is the shipping tier while
Forward+ has never been clean under WebGPU. That avoids these buffers entirely
without touching the engine.
