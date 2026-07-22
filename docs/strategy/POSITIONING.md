# Positioning: Transcend, Don't Shed

Status: accepted strategic posture (2026-07-21). Complements ADR 0008 (own the
distribution, never the engine) and the master thesis
([AI_NATIVE_PLATFORM.md](AI_NATIVE_PLATFORM.md)).

## The question

Do we ever shed Godot — the engine, or parts of it — or shed the association?

## The answer

**Never shed the engine. Always transcend the label.**

### Why shedding Godot loses

Shedding Godot means taking on the exact maintenance surface ADR 0008 refuses:
the editor, scene system, animation, UI, importers, physics, and the
platform/console export layer. The moment we shed it, we stop being a game
studio with an unfair advantage and become an engine company with a crushing
obligation — every hour that should go into our differentiator goes into
tracking Godot's own releases. That is how open-source engine forks die.

Godot is the **commodity we borrow**; the distribution is the **moat we own**.
Shedding the commodity is the one move that destroys the moat.

### What we actually shed: the perception that Godot is the product

"studio-foundation" reading as "a Godot project with extras" is a positioning
liability. What we are really building is an **AI-native production reality** —
the world-sim, the agent contract (studio-mcp + skills + validation gates), the
asset factory, the WebGPU backend — that *happens to use Godot as its renderer
and editor*. Godot is an implementation detail, the way a compiler is an
implementation detail. **We shed the brand, never the engine.**

### Leveraging Godot's reputation: the arc

- **Short term:** "Godot WebGPU that actually works" is a credible, searchable,
  valuable claim. Use it. It on-ramps the Godot community.
- **Long term:** do not stay "the Godot WebGPU people." That is a ceiling and it
  ties our fate to Godot's roadmap instead of our own.
- **The arc:** start as *the team that made Godot WebGPU real* (credibility,
  adoption) → become *the AI-native game platform* (what people actually choose
  us for). The engine is the on-ramp, not the destination.

## The open-source play (and what CC BY 4.0 is really for)

Attribution is the floor, not the goal. The real reasons the platform is open
(while games stay proprietary), in order of actual value:

1. **Adoption → feedback → contributions → durability.** An open platform gets
   other people's fixes, ports, and trust — how Godot itself won. CC BY
   attribution makes that adoption visible and credit-bearing; nice, but least.
2. **The standard.** If the agent-operable contract (MCP tools, validation
   gates, world-event schema) becomes *the way* AI-native games are made, we own
   the standard. Standards outlast any single game. Unity won by being the
   default, not the best.
3. **The world.** The defensible, unreplicable asset is the **one persistent
   world** (ADR 0007) games plug into. The platform can be copied; a living
   world with players in it cannot. **Open platform is the funnel; the world is
   the moat.**

So: open the engine + platform (dual MIT + CC BY 4.0) to maximize adoption and
become the standard; keep the games and the world proprietary — that is where
the money and the defensibility live.

## One-breath strategy

> Borrow the commodity engine (Godot), own the agent-operable distribution and
> the world, win the browser because incumbents can't reach it, become the
> standard AI-native platform, and let the proprietary games and world be where
> the value compounds.

**Nothing is shed except the perception that Godot is the point.**
