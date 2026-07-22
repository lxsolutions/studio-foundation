# Asha — the AI-Native Game Platform: Strategy & Roadmap

Status: living document (started 2026-07-20). Constrains every layer of the stack.
Related: ADR 0007 (one world, many scales), ADR 0008 (own the distribution, not the
engine), `docs/architecture/asha-platform-strategy.md`, `docs/architecture/vertical-slice.md`.

## The end state

Within a few years, the limiting factor in game development stops being "how many
engineers/artists can you hire" and becomes **how much verified, shippable work your
agents can land per day.** The winning studios aren't the ones with the best model —
models commoditize. They're the ones whose **entire production pipeline is
agent-operable**: an AI reads the goal, writes code/assets, runs the build, sees the
failure, fixes it, and proves it shipped — across every platform — without a human
unblocking it.

No engine offers this today. Unity/Unreal are human-click monoliths with bolted-on AI
assistants; Babylon/PlayCanvas/three.js are browser renderers, not production
platforms. The thing that does not exist yet:

> **An AI-native game platform: one authoritative world/toolchain where agents are
> first-class developers, and shipping to browser + mobile + console is a verified,
> repeatable, agent-runnable act.**

That is what Asha is. Not "an engine with AI features" — a **production organism**
where AI does the labor and humans do taste, direction, and judgment.

## Why we win (the moat — four compounding bets)

1. **Agent-operability as foundation, not plugin.** Unity/Unreal would have to
   rebuild 20 years of editor-first architecture to make agents first-class. We
   started there: `just` commands, studio-mcp tools, the honest BOOTSTRAP_REPORT,
   validation gates, the conflict classifier — the contract that lets Codex / Claude
   Code / Kimi do real work. Hardest thing to retrofit; we already have it.
2. **Browser-native AAA via owned WebGPU.** Official Godot web = WebGL2; Unity
   abandoned browser; Unreal never went. The browser is the biggest, most
   friction-free games channel on Earth — a link, no install — and WebGPU just made
   AAA rendering viable there. We own a maintained WebGPU Godot backend
   (`lxsolutions/godot-webgpu`). A **distribution moat**: our games reach players
   Unity/Unreal cannot reach without an install.
3. **One authoritative world, many scales (ADR 0007).** An architecture engines
   can't sell you: Rust world-sim + PostgreSQL authority + Godot clients at every
   scale (social → extraction → strategy → FPS) sharing one identity/economy.
   Incumbents give a renderer; we give a *world*.
4. **Own the distribution, never the engine (ADR 0008).** Borrow Godot's
   editor/scene/exporters (free, community-maintained, console-ported); own only the
   differentiating layer. Small team, no engine-maintenance treadmill, infinite
   leverage.

Compounding: **agent-operable × browser-reach × one-world × no-engine-debt** = a
small team shipping a living, everywhere-at-once game faster than studios 50× its
size. That is what makes people switch.

## What makes it substantially the most valuable

- **Timing.** Agent capability crossed the "does real multi-hour work" threshold this
  year; almost no production stack is ready to receive that labor. We're early to the
  only posture that matters.
- **The browser gap is open now.** WebGPU is new enough that a maintained Godot
  WebGPU path is a temporary, closeable window — we closed it first.
- **Network effect of one world.** Every game feeds the same civilization/economy/
  identity; each new player makes every game more meaningful. Unity sells engines;
  we grow a *world*.

## The platform we become

```
ASHA — the AI-native game platform

  CREATION (agents do the labor)
  ├─ Godot editor (borrowed, clean upstream — never forked)
  ├─ studio_core + editor plugins (our framework)
  ├─ Blender → GLB deterministic cooker (our pipeline)
  └─ Skills + studio-mcp + just: the agent contract

  WORLD (one authoritative reality)
  ├─ Rust world-simulation — services/world-sim (factions, sectors,
  │   stockpiles, canonical WorldEvents, bounded-impact economy; done, tested)
  ├─ PostgreSQL (durable world state)
  └─ Nakama (identity, social, matchmaking)

  REACH (everywhere a player is)
  ├─ Browser:  our WebGPU backend (AAA, zero install)  ← the wedge
  ├─ Mobile:   Godot iOS/Android (one shared project)
  └─ Console/PC: Godot's licensed console paths (never ours to port)

  TRUST (why agents/humans rely on it)
  ├─ Validation gates (build → export → capture → compare)
  ├─ Honest status ledger (BOOTSTRAP_REPORT.md)
  └─ Visual regression + protocol fixtures as code
```

**Endgame:** describe a game, and a fleet of agents builds, balances, tests, and
ships it to every platform — while a handful of humans steer. Highest strategic
success = becoming the platform the next generation of AI-native studios is built
on, the way Unity became the default for the last.

## Roadmap

### Phase 1 — Prove the loop on one game, browser-first, agent-built  *(current)*
1. ~~Close the WebGPU claim~~ **DONE (2026-07-20):** 4.7.1 build green → WebGPU
   export boots → `capture-web` shows the real menu rendering → visual-regression
   gate passes. WebGPU is an evidence-backed browser path (BOOTSTRAP_REPORT).
2. Ship the vertical slice (`vertical-slice.md`): closed-loop sector — mine →
   refine → build → battle → capture territory — playable in a browser via WebGPU,
   Rust world-sim settling into PostgreSQL.
   **Progress (2026-07-20):** `games/asha_world` created and **renders in WebGPU**.
   The authoritative spine is built and tested: `services/world-sim` (canonical
   WorldEvents, idempotent settle, bounded-impact economy) + dedicated-server
   `run_server_with` + protocol `WorldEventSubmit`/`WorldEventResult` (Rust,
   GDScript mirror, golden fixtures) + a `world_slice` client loop driving the
   events over WebSocket. Nakama now authenticates public RPC callers and forwards
   canonical events to a private Rust adapter; first-seen results commit an append-only
   event ledger and recovery snapshot atomically before acknowledgement, with database-backed idempotency and a live replay probe.
   Remaining: deploy the full path for live play and build real 3D gameplay.
3. Prove the agent flywheel on it: agents drive iteration via studio-mcp +
   godot-fork-webgpu skill (build, test, capture, compare, fix) with a human only
   steering. Measure agent-landed vs human-landed changes.
4. Make the slice the reference every later target inherits.

### Phase 2 — Harden the pipeline into a product
- `just engine-validate` as CI gate (visual regression as code).
- studio-mcp engine lifecycle complete (classify, build status, capture, compare).
- Mobile export evidence (Android first; iOS needs macOS hardware).
- Nakama social/matchmaking plus the Rust/PostgreSQL authority path deployed live.

### Phase 3 — Open the world
- The Deep + Plato's Plaza as two scales of the same world, browser-native.
- Profession/puzzle layers as agent-generated content packs.
- Console/PC via Godot's licensed paths once a game justifies it.

### Phase 4 — Become the platform
- Other small teams build on Asha; the agent contract + world-sim are the product.

## The one-line strategy

> **Borrow the commodity engine; own the agent-operable distribution and the one
> world; win the browser first because it's the only channel the incumbents can't
> reach — and let agents do the labor everywhere.**
