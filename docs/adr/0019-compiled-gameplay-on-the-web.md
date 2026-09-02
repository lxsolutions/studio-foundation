# ADR 0019: Compiled gameplay on the web — a side-car kernel, not the main module

- Status: Accepted
- Date: 2026-09-02
- Extends: [ADR 0003](0003-gdscript-shared-gameplay-language.md) (GDScript as the
  shared gameplay language), [ADR 0018](0018-brief-to-battle-world-compiler.md)
  (the deterministic simulation kernel is milestone M3)
- Relates: [ADR 0002](0002-webgpu-patch-series.md) — the WebGPU series is *not* an
  answer to this problem, and this ADR exists partly to stop it being read as one.

## Context

A team with a C# Godot client tries to ship to the browser and gets:

```
export failed: cannot combine Mono runtime with the web platform
```

They then find this repository — a Godot fork with a browser rendering path — and
ask a reasonable question: does it make Godot viable here?

**It does not, and no amount of work on that patch series ever will.** The two
problems sound adjacent and are not related at all.

A web export is one WebAssembly **main module**: the module that owns runtime
initialization, the linear memory, and the JavaScript glue the page boots. Godot's
Emscripten build is that module. The .NET runtime is *also* built to be that
module. Two runtimes, one slot. That is an architectural fact about how the
binary is initialized, and it is indifferent to export presets, export templates,
threading flags, and renderers.

Everything in `engine/patches/` changes what Godot **draws with** — SPIR-V, Tint,
WGSL, clustered lighting. Not one line of it touches module loading or runtime
initialization. A C#/.NET client hits the identical wall against a Studio
Foundation build as against stock Godot. Saying so plainly is the point: a team
that mistakes a rendering fork for a runtime fix loses weeks.

ADR 0003 already ruled that C# is not allowed in shared client code. What it did
not do is explain *why* to anyone arriving from the outside, or say what to do
with the requirement C# was carrying. That requirement is real and is not about
C#: teams want gameplay rules that are **typed, compiled, and identical on client
and server**, and GDScript alone does not offer that.

Meanwhile ADR 0018's milestone M3 shipped exactly that, for a different reason —
`services/sim-kernel`, a deterministic Rust kernel where initial state plus seed
plus event stream yields a final state hash, with the native binary and the wasm
build verified to agree over a frozen conformance corpus.

The connection was never written down, so the repository could not answer the
question above. It is written down here.

## Decision

**Compiled gameplay logic reaches the browser as a zero-import reactor module.
It does not compete for the main-module slot; it is instantiated by whichever
runtime already holds one.**

- `sim_kernel.wasm` imports **nothing**. Not WASI, not Emscripten, not a JS shim.
  It exports a linear memory and three functions (`sim_alloc`, `sim_free`,
  `sim_run`) and does nothing until a host calls it.
- Because it demands nothing of its host, any host can instantiate it: node, a
  bare browser page, a Babylon viewer, a dedicated server — and a running Godot
  web export, which loads it beside its own module without either one noticing.
- The Godot client stays GDScript (ADR 0003 is unchanged). `StudioSimKernel` is
  its view onto kernel state; the renderer observes and never invents state, the
  same contract `tools/sim-viewer/adapter.js` already holds to.
- **C# remains unsupported for web targets, and that is now said in the one place
  it comes up.** `tools/godot/export_game.py` refuses a `.csproj`/`[dotnet]`
  project on a web preset with the mechanism above and a pointer here, instead of
  letting Godot deliver a message that reads like a missing download.

### Enforcement

Host independence is a property one careless dependency destroys in silence — a
`println!`, a `std::time` call, a crate that reaches for the clock — each of which
adds a WASI import and makes the module unloadable from inside a Godot export.
Nothing about the build fails; the kernel just refuses to instantiate later, in a
browser, in someone else's product. So the property is checked mechanically:

| Gate | What it holds | Command |
|---|---|---|
| `tools/sim/host_abi.py` | zero imports, the exact reactor ABI and signatures, exported memory, no start section | `just sim-host-abi` |
| `tools/sim/tests/test_parity.py` | Python, native Rust and wasm agree on every conformance fixture, valid and invalid | `just sim-parity` |
| `tests/browser/sim-kernel-host.mjs` | the corpus replays in a **real browser** through the same host script Godot injects, matching the golden hashes | `just sim-browser-host` |
| `tools/godot/tests/` | the .NET refusal fires only on web presets; the host script actually ships in web exports | `just test-python` |

The browser gate matters most to the argument. Three hosts agreeing is a claim
about Rust and wasm; the browser is the host the whole question is about, so it
is checked where a team would actually run it.

## What this does not claim

- **It does not make C#/.NET work on the web.** That is a Godot and .NET upstream
  problem about which runtime boots the page. Nothing here changes it, and this
  repository should never imply otherwise.
- **It does not make the WebGPU series relevant to runtime questions.** Renderer
  and runtime are separate axes. ADR 0002 stands on its own merits.
- **It is not a general C#-to-Rust port path.** It is narrower and more useful:
  the *rules* move into a kernel both client and server run; presentation stays
  in the engine's own language.
- **It does not make GDExtension a browser strategy.** GDExtension on web needs
  `dlink_enabled=yes` templates and stays a compatibility risk (ADR 0003). The
  reactor kernel deliberately sidesteps GDExtension: it is loaded by the page,
  not linked into the engine.

## Consequences

- The repository can answer "would this have made Godot viable?" with a specific
  yes-and-no instead of a rendering demo: no for .NET, yes for the requirement
  underneath it, with the evidence attached.
- Gameplay rules get one implementation, compiled, shared by client and server,
  and identical across four hosts by test — which is more than a C# web export
  would have delivered even if it worked, since that would still have left the
  server on a separate build.
- A new cost: the kernel's wasm build must stay free of std side effects. The
  gate names the cause when it is not, which is the difference between a
  five-minute fix and a browser-only mystery.
- `StudioSimKernel`'s web path cannot run in the headless GDScript suite. It is
  split so the platform-free logic is tested there, and the browser half is the
  same file the browser suite drives — the untested seam is the wrapper, not the
  behavior.
