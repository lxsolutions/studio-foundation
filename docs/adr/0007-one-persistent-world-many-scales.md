# ADR 0007: One Persistent World, Many Scales of Play

Status: Accepted (2026-07-20)
Supersedes: nothing. Constrains: every game built on this platform.

## Context

External design review (ChatGPT synthesis, 2026-07-20) of the studio's portfolio
(Plato's Plaza, The Deep, Galactic Conquest, Battlefront-style combat,
profession/puzzle games) concluded these must not be separate games stitched
together by a launcher, and must not be unified by combining multiple engines.

## Decision

The studio builds **one persistent society whose citizens experience the same
reality at different scales**:

> One world, one economy, one war, one identity, many ways of participating.

- Unification happens in the **authoritative Rust world simulation** and
  **PostgreSQL world state** — never by merging engines and never by client-side
  glue.
- Each "game" (Plaza, Deep, farms/settlements, industry/logistics, strategic
  command, battlefield FPS, RPG exploration) is a **role, scale, and interface**
  into the same simulation, delivered as a modular Godot content pack sharing
  one account, identity, progression graph, and art universe.
- All activities emit canonical world events (`ResourceExtracted`,
  `ContractAccepted`, `FactoryCompleted`, `BattleStarted`, `TerritoryChanged`,
  ...) which the Rust simulation validates and settles.

## Design laws (non-negotiable)

1. **Every mode must be a real game.** Mining, farming, strategy, and combat
   must each be independently fun. The shared world supplies *meaning*, never a
   substitute for fun.
2. **No role is mandatory drudgery.** AI citizens and baseline automation fill
   vacant roles; the world runs without humans. Human play improves efficiency,
   discovers opportunities, and redirects priorities.
3. **Contributions have bounded impact** (throughput limits, conversion ratios,
   diminishing returns, logistics constraints) so no single player decides a war
   in ten minutes.
4. **PvP/PvE safety boundaries**: secure home regions, contested zones,
   instanced frontlines, persistent strategic consequences.
5. **The commander delegates, not micromanages.** Strategic objectives generate
   contracts that cascade into gameplay for every other role. AI fills every
   unoccupied battlefield role.
6. **Players move between scales freely** — character, organization,
   possessions, reputation, and history follow them across all modes.

## Current implementation

- Godot and other real-time clients submit the canonical externally tagged event
  JSON over the shared WebSocket protocol.
- Authenticated public submissions enter through Nakama's `asha_world_event` RPC,
  which forwards to a bearer-protected private adapter on the Asha Rust server.
- The adapter settles through the same shared `WorldSim` using a row-locked
  PostgreSQL transaction. Every first-seen canonical event and its resulting
  snapshot commit atomically; the append-only ledger is the traceable history and
  database idempotency authority. Process memory changes only after commit.

## Consequences

- `shared/protocol/` must define the canonical world-event schema; it becomes
  the most important contract in the repo.
- The Rust backend grows a world-simulation crate (factions, sectors,
  stockpiles, factories, armies, contracts, settlement) distinct from
  session/auth services.
- Godot clients stay modular: no client loads every mode's assets; browser
  streams packs on demand, mobile downloads optional modules.
- The first milestone is the **single closed-loop campaign sector** vertical
  slice (see `docs/architecture/vertical-slice.md`), not the whole universe.

## Alternatives rejected

- Combining Godot + Bevy + PlayCanvas + Babylon.js + Three.js into a custom
  engine: these are alternative architectures (scene graphs, renderers, asset
  pipelines), not composable modules. We borrow designs/algorithms from them,
  never their runtimes. (See ADR 0002 and `docs/architecture/asha-platform-strategy.md`.)
- A launcher of separate games: fails the "same chain of events" test — a tank
  must be traceable from the miner who dug its iron to the FPS player who drove
  it.
