# Vertical Slice: The Closed-Loop Campaign Sector

The first milestone of the unified world (ADR 0007). Not the whole universe — one
loop that proves the entire concept.

## The loop

12 players supported; must also work with 1 player plus bots.

1. A commander needs alloy to build an armored unit.
2. A mining contract appears in Plato's Plaza.
3. A player enters The Deep.
4. They mine ore, fight an enemy, and return with cargo.
5. A refinery converts the ore.
6. The factory completes one vehicle.
7. A small RTS battle begins over a nearby outpost.
8. A player can directly drive the vehicle or fight beside it.
9. Winning the battle captures the outpost.
10. The captured outpost unlocks a deeper mine entrance.

```
Extraction → economy → production → strategy
→ embodied battle → territorial consequence
→ new extraction opportunity
```

## What this proves

- Canonical world events flow through the Rust simulation into PostgreSQL.
- A Godot client can participate at three scales (Deep action, strategic command,
  battlefield) against the same world state.
- AI fills vacant roles so the loop never stalls on missing humans.
- The tank has a traceable history: mined → refined → manufactured → deployed →
  driven → destroyed/recovered/captured.

## Non-goals for the slice

- Multiple sectors, factions, or planets.
- Full profession/puzzle suite.
- Browser-native WebGPU polish (WebGL fallback is acceptable for the slice).
- Mobile clients.

## Timescales exercised

- Immediate (seconds/minutes): mining, combat, driving.
- Operational (20–90 min): the expedition and the outpost battle.
- Strategic (days/weeks): stubbed — territory flip and mine unlock only.
