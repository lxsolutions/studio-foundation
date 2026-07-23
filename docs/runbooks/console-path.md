# Runbook: Console path (Xbox, PlayStation, Nintendo)

**We do not port consoles ourselves.** Per ADR 0008 (own the distribution, never
the engine), console export goes through **Godot's licensed third-party console
paths** — the same route every small Godot studio uses. Console SDKs are private,
NDA-covered, and platform-holder-gated; maintaining our own backends for them is
exactly the engine-maintenance treadmill we deliberately avoid.

## Why this is the right call (and not a gap)

- Console SDKs/devkits require platform-holder approval (ID@Xbox, PlayStation
  Partners, Nintendo Developer) and signed NDAs. You cannot legally target them
  without that, regardless of engine.
- Godot's design keeps console support out of the open tree; licensed W4 Games
  and other approved porting houses provide the console backends and handle
  certification. Our "one shared project per game" (GOAL.md) means the same
  Godot project that ships browser/mobile/PC is the one a porting house takes
  to console — no separate console codebase to build or maintain.
- Our WebGPU/browser work does **not** transfer to consoles (they don't run
  browsers); console uses Godot's native Forward+/Mobile renderers, which our
  projects already support. The distribution layer (agent pipeline, backend interfaces, asset factory) is
  renderer-agnostic and carries over unchanged.

## The actual path (when a game justifies it)

1. **Get platform-holder approval first** (this gates everything):
   - **Xbox:** ID@Xbox program (id.xbox.com) — free for indie; GDK access after approval.
   - **PlayStation:** PlayStation Partners (partners.playstation.net) — application + concept review.
   - **Nintendo:** Nintendo Developer Portal (developer.nintendo.com) — application + devkit purchase.
2. **Choose a console backend provider:**
   - **W4 Games consoles** (W4 Consoles) — first-party-backed console ports of Godot.
   - Approved porting houses (e.g. those listed at godotengine.org/consoles) if
     you want a hands-on port rather than a self-serve SDK.
3. **Keep the project console-clean** (mostly already true here):
   - No browser-only APIs in shared gameplay code (we already isolate net/render
     behind interfaces per GOAL.md quality profiles).
   - GDScript-only gameplay (ADR 0003) — no C# in shared client code, which
     keeps console export straightforward.
   - Deterministic input (StudioInputMap) so console controllers map cleanly.
4. **Cert requirements to design for early** (cheap now, expensive later):
   - Save-game robustness (we have versioned `save_data` + schema rejection).
   - Suspend/resume handling, offline play, and platform TRC/XR requirements.
   - Performance budgets per console profile (mobile_low is a good proxy to start).

## What we will NOT do

- Maintain our own Xbox/PlayStation/Nintendo export backends.
- Put console SDK code, keys, or NDA material in this open repository.
- Claim console "support" before a real device run — per BOOTSTRAP_REPORT.md's
  honest-status policy, console is **documented, not evidenced** until a game
  ships on one through a licensed path.

## Near-term evidence bar

Console stays a documented path until a game warrants the platform-holder
applications. The cheapest real evidence first: a **Steam Deck / PC-console-style
run** (native Linux export, controller input) — no NDA, validates the controller +
performance model that console cert will demand.
