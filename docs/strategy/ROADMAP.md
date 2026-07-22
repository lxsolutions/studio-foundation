# Asha — Ultimate Strategic Plan & Roadmap

The master plan for becoming the **number-one choice for AI-native game
development across browser, iOS/Android, console, and PC** — and for making open
source beat Unity and Unreal by being the only stack built for AI labor.

Read with: [POSITIONING.md](POSITIONING.md) (transcend, don't shed),
[AI_NATIVE_PLATFORM.md](AI_NATIVE_PLATFORM.md) (the thesis),
ADR 0007 (one world), ADR 0008 (own the distribution).

---

## The end state we are building toward

A world where a small team — amplified by AI agents — ships AAA-quality games to
**every platform from one shared project and one persistent world**, playable
instantly from a browser link, where agents do the production labor and humans
steer taste. Where the platform itself is open source and becomes the *standard*
way AI-native games are made — and the world it hosts is the destination.

**The moat (four compounding bets no incumbent can copy):**
1. **Agent-operable by foundation** — build/test/render/verify/ship as machine
   commands (MCP + skills + `just` gates). Unity/Unreal would have to rebuild
   20 years of editor-first architecture to match.
2. **Browser-native AAA** — owned Godot WebGPU backend; reach a link, no install.
   Incumbents abandoned the browser; we own the breach.
3. **One authoritative world** — Rust world-sim + PostgreSQL; many games/scales
   sharing one identity/economy. Engines can't sell you a world.
4. **Own the distribution, never the engine** — borrow Godot; own only the
   differentiating layer. No maintenance treadmill.

---

## Phase 1 — Prove the loop publicly  *(current; ~90% done)*

Goal: a stranger plays a real game from a link, built mostly by agents.

- [x] WebGPU 4.7.1 backend, validated rendering (`just engine-validate`).
- [x] World-sim + protocol + dedicated-server + PostgreSQL persistence.
- [x] Vertical slice: mine → refine → build → deploy → battle → territory (3D).
- [x] Agent multipliers: conflict classifier, godot-fork-webgpu skill, MCP tools.
- [x] Public repo, dual licensing (platform open / games proprietary).
- [x] Public-host turnkey (one-container deploy + Cloudflare headers + runbook).
- [ ] **Go live:** host the export + world-sim on a public host; one stranger plays.
- [ ] Prove the agent flywheel: measure agent-landed vs human-landed changes.

## Phase 2 — Become the reference for AI-native Godot

Goal: the pipeline is a product; the rebase flywheel is proven.

- [ ] `engine-validate` as CI gate on every push. The workflow is hardened in
      the current worktree (trusted pushes only on self-hosted hardware, exact
      engine rebuild first); publishing that workflow is still required before
      this can be marked enforced.
- [ ] WebGPU rebase flywheel survives the next two Godot releases (runbook +
      classifier make it mostly mechanical).
- [ ] Mobile export evidence (Android .apk on a device/emulator; iOS needs macOS).
- [ ] Self-verifying Blender asset factory: headless generate → validate →
      budget → cook → into a live scene, agent-driven.
- [ ] Nakama live authority: identity/social/matchmaking; world-sim graduates
      from in-process to the production RPC layer. Authenticated event RPCs now
      settle through the private Rust adapter with an atomic event-ledger/snapshot
      replay probe; social/matchmaking and deployment remain.
- [ ] Console-style proof: Steam Deck native run (no NDA; validates controller +
      performance model console cert demands).

## Phase 3 — Transcend the brand; open the world

Goal: the platform is the story, not the engine; the world opens to many games.

- [ ] The Deep + Plato's Plaza as two scales of the same world (ADR 0007).
- [ ] Profession/puzzle content packs (agent-generated) feeding the one economy.
- [ ] Console via Godot's licensed paths (W4 / porting house) once a game justifies it.
- [ ] Public world events: players see the shared civilization change (territory,
      economy, wars) across games.

## Phase 4 — Become the standard

Goal: other teams build on Asha; the world is a destination.

- [ ] Prompt-to-shipped-game: describe a game; agents build, balance, test, ship
      to browser + mobile + console; humans steer.
- [ ] The agent contract (MCP + skills + gates) becomes the de-facto standard for
      AI-native game development.
- [ ] The world accrues network effect: every game and player makes it more valuable.

---

## What we deliberately will NOT do

- Shed Godot (the engine) — it's the commodity we borrow. We transcend the label only.
- Fork godotengine/godot or maintain console backends ourselves.
- Chase feature-parity with Unity/Unreal. We win on a different axis
  (agent-operable × browser-reach × one-world × no-engine-debt), not by out-featuring them.
- Put secrets, console SDK material, or proprietary game content in the open repo.

## The one-line plan

> **Prove the loop publicly → become the reference for AI-native Godot →
> transcend the engine brand and open the world → become the standard platform.**
