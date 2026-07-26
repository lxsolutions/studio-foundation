# GDScript pitfalls this repo has paid for

Each entry is a defect that shipped, hung a suite, or burned an hour of
debugging in this codebase or one of its consuming games. Symptom first, then
the mechanism, then the discipline that prevents it.

## A parse error in a preloaded script hangs a scene-based runner silently

**Symptom:** `just test-godot` (or a game's `test.cmd`) sits forever with no
output, no failure, no timeout.

**Mechanism:** a scene-based test runner only ever exits through
`get_tree().quit()`. If any script in its `preload` graph fails to parse, the
scene loads nothing, nothing calls quit, and the harness waits on a process
that will never finish.

**Discipline:** the runner prints `[tests] runner alive` before anything else.
If that marker is missing from a hung run, execute the same command bare and
read the first second of output — the parse error is there. Cheap insurance
before running a suite: `--check-only --script <file>` on every script you
touched. Expect false positives on scripts that reference project autoloads
(autoloads are not registered in a bare check); the suite is the true gate for
those.

## Headless MultiMesh per-instance data is write-only

**Symptom:** every `multimesh.get_instance_transform(i)` returns identity in a
headless run, while `instance_count` reads back correctly. Placement
assertions pass on a desktop and fail in CI, or vice versa.

**Mechanism:** under the dummy RenderingServer (`--headless`), MultiMesh
per-instance storage is stubbed. `set_instance_transform` is accepted and
discarded; there is no buffer to read back.

**Discipline:** game code that *reasons* about placement keeps its own
`Array[Transform3D]` per layer as the source of truth and treats the MultiMesh
as write-only render output. Tests assert on the stored arrays (and may still
assert `instance_count`, which survives headless). Found while dressing The
Deep's strata: three placement pins "failed" against a buffer that had never
stored anything.

## Instancing a GLB scene imports its collision too

**Symptom:** decorative props subtly change movement, AI pathing, or reach;
or a "visual-only" layer trips physics queries.

**Mechanism:** the Blender export convention names a second mesh
`<name>-convcol`, which Godot's importer converts into a StaticBody3D with a
convex collision shape inside the imported scene. `instantiate()` on the GLB's
PackedScene brings that body with it.

**Discipline:** presentation-only consumers never instantiate the prop scene.
Extract the visual surface (the MeshInstance3D whose name does not carry the
collision suffix) once, cache the `Mesh`, and draw it through
MultiMeshInstance3D or a bare MeshInstance3D — neither can collide. Keep a
test that asserts the dressing subtree contains no `CollisionObject3D`.

## `set_anchors_preset` places a control at the size it has *now*

**Symptom:** a code-built HUD element is centred (or edge-hugging) while
empty, then drifts as soon as real text arrives: labels walk off-centre,
panels grow out through the screen edge, "centred" overlays sit half their
own width to the right.

**Mechanism:** anchor presets compute offsets from the control's minimum size
*at the moment the preset is applied*. A control built in code is empty at
that moment; everything it later fills with expands away from the anchor
point, not around it.

**Discipline:** one pinning rule per edge: edge-anchored controls must grow
*inward*, centred overlays must grow *both ways*, and the assertion belongs in
a class-wide test that walks every registered HUD control rather than a
per-widget check (per-widget checks are exactly how the same defect shipped in
five more places). The Chariot Club HUD paid for this lesson roughly twenty
times.

## Sequential ids through a multiplicative hash correlate

**Symptom:** per-entity variation driven by `hash(id) % N` comes out in
lockstep — every horse gallops in phase, every corner of a room grows the same
prop.

**Mechanism:** neighboring integers times a large prime differ by that prime;
without avalanching, the low bits used by `% N` stay strongly correlated
across consecutive ids or grid coordinates.

**Discipline:** avalanche before windowing:

```gdscript
static func _cell_hash(x: int, y: int, salt: int) -> int:
    var h: int = x * 73856093 ^ y * 19349663 ^ salt * 83492791
    h = (h ^ (h >> 13)) * 1274126177
    return absi(h ^ (h >> 16))
```

and derive every windowed decision (`% 10` buckets, yaw, scale jitter) from
the avalanched value.

## `Dictionary.get()` cannot tell null from missing

**Symptom:** logic that stores `null` as a meaningful value silently takes the
default branch.

**Mechanism:** `dict.get(key, fallback)` returns `fallback` for a key that is
present with value `null` — the two cases are indistinguishable through
`get`.

**Discipline:** when `null` is a legal stored value, gate on `dict.has(key)`
first and only then read.
