# bforge op reference

121 operations.

## `arch.*`

### `arch.arcade`

A wall of repeating arched bays following a path — THE Roman building block. Stack these to turn a stadium bowl into a colosseum, or run one along a line for an aqueduct or a cloister. Bays are spaced by arc length so an oval colonnade stays even through the turns.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'arcade' | Object name |
| `path` | array | [] | Flat [x0,y0,z0, ...] path; leave empty and use path_shape |
| `path_shape` | custom \| oval \| circle \| line \| arc | 'oval' | Built-in path generator |
| `straight` | number | 40.0 | oval: length of each straight in metres |
| `radius` | number | 20.0 | oval/circle/arc radius in metres |
| `length` | number | 30.0 | line: total length in metres along X |
| `arc_degrees` | number | 180.0 | arc: sweep angle in degrees |
| `resolution` | integer | 48 | Path sampling resolution |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 3.0 | Metres per UV tile |
| `z` | number | 0.0 | Base height in metres |
| `bays` | integer | 32 | Number of arched openings around the path |
| `height` | number | 9.0 | Storey height in metres, plinth to cornice |
| `thickness` | number | 1.6 | Wall depth in metres |
| `opening` | number | 0.58 | Fraction of each bay that is opening rather than pier (0.3-0.75) |
| `arch_rise` | number | 0.0 | Height of the arch semicircle; 0 makes it a true semicircle (half the opening width) |
| `springing` | number | 0.42 | Height where the arch starts, as a fraction of storey height |
| `voussoirs` | integer | 7 | Segments per arch — 7 reads as an arch, more is wasted at distance |
| `plinth` | number | 0.5 | Base band height in metres |
| `cornice` | number | 0.6 | Top band height in metres |
| `cornice_jut` | number | 0.35 | How far the cornice projects past the wall |
| `engaged_columns` | boolean | True | Half-columns on the piers — the Colosseum's storey articulation |

### `arch.civic_hall`

A complete classical town centre in one joined, material-disciplined asset: stepped masonry masses, pedimented portico, tiled gable roofs, buttresses, windows and faction banner. The greek_mine style adds an arched shaft mouth and working timber headframe/hoist, making an RTS civic centre that is also credible at first-person distance. Optional mine_yard geometry extends the shaft into a stone loading apron, rails, sleepers and a loaded ore cart.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'civic_hall' | Object name |
| `style` | greek_mine \| greek_polis | 'greek_mine' | Architecture programme |
| `width` | number | 10.4 | Overall facade width in metres |
| `depth` | number | 8.4 | Overall building depth in metres |
| `height` | number | 6.8 | Height to the upper roof eaves |
| `columns` | integer | 6 | Doric columns across the front portico |
| `tile_rows` | integer | 7 | Raised tile bands across each major roof |
| `mine_portal` | boolean | True | Add an arched mine mouth through the facade |
| `hoist` | boolean | True | Add the timber headframe, wheel, spokes, axle and rope |
| `mine_yard` | boolean | False | Extend the mine into a working forecourt with apron, rails and sleepers |
| `portal_scale` | number | 1.0 | Mine-mouth width multiplier (0.85-1.55) |
| `rail_length` | number | 4.8 | Mine-yard rail length beyond the portal in metres |
| `ore_cart` | boolean | True | Place a timber-and-metal ore cart on mine-yard rails |
| `stone_color` | string | '#817765' | Primary weathered masonry |
| `foundation_color` | string | '#4c4841' | Podium, courses and buttress stone |
| `roof_color` | string | '#552c24' | Dark terracotta tile |
| `timber_color` | string | '#2b1d16' | Mine framing and doors |
| `metal_color` | string | '#61441f' | Bronze/iron fittings |
| `cloth_color` | string | '#4a2024' | Faction banner |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `rotation` | number | 0.0 | Yaw in degrees |
| `uv_scale` | number | 1.4 | Metres per UV tile |

### `arch.colonnade`

A ring or run of free-standing columns with an entablature — temple fronts, stadium rims, forum porticos. Cheaper than an arcade and the right silhouette for a top storey.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'arcade' | Object name |
| `path` | array | [] | Flat [x0,y0,z0, ...] path; leave empty and use path_shape |
| `path_shape` | custom \| oval \| circle \| line \| arc | 'oval' | Built-in path generator |
| `straight` | number | 40.0 | oval: length of each straight in metres |
| `radius` | number | 20.0 | oval/circle/arc radius in metres |
| `length` | number | 30.0 | line: total length in metres along X |
| `arc_degrees` | number | 180.0 | arc: sweep angle in degrees |
| `resolution` | integer | 48 | Path sampling resolution |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 3.0 | Metres per UV tile |
| `z` | number | 0.0 | Base height in metres |
| `columns` | integer | 40 | Number of columns |
| `height` | number | 6.5 | Column height in metres |
| `column_radius` | number | 0.42 | Shaft radius |
| `segments` | integer | 8 | Sides per column |
| `entablature` | number | 0.9 | Depth of the beam carried across the tops; 0 for none |
| `flutes` | boolean | False | Fluted shafts (costs triangles, only reads up close) |
| `statues` | boolean | False | Blocky statue silhouettes above every fourth column |

### `arch.defense_tower`

A browser-budget classical Greek defense tower with one disciplined material set and three gameplay-readable silhouettes: an elevated arrow crown, a horizontal torsion ballista, or a vertical bronze storm conductor. All variants share stepped weathered masonry, battered buttresses, string courses and oxblood faction cloth.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'defense_tower' | Object name |
| `style` | arrow \| ballista \| storm | 'arrow' | Weapon and crown silhouette |
| `width` | number | 3.0 | Overall masonry footprint width in metres |
| `height` | number | 5.2 | Overall structure height before the weapon crown |
| `stone_color` | string | '#777064' | Primary weathered limestone |
| `foundation_color` | string | '#403e3a' | Podium, buttress and course stone |
| `timber_color` | string | '#2a1c14' | Weapon frame, canopy and rails |
| `metal_color` | string | '#72502a' | Bronze and dark iron fittings |
| `cloth_color` | string | '#491c20' | Oxblood faction cloth |
| `energy_color` | string | '#7e9ca3' | Restrained storm conductor emission |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `rotation` | number | 0.0 | Yaw in degrees |
| `uv_scale` | number | 0.9 | Metres per UV tile |

### `arch.dock`

A serious Aegean working harbour: stepped limestone quay, timber pier, waterline piles, bollards, cargo and a bronze-hooped loading crane. The landward apron and waterward pier read from RTS and first-person cameras.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'aegean_dock' | Object name |
| `width` | number | 7.5 | Shore-parallel width in metres |
| `depth` | number | 8.5 | Land-to-water depth in metres |
| `height` | number | 2.5 | Highest crane point in metres |
| `stone_color` | string | '#777064' | Weathered limestone quay |
| `foundation_color` | string | '#3b3935' | Wet foundation and shadow stone |
| `timber_color` | string | '#332117' | Pier, crane and cargo timber |
| `metal_color` | string | '#6f512e' | Bronze hoops, chain and fittings |
| `cloth_color` | string | '#4b2522' | Restrained painted harbour marker |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `rotation` | number | 0.0 | Yaw in degrees; pier points toward -Y |
| `uv_scale` | number | 0.75 | Metres per UV tile |

### `arch.field_building`

A browser-budget Greek settlement family for the structures surrounding a civic hall: a furrowed farmstead, strategos campaign tent, hoplite barracks, delver household, mining emporium, survey lattice, modular ashlar wall, or weathered road stele. Variants share restrained limestone, timber, cloth, terracotta, bronze and crop materials while keeping silhouettes readable from an RTS camera.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'field_building' | Object name |
| `style` | farm \| camp \| barracks \| house \| emporium \| lattice \| wall \| waymarker | 'farm' | Settlement structure silhouette |
| `width` | number | 3.4 | Overall footprint width in metres |
| `depth` | number | 3.4 | Overall footprint depth in metres |
| `height` | number | 2.2 | Authored visual height in metres |
| `stone_color` | string | '#777064' | Primary weathered limestone |
| `foundation_color` | string | '#403e3a' | Podium, earth and shadow stone |
| `timber_color` | string | '#2a1c14' | Posts, doors, racks and tools |
| `roof_color` | string | '#552c24' | Muted terracotta roof and painted details |
| `metal_color` | string | '#72502a' | Bronze and dark iron fittings |
| `crop_color` | string | '#525632' | Olive, grain and restrained field growth |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `rotation` | number | 0.0 | Yaw in degrees |
| `uv_scale` | number | 0.7 | Metres per UV tile |

### `arch.gateway`

A monumental arched gate — the triumphal entrance every Roman venue frames its far end with. One big central arch, optional flanking arches, an attic storey above.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'gateway' | Object name |
| `width` | number | 14.0 | Overall width in metres |
| `height` | number | 16.0 | Overall height in metres |
| `thickness` | number | 3.0 | Depth in metres |
| `side_arches` | boolean | True | Smaller arches either side of the main opening |
| `attic` | number | 4.0 | Attic storey height above the cornice; 0 for none |
| `voussoirs` | integer | 9 | Segments in the main arch |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `rotation` | number | 0.0 | Yaw in degrees |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 3.0 | Metres per UV tile |

## `build.*`

### `build.array`

Repeat an object along a vector, or in a 2D/3D grid. Fences, columns, pipes, city blocks, crowd props.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object to repeat |
| `counts` | array | [3] | Repeat count per axis, e.g. [5] or [4,4] or [3,3,2] |
| `spacing` | array | [1.0, 1.0, 1.0] | Distance between copies in metres |
| `join` | boolean | True | Merge into a single mesh (fewer draw calls) |

### `build.bevel`

Chamfer an object's sharp edges. The single highest-impact polish step for hard-surface props.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `width` | number | 0.015 | Chamfer width in metres |
| `segments` | integer | 2 | Chamfer resolution |
| `angle` | number | 30.0 | Only bevel edges sharper than this (degrees) |

### `build.box`

Chamfered box. The chamfer is what makes a box read as a solid object under game lighting instead of a flat card.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'box' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | False | Smooth shading with a sharp-edge threshold |
| `size` | array | [1.0, 1.0, 1.0] | Outer dimensions in metres |
| `bevel` | number | 0.02 | Chamfer width in metres; 0 disables |
| `bevel_segments` | integer | 2 | Chamfer resolution (2 is plenty for game assets) |

### `build.cleanup`

Weld duplicate vertices and optionally dissolve coplanar faces. Run before measuring or exporting.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `merge_distance` | number | 0.0001 | Weld threshold in metres |
| `dissolve_flat` | boolean | False | Merge coplanar faces (cuts triangles, can create n-gons) |

### `build.cylinder`

Cylinder, cone or truncated cone (set radius_top). Pillars, pipes, barrels, tent poles.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'cylinder' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | True | Smooth shading (usually right for round shapes) |
| `radius` | number | 0.5 | Bottom radius in metres |
| `radius_top` | number | -1.0 | Top radius; -1 means same as bottom, 0 makes a cone |
| `depth` | number | 1.0 | Height in metres |
| `segments` | integer | 16 | Radial segments — 12-16 is the game-asset sweet spot |
| `cap` | boolean | True | Close the ends |
| `bevel` | number | 0.0 | Chamfer the rim edges |

### `build.deform`

Taper, twist or noise-displace a mesh. Turns generic primitives into things with character.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `mode` | taper \| noise \| jitter \| squash | 'taper' | Deformation type |
| `amount` | number | 0.5 | taper: top scale factor. noise/jitter: displacement in metres. squash: Z scale |
| `frequency` | number | 3.0 | noise: spatial frequency |
| `seed` | integer | 0 | Random seed |

### `build.extrude`

Inset-and-extrude faces selected by their normal direction. Makes panels, ledges, windows and recesses.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `direction` | up \| down \| north \| south \| east \| west \| all \| outward | 'up' | Which faces to affect |
| `distance` | number | 0.1 | Extrude distance in metres (negative recesses) |
| `inset` | number | 0.05 | Inset before extruding — this is what makes a panel not a spike |
| `threshold` | number | 0.7 | Normal alignment required to count as facing that direction |

### `build.greeble`

Scatter panel detail across faces — sci-fi hulls, machinery, city blocks, tech walls. Deterministic for a given seed.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `seed` | integer | 0 | Random seed; same seed gives the same result forever |
| `density` | number | 0.35 | Fraction of faces that get a panel (0..1) |
| `depth` | number | 0.03 | Maximum panel depth in metres |
| `cuts` | integer | 1 | Subdivision passes before panelling — more cuts, finer greeble |

### `build.lathe`

Revolve a 2D profile into a solid. The highest value-per-parameter op here: bottles, vases, columns, goblets, chess pieces, tree trunks, fountains.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'cylinder' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | True | Smooth shading |
| `profile` | array | None | Flat [radius0, height0, radius1, height1, ...] pairs, bottom to top |
| `segments` | integer | 16 | Radial segments |

### `build.mirror`

Mirror geometry across an axis. Halves the modelling work for anything symmetrical — characters, vehicles, buildings.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `axis` | X \| Y \| Z | 'X' | Mirror axis |

### `build.plane`

Flat quad, optionally grid-subdivided. Floors, walls, water, billboards, terrain bases.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'box' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | False | Smooth shading with a sharp-edge threshold |
| `size` | array | [1.0, 1.0] | Dimensions in metres |
| `cuts` | integer | 0 | Grid subdivisions per edge |

### `build.prism`

N-sided prism. Hex tiles, crystals, columns, low-poly trunks.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'box' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | False | Smooth shading with a sharp-edge threshold |
| `radius` | number | 0.5 | Circumradius in metres |
| `depth` | number | 1.0 | Height in metres |
| `sides` | integer | 6 | Number of sides |

### `build.sphere`

UV sphere or icosphere. Icospheres have even topology and are better bases for rocks and organic shapes.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'smart' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | True | Smooth shading |
| `radius` | number | 0.5 | Radius in metres |
| `kind` | uv \| ico | 'ico' | Topology type |
| `segments` | integer | 16 | UV sphere: radial segments |
| `rings` | integer | 8 | UV sphere: vertical rings |
| `subdivisions` | integer | 2 | Icosphere: subdivision level (2 = 320 tris) |

### `build.subdivide`

Subdivide all faces. Use sparingly — subdivision multiplies triangles fast.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `cuts` | integer | 1 | Cuts per edge |
| `smooth` | number | 0.0 | Smoothing factor (0 keeps the silhouette) |

### `build.sweep`

Sweep a 2D cross-section along a path — the workhorse for level geometry. Racetracks, grandstands, roads, ramparts, rails, tunnels, mouldings and pipes are all one profile plus one path. Frames use parallel transport, so a closed loop does not twist.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'box' | UV strategy |
| `uv_scale` | number | 4.0 | Metres per UV tile |
| `origin` | bottom \| center \| center_xy \| world | 'world' | Pivot placement |
| `smooth` | boolean | False | Smooth shading |
| `profile` | array | None | Flat [lateral0, vertical0, lateral1, vertical1, ...] cross-section in metres, relative to the path |
| `profile_scales` | array | [] | Flat [lateral0, vertical0, ...] multipliers applied to the cross-section ALONG the path, interpolated to fit. This is what turns a uniform tube into an anatomy — a barrel that swells at the girth, a neck that tapers to the poll. Give a few key values, not one per point |
| `path` | array | [] | Flat [x0,y0,z0, x1,y1,z1, ...] path points; leave empty and use path_shape instead |
| `path_shape` | custom \| oval \| circle \| line \| arc | 'custom' | Built-in path generator |
| `straight` | number | 40.0 | oval: length of each straight in metres |
| `radius` | number | 12.0 | oval/circle/arc radius in metres |
| `length` | number | 20.0 | line: total length in metres along X |
| `arc_degrees` | number | 180.0 | arc: sweep angle in degrees |
| `segments` | integer | 24 | Path resolution (per turn for an oval) |
| `closed_path` | boolean | True | Close the path into a loop (oval and circle are always closed) |
| `closed_profile` | boolean | True | Treat the cross-section as a closed outline (a solid tube) rather than an open strip |

### `build.torus`

Torus. Rings, handles, hoops, portal frames.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'smart' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | True | Smooth shading |
| `major` | number | 0.5 | Ring radius in metres |
| `minor` | number | 0.12 | Tube radius in metres |
| `major_segments` | integer | 20 | Segments around the ring |
| `minor_segments` | integer | 8 | Segments around the tube |

### `build.wedge`

Right-triangle prism. Ramps, roof sections, chamfer blockouts.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'part' | Object name (coerced to snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `material` | string | 'stone' | Material preset name, or '' for none. See meta.palette |
| `color` | string | '' | Override colour: palette name or #rrggbb |
| `uv` | box \| cylinder \| smart \| smart_packed \| none | 'box' | UV strategy |
| `uv_scale` | number | 1.0 | Metres per UV tile for box projection |
| `origin` | bottom \| center \| center_xy \| world | 'center' | Pivot placement |
| `smooth` | boolean | False | Smooth shading with a sharp-edge threshold |
| `size` | array | [1.0, 1.0, 1.0] | Bounding dimensions in metres |

## `char.*`

### `char.animate`

Author a keyframed animation clip on a rig: idle, walk, run, attack, jump, death or wave. Real pose-to-pose keys at contact/passing frames, not sine-wave wiggle — the difference between a walk and a shuffle.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `rig` | string | None | Armature object name (from char.rig) |
| `clip` | idle \| walk \| run \| attack \| jump \| death \| wave | 'idle' | Which clip to author |
| `length` | integer | 24 | Clip length in frames (24 frames at 30 fps = 0.8 s) |
| `amplitude` | number | 1.0 | Motion scale — 0.6 is subtle, 1.4 is exaggerated |
| `loop` | boolean | True | Match the last frame to the first so the clip cycles |
| `action_name` | string | '' | Action name (defaults to the clip name) |

### `char.attach`

Parent a prop to a character bone — a sword to hand_r, a shield to hand_l, a helmet to head. Keeps the prop's own pivot, so it animates with the character.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `prop` | string | None | Object to attach |
| `rig` | string | None | Armature object name |
| `bone` | string | 'hand_r' | Bone to attach to |
| `offset` | array | [0.0, 0.0, 0.0] | Local offset in metres |
| `rotation` | array | [0.0, 0.0, 0.0] | Local rotation in degrees |
| `keep_transform` | boolean | False | Keep the prop exactly where it already is, ignoring offset/rotation |

### `char.bake_pose`

Freeze a posed rig into the mesh vertices and drop the skin. Turns a char.rig + char.pose result into a plain static mesh that keeps the pose through export — for background figures, props and NPCs that never animate.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `mesh` | string | None | Skinned mesh object to freeze |
| `rig` | string | None | Armature to delete afterwards (default: the one deforming this mesh; pass "" to keep it) |
| `keep_groups` | boolean | False | Keep the vertex groups after baking |

### `char.humanoid`

Animation-ready anatomical humanoid using classic figure-drawing head ratios (7.5 realistic, 8 heroic, 4 chibi). Shaped chest/waist depth, jaw, nose, ears, hands and feet avoid the tube-limbed mannequin look. Pair with char.outfit, char.rig and char.animate.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'character' | Object name |
| `height` | number | 1.8 | Total height in metres |
| `build` | realistic \| heroic \| stylized \| chibi \| lithe | 'heroic' | Body proportions |
| `bulk` | number | 1.0 | Extra muscle/armour thickness multiplier |
| `detail` | integer | 8 | Limb cross-section segments (6-10 is the game range) |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `skin` | string | '#c08a6a' | Body colour |
| `seed` | integer | 0 | Random seed |

### `char.outfit`

Add a production-readable rigid outfit to an unrigged humanoid, then join it into the body so char.rig skins every shell. Greek delver, hoplite and peltast armour include cuirass, straps, pteruges, helmets, bracers and greaves; toxotes and hypaspist provide RTS-readable archer and heavy-guard silhouettes; strategos and warlock add boss-readable officer and ritual silhouettes; stalker and oracle add undead hoods, masks and robes.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Unrigged humanoid mesh from char.humanoid |
| `style` | greek_delver \| hoplite \| peltast \| toxotes \| hypaspist \| strategos \| stalker \| oracle \| warlock | 'greek_delver' | Outfit silhouette |
| `cloth` | string | '#262522' | Coarse tunic/linen colour |
| `leather` | string | '#38261c' | Straps, belt and boot-wrap colour |
| `metal` | string | '#71502d' | Aged bronze armour colour |
| `accent` | string | '#d18a32' | Small lamp or crest accent |
| `detail` | integer | 10 | Radial segment count, 8-16 |

### `char.pose`

Set a static pose on a rig — T-pose, A-pose, sitting, or a custom per-bone rotation. Useful for reference renders and for fixing an import rest pose.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `rig` | string | None | Armature object name |
| `preset` | rest \| a_pose \| t_pose \| sit \| crouch \| custom | 'a_pose' | Pose preset |
| `bones` | object | None | custom only: {"bone_name": [rx, ry, rz], ...} in degrees |

### `char.rig`

Build a humanoid armature fitted to a mesh and skin it with distance-falloff weights. Single 'hips' root, snake_case bone names, glTF/Godot-compatible. No GUI needed.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Mesh object to rig |
| `height` | number | 0.0 | Character height; 0 measures it from the mesh bounds |
| `build` | realistic \| heroic \| stylized \| chibi \| lithe | 'heroic' | Proportions the rig assumes — match char.humanoid |
| `falloff` | number | 1.6 | Weight blend sharpness; higher is more rigid |
| `armature_name` | string | '' | Armature object name (defaults to <mesh>_rig) |

### `char.skeleton`

Build an anatomically readable bone-body on the same proportions as char.humanoid. The joined rib cage, skull, long bones and dark sockets remain compatible with char.outfit, char.rig and char.animate.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'skeleton' | Object name |
| `height` | number | 1.86 | Total height in metres |
| `build` | realistic \| heroic \| lithe | 'lithe' | Bone proportions |
| `detail` | integer | 8 | Bone cross-section segments, 6-12 |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `bone` | string | '#b8ad92' | Aged bone colour |
| `socket` | string | '#171817' | Eye, nose and mouth cavity colour |
| `seed` | integer | 0 | Random seed |

## `check.*`

### `check.asset`

Run the studio's ADR 0006 asset rules against the open scene: naming, units, applied transforms, origins, UVs, budgets, bone conventions, collision, textures, glTF-safe shaders. Same checks as `just asset-validate`, but before you write the file.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `triangle_budget` | integer | 2000 | Triangle ceiling for the check |
| `material_budget` | integer | 2 | Material ceiling |
| `require_collision` | boolean | False | Fail when no -col/-convcol proxy exists |
| `require_lods` | boolean | False | Fail when no _lod1 object exists |

### `check.critique`

Quality critique with specific, actionable findings: topology and UV faults, texel-density drift, unused slots, and natural rock that never received a textured or layered surface. Pair it with render.contact_sheet — numbers plus eyes.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `objects` | array | [] | Objects to critique (empty = every mesh) |
| `texture_size` | integer | 1024 | Texture resolution the texel-density figures assume |

### `check.image`

Measure an image instead of eyeballing it: luminance range, blown highlights, crushed blacks, contrast, saturation, dominant colours and subject coverage. Reading a render is slow and cannot tell 'the asset is wrong' from 'the render is over-lit'. These numbers can, in a fraction of the time.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `path` | string | None | PNG, JPEG or WebP to analyse — a render, sprite sheet, contact sheet, or baked texture |
| `colors` | integer | 6 | How many dominant colours to report |
| `background` | array | [0.05, 0.055, 0.065, 1.0] | Backdrop colour, excluded from subject stats |
| `require_alpha` | boolean | False | Fail when the image has no meaningful transparent pixels |
| `require_clear_corners` | boolean | False | Fail when the four corners are not transparent; useful for UI icons and cutouts |
| `require_square` | boolean | False | Fail when width and height differ |
| `minimum_size` | integer | 0 | Fail when either image dimension is below this many pixels (0 disables) |
| `minimum_coverage` | number | 0.04 | Minimum fraction of the frame occupied by the visible subject |
| `maximum_coverage` | number | 1.0 | Maximum fraction of the frame occupied by the visible subject |

### `check.silhouette`

Score how readable an object's silhouette is from the standard game camera angles. A prop that fails here will not read at gameplay distance no matter how good its texture is.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object to test |
| `samples` | integer | 64 | Rays per axis for the projected-area estimate |

## `creature.*`

### `creature.hound`

Build a gaunt game-ready war hound with readable canine anatomy, bent legs, muzzle, ears, segmented tail and a separate bronze collar. The joined mesh can be exported static or bound to a custom quadruped rig.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'war_hound' | Object name |
| `length` | number | 1.75 | Nose-to-rump length in metres |
| `shoulder_height` | number | 1.0 | Ground-to-shoulder height |
| `bulk` | number | 1.0 | Torso and limb thickness multiplier |
| `detail` | integer | 8 | Radial segment count, 6-12 |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `hide` | string | '#25231f' | Dark hide colour |
| `leather` | string | '#3b241c' | Collar leather colour |
| `metal` | string | '#6f4d2b' | Collar and spike metal colour |
| `eyes` | string | '#9b5428' | Eye colour |

### `creature.scarab`

Build a low, wide carrion scarab with layered segmented shell plates, six bent legs, hooked forelimbs and mandibles. The joined multi-material mesh is readable from an isometric camera and ready for a custom rig.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'carrion_scarab' | Object name |
| `length` | number | 1.55 | Mandible-to-abdomen length in metres |
| `width` | number | 0.95 | Maximum shell width |
| `height` | number | 0.62 | Maximum shell height |
| `detail` | integer | 8 | Radial segment count, 6-12 |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `shell` | string | '#4e3925' | Aged shell colour |
| `edge` | string | '#84603a' | Raised shell-edge colour |
| `body` | string | '#171715' | Underside and leg colour |
| `eyes` | string | '#8d3f22' | Eye colour |

## `env.*`

### `env.amphitheatre`

A complete Roman venue in one call: raked cavea, podium, arched arcade storey, statued attic colonnade, vomitoria stair wedges, velarium masts, hanging banners and gateways. This is the difference between a stone bowl and the Colosseum — arches and vertical rhythm. Use shape='oval' for a circus/hippodrome, 'circle' for an amphitheatre.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'amphitheatre' | Object name |
| `shape` | oval \| circle | 'circle' | oval = circus/hippodrome, circle = amphitheatre |
| `arena_radius` | number | 40.0 | Arena half-width in metres (short axis) |
| `straight` | number | 0.0 | oval only: length of each straight in metres |
| `arena_margin` | number | 6.0 | Flat run-off between the arena edge and the podium wall |
| `podium_height` | number | 4.0 | Height of the solid wall between arena and first seats |
| `tiers` | integer | 3 | Seating tiers (maenianum), separated by walkway walls |
| `tier_depth` | number | 9.0 | Depth of each tier in metres |
| `tier_rise` | number | 5.4 | Height gained across each tier |
| `tier_riser` | number | 2.4 | Walkway wall height between tiers |
| `rows_per_tier` | integer | 7 | Seat steps cut per tier |
| `arcade_height` | number | 9.5 | Height of the arched storey crowning the stands; 0 for none |
| `arcade_bays` | integer | 0 | Arch count; 0 auto-sizes to roughly one arch per 8 m |
| `colonnade` | boolean | True | Statued attic colonnade above the arcade |
| `vomitoria` | integer | 0 | Stair wedges dividing the seating; 0 auto-sizes |
| `masts` | integer | 0 | Velarium masts on the rim; 0 auto-sizes, -1 for none |
| `gateways` | integer | 2 | Monumental arched gates cut through the podium |
| `banners` | integer | 0 | Hanging banners between arcade bays; 0 auto-sizes |
| `stone` | string | '#d6c4a0' | Sunlit stone colour (travertine, not concrete) |
| `stone_shade` | string | '#9c8763' | Shadowed stone colour |
| `sand` | string | '#d9bd8e' | Arena floor colour |
| `banner_color` | string | '#7a201a' | Banner cloth colour |
| `quality` | low \| medium \| high | 'medium' | Path and detail resolution |
| `join` | boolean | True | Merge into one object |
| `seed` | integer | 0 | Random seed |

### `env.arena`

Complete combat arena in one call: floor, tiered walls, entrance arches and corner towers. A whole playable space from a single op.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'arena' | Object name |
| `radius` | number | 16.0 | Arena floor radius in metres |
| `wall_height` | number | 6.0 | Perimeter wall height |
| `sides` | integer | 16 | Perimeter segments (higher is rounder) |
| `entrances` | integer | 2 | Number of gate openings |
| `tiers` | integer | 2 | Spectator tiers stepping up behind the wall |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 3.0 | Metres per UV tile |
| `seed` | integer | 0 | Random seed |

### `env.cliff`

Rock cliff wall or canyon face with stratified layers. Blocks sightlines and frames a play space without the cost of terrain.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'cliff' | Object name |
| `length` | number | 20.0 | Length along X in metres |
| `height` | number | 8.0 | Height in metres |
| `depth` | number | 3.0 | Depth variation in metres |
| `segments` | integer | 20 | Horizontal segments |
| `layers` | integer | 6 | Vertical strata |
| `strata` | number | 0.35 | How pronounced the rock layering is |
| `seed` | integer | 0 | Random seed |
| `material` | string | 'rock' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 3.0 | Metres per UV tile |

### `env.road`

Road, path or river bed following a polyline, conformed to a terrain surface if given.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'road' | Object name |
| `points` | array | [-15.0, 0.0, 0.0, 0.0, 15.0, 6.0] | Flat [x0,y0, x1,y1, ...] control points |
| `width` | number | 3.0 | Road width in metres |
| `target` | string | '' | Terrain to drape onto (empty = flat at Z=0) |
| `offset` | number | 0.06 | Height above the surface, to avoid z-fighting |
| `segments_per_span` | integer | 8 | Subdivisions between control points |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 3.0 | Metres per UV tile |
| `seed` | integer | 0 | Random seed |

### `env.scatter`

Scatter copies of an object over a surface with Poisson-ish spacing, aligned to the surface normal. The op that turns bare terrain into a forest, a rockfield or a graveyard.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `source` | string | None | Object to scatter |
| `target` | string | '' | Surface to scatter onto (empty = scatter on the Z=0 plane) |
| `count` | integer | 30 | Number of instances to attempt |
| `area` | array | [20.0, 20.0] | Scatter area in metres when there is no target |
| `min_spacing` | number | 1.2 | Minimum distance between instances |
| `scale_range` | array | [0.75, 1.35] | Random uniform scale range |
| `align_to_normal` | number | 0.0 | 0 = always upright, 1 = fully follow the surface tilt |
| `max_slope` | number | 40.0 | Skip spots steeper than this (degrees) |
| `seed` | integer | 0 | Random seed |
| `join` | boolean | True | Merge into one mesh — critical for draw calls |
| `name` | string | '' | Name for the merged result |

### `env.terrain`

Heightfield terrain with fBm noise, optional plateaus and erosion-like smoothing. Deterministic across machines, so CI can regenerate and diff it.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'terrain' | Object name |
| `size` | array | [40.0, 40.0] | Terrain extents in metres |
| `resolution` | integer | 48 | Grid subdivisions per side (48 = ~4600 tris) |
| `height` | number | 5.0 | Peak-to-trough height in metres |
| `scale` | number | 0.12 | Noise frequency — lower is broader hills |
| `octaves` | integer | 4 | Noise detail levels |
| `style` | hills \| mountains \| plateau \| dunes \| island | 'hills' | Terrain character |
| `flatten_center` | number | 0.0 | Radius in metres of a flat buildable area at the origin |
| `seed` | integer | 0 | Random seed |
| `material` | string | 'sand' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 4.0 | Metres per UV tile |

### `env.water`

Water plane with a gentle wave mesh and a translucent material. Fills moats, lakes and canals.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'water' | Object name |
| `size` | array | [30.0, 30.0] | Extents in metres |
| `resolution` | integer | 16 | Grid subdivisions |
| `wave_height` | number | 0.08 | Wave amplitude in metres |
| `level` | number | 0.0 | Z height of the water surface |
| `color` | string | '#20465e' | Water colour |
| `seed` | integer | 0 | Random seed |

## `export.*`

### `export.asset`

One call: save the .blend master, export the GLB, write the .meta.json sidecar and render a contact sheet. The complete hand-off for a finished asset.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `asset_id` | string | None | snake_case asset identifier — names every output file |
| `out_dir` | string | '' | Directory for the outputs (defaults to the session output dir) |
| `objects` | array | [] | Objects to export (empty = whole scene) |
| `engine` | godot \| unity \| unreal \| threejs \| raw | 'godot' | Target engine preset |
| `category` | prop \| character \| environment \| weapon \| architecture \| vfx \| ui | 'prop' | Asset category |
| `ai_prompt` | string | '' | What the asset was asked for — recorded in provenance |
| `triangle_budget` | integer | 0 | Triangle budget recorded in metadata; 0 uses the measured export |
| `material_budget` | integer | 0 | Material budget recorded in metadata; 0 uses the measured export |
| `contact_sheet` | boolean | True | Also render a review contact sheet |
| `draco` | boolean | False | Compress the GLB mesh payload with Draco for supported browser and engine runtimes |
| `strict` | boolean | True | Block export on problems that would corrupt the import |

### `export.blend`

Save the .blend master. Under ADR 0006 the .blend is the committed source of truth and the GLB is a derived artefact — always save both.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out` | string | 'asset.blend' | Output .blend path |
| `compress` | boolean | True | Compress the file |
| `pack_textures` | boolean | True | Embed image textures in the .blend. A master links textures by RELATIVE path, so the moment it is copied into assets-source those links break and the committed master is useless — `just asset-validate` fails it on missing textures |

### `export.gltf`

Export to GLB/glTF with an engine-specific preset. Checks for the things that silently break an import first — unapplied scale, missing UVs, procedural materials — and tells you rather than shipping a broken file.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out` | string | 'asset.glb' | Output path (.glb binary or .gltf text) |
| `objects` | array | [] | Objects to export (empty = whole scene) |
| `engine` | godot \| unity \| unreal \| threejs \| raw | 'godot' | Target engine preset |
| `format` | glb \| gltf | 'glb' | Binary GLB (one file) or text glTF (separate assets) |
| `animations` | boolean | True | Include armature actions |
| `draco` | boolean | False | Draco mesh compression — smaller files, slower load, not all importers support it |
| `strict` | boolean | True | Fail on problems that would corrupt the import instead of warning |
| `rename` | object | None | Names to apply IN THE EXPORTED FILE ONLY, e.g. {"horse": "Horse", "m_coat": "Coat", "gallop": "Gallop"}. Game code often looks up nodes and materials by exact name, and those names break the studio's snake_case rule — this satisfies both without renaming the master |

### `export.meta`

Write the .meta.json sidecar the studio asset pipeline requires — id, licence, provenance including AI-generation disclosure, budgets and policies. Without this, `just asset-validate` rejects the asset.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out` | string | 'asset.meta.json' | Output .meta.json path |
| `asset_id` | string | None | snake_case asset identifier |
| `category` | prop \| character \| environment \| weapon \| architecture \| vfx \| ui | 'prop' | Asset category |
| `license` | string | 'CC-BY-4.0' | Licence identifier |
| `creator` | string | 'bforge' | Creator name |
| `source` | string | 'procedural' | Where the asset came from |
| `ai_tool` | string | 'bforge' | AI tool used — required for honest provenance |
| `ai_model` | string | '' | Model that drove the generation, if any |
| `ai_prompt` | string | '' | Prompt or intent that produced the asset |
| `triangles` | integer | 0 | Triangle budget; 0 measures the scene |
| `materials` | integer | 2 | Material budget |
| `collision_policy` | explicit \| auto \| none | 'explicit' | Collision policy |
| `lod_policy` | explicit \| auto \| none | 'auto' | LOD policy |

## `gameready.*`

### `gameready.atlas`

Merge several objects into one mesh with one shared material and a repacked UV atlas. The most effective draw-call reduction available — a room of 20 props becomes 1 draw call.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `objects` | array | None | Objects to atlas together |
| `name` | string | 'atlas_group' | Name for the merged object |
| `margin` | number | 0.015 | UV island padding |
| `material` | string | 'stone' | Material preset for the merged result |
| `color` | string | '' | Override colour |

### `gameready.budget`

Check the scene against a platform triangle/texture budget and say what to do about anything over. Run this before export, every time.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `profile` | mobile_low \| mobile_high \| browser_webgl \| browser_webgpu \| desktop_high | 'browser_webgpu' | Target platform profile |
| `asset_class` | prop \| character \| environment \| hero | 'prop' | What kind of asset this is |
| `objects` | array | [] | Objects to check (empty = every mesh in the scene) |

### `gameready.collision`

Generate a physics collision proxy. Convex hulls are what you want for anything a character walks into; box is cheapest; simplified trimesh is for concave shapes like arenas and rooms. Named <object>-convcol / <object>-col per the studio import convention. SKIP for hulls that ride inside a moving body: Godot imports the proxy as a StaticBody3D child, and a static collider inside a CharacterBody3D blocks its own vehicle.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Source object |
| `mode` | box \| convex \| simplified \| cylinder \| sphere \| capsule | 'convex' | Proxy shape |
| `ratio` | number | 0.12 | simplified only: decimation ratio for the trimesh proxy |
| `inflate` | number | 0.0 | Grow the proxy by this many metres (stops geometry poking through) |
| `hide` | boolean | True | Hide the proxy from rendering |

### `gameready.lod`

Generate a level-of-detail chain by decimation. Ratios are chosen so each level roughly halves the triangle count, which is what LOD switching expects. Named <object>_lod1..N to match the studio import convention.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Source object (becomes LOD0) |
| `levels` | integer | 3 | Number of reduced levels to create |
| `ratios` | array | [] | Explicit decimation ratios, e.g. [0.5, 0.25, 0.1]. Empty auto-generates |
| `keep_uvs` | boolean | True | Preserve UV layout while decimating |
| `layout` | boolean | False | Offset each LOD along X for side-by-side review |

### `gameready.optimize`

One-call cleanup pass: weld doubles, drop degenerate faces, recalculate normals, and report what it saved. Safe to run on anything.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `objects` | array | [] | Objects to optimise (empty = every mesh) |
| `merge_distance` | number | 0.0001 | Vertex weld threshold in metres |
| `dissolve_flat` | boolean | False | Merge coplanar faces — cuts triangles but can create n-gons |
| `triangulate` | boolean | False | Triangulate (engines do this anyway; useful for exact counts) |

### `gameready.pivot`

Fix pivots and transforms across many objects at once — the two things engines get wrong on import and nobody notices until a prop spins about its ankle.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `objects` | array | [] | Objects to fix (empty = every mesh) |
| `origin` | bottom \| center \| center_xy \| world \| none | 'bottom' | Pivot placement |
| `apply_transforms` | boolean | True | Bake rotation and scale into the mesh |
| `snap_to_ground` | boolean | False | Move each object so its lowest point sits at Z=0 |
| `to_origin` | boolean | False | Also move the object itself to (0,0,0). Required for a single-asset master file — the studio validator rejects a root object that is not at the world origin |

### `gameready.socket`

Add a named empty as an attachment socket — muzzle points, hardpoints, spawn markers, VFX anchors. Engines import empties as nodes you can query by name.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Socket name (prefix it, e.g. 'socket_muzzle') |
| `parent` | string | '' | Object to parent the socket to |
| `location` | array | [0.0, 0.0, 0.0] | Position in metres |
| `rotation` | array | [0.0, 0.0, 0.0] | Rotation in degrees |
| `size` | number | 0.1 | Display size of the empty |

### `gameready.texture_budget`

Measure what the textures actually cost in GPU memory and flag any over the platform's resolution cap. Triangle budgets are half the story — a scene can be trivially cheap to draw and still fail to load because its textures do not fit in VRAM.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `profile` | mobile_low \| mobile_high \| browser_webgl \| browser_webgpu \| desktop_high | 'browser_webgpu' | Target platform profile |
| `assume_compressed` | boolean | False | Report cost after KTX2/Basis transcoding (~8:1) instead of raw RGBA. Only set this once the cook step actually compresses, or the number is fiction |

## `kit.*`

### `kit.piece`

One modular kit piece with its origin at the grid corner, ready to snap. Build a whole set with kit.set instead if you want more than one.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `kind` | floor \| wall \| wall_door \| wall_window \| wall_half \| corner \| pillar \| stairs \| ramp \| roof \| arch \| railing | 'wall' | Piece type |
| `name` | string | '' | Object name |
| `grid` | number | 4.0 | Grid module size in metres — use ONE value across the whole kit |
| `height` | number | 3.0 | Wall/storey height in metres |
| `thickness` | number | 0.25 | Wall thickness in metres |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 2.0 | Metres per UV tile — MUST match across the kit |
| `detail` | boolean | False | Extra edge loops for later greebling |
| `seed` | integer | 0 | Random seed |

### `kit.room`

Assemble a closed room from kit pieces: floor, four walls with a door and windows, optional pillars and roof. Produces a playable space, not just parts.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'room' | Name for the assembled room |
| `size` | array | [3, 3] | Room size in grid modules [x, y] |
| `grid` | number | 4.0 | Grid module size in metres |
| `height` | number | 3.0 | Wall height in metres |
| `thickness` | number | 0.25 | Wall thickness in metres |
| `doors` | integer | 1 | Number of doorway modules to cut into the walls |
| `windows` | integer | 2 | Number of window modules |
| `pillars` | boolean | True | Corner pillars |
| `roof` | boolean | False | Add a pitched roof |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 2.0 | Metres per UV tile |
| `join` | boolean | True | Merge into one mesh (recommended — one draw call) |
| `seed` | integer | 0 | Random seed |

### `kit.set`

Generate a complete, texel-consistent modular kit in one call — floor, walls, door, window, corner, pillar, stairs, roof. This is the fastest path from nothing to a level a designer can actually build with.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `prefix` | string | 'kit' | Name prefix for every piece |
| `pieces` | array | ['floor', 'wall', 'wall_door', 'wall_window', 'corner', 'pillar', 'stairs', 'roof'] | Which pieces to generate |
| `grid` | number | 4.0 | Grid module size in metres |
| `height` | number | 3.0 | Storey height in metres |
| `thickness` | number | 0.25 | Wall thickness in metres |
| `material` | string | 'stone' | Shared material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 2.0 | Shared metres-per-UV-tile across the whole set |
| `layout` | boolean | True | Lay the pieces out in a row for review rendering |
| `seed` | integer | 0 | Random seed |

## `material.*`

### `material.bake`

Bake procedural shading down to an image texture and rewire the material to use it. This is what makes procedural materials shippable.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object to bake |
| `pass_name` | base_color \| normal \| roughness \| ao \| emit \| combined | 'base_color' | Which channel to bake |
| `size` | integer | 1024 | Texture resolution in pixels |
| `samples` | integer | 16 | Cycles samples; 16 is plenty for base colour, raise for AO |
| `out` | string | '' | PNG output path (defaults to textures/<object>_<pass>.png) |
| `unwrap` | boolean | True | Auto-unwrap first — baking needs non-overlapping UVs |
| `rewire` | boolean | True | Replace the procedural graph with the baked texture |

### `material.bake_detail`

Bake high-poly detail onto a low-poly mesh as a tangent-space normal (or AO) map. This is what makes a cheap mesh read as an expensive one: the silhouette stays low-poly but the surface gets its detail back. Use this instead of material.bake when the detail lives in a separate dense mesh -- material.bake bakes an object onto itself, so its normal pass just reproduces the low-poly's own flat normals.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `low` | string | None | Low-poly object that receives the texture (needs UVs) |
| `high` | array | None | High-poly source object(s) the detail is projected from |
| `pass_name` | normal \| ao \| base_color | 'normal' | Which channel to transfer |
| `size` | integer | 2048 | Texture resolution in pixels |
| `samples` | integer | 32 | Cycles samples; raise for AO, 32 is plenty for normals |
| `cage_extrusion` | number | 0.02 | Metres to push the low-poly out before casting rays |
| `max_ray_distance` | number | 0.05 | Metres to search for the high-poly surface |
| `out` | string | '' | PNG output path (defaults to textures/<low>_<pass>_detail.png) |
| `attach` | boolean | True | Link the baked map into the low-poly's existing material |

### `material.bake_pbr`

Bake a layered material into a real PBR texture set (base colour, normal, roughness, AO) and rewire it as glTF-safe image textures. This is the step that makes a procedurally-surfaced asset actually shippable.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object to bake |
| `stem` | string | '' | Filename stem (defaults to the object name) |
| `out_dir` | string | 'textures' | Directory for the PNGs |
| `size` | integer | 1024 | Texture resolution per map |
| `samples` | integer | 24 | Cycles samples; AO and normal want more than base colour |
| `maps` | array | ['base_color', 'normal', 'roughness', 'ao'] | Which maps to bake |
| `unwrap` | boolean | True | Auto-unwrap first — baking needs non-overlapping UVs |
| `margin` | integer | 10 | Bake margin in pixels; prevents seams at low mips |

### `material.consolidate`

Merge materials that render identically into one shared material. Composing a scene from many prop recipes leaves a pile of near-duplicate materials, and every distinct material is a draw call — this collapses them without changing how anything looks.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `tolerance` | number | 0.02 | How close two materials' colour/roughness/metallic must be to count as the same |
| `objects` | array | [] | Limit to these objects (empty = whole scene) |
| `dry_run` | boolean | False | Report what would merge without changing anything |

### `material.face_assign`

Give a subset of faces its own material — trim strips, emissive panels, painted details. Selected by world-space direction or height.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object name |
| `preset` | string | 'gold' | Material preset for the selected faces |
| `select` | up \| down \| sides \| top_band \| bottom_band | 'up' | Face selection rule |
| `band_min` | number | 0.0 | top_band/bottom_band: lower bound as a fraction of height. Bands select by face CENTER, so a thin band needs real face rows at that height - one tall quad (e.g. a column shaft) has its centre near the middle and a thin band elsewhere matches nothing |
| `band_max` | number | 1.0 | top_band/bottom_band: upper bound as a fraction of height |
| `color` | string | '' | Override colour |
| `roughness` | number | -1.0 | Override roughness 0..1; -1 keeps the preset value |
| `metallic` | number | -1.0 | Override metallic 0..1; -1 keeps the preset value. Metals read black without something bright to reflect - painted trim (metallic ~0.15) survives dark environments |

### `material.list`

List materials in the file and flag any that glTF cannot export.

### `material.pbr`

Apply a layered AAA-grade surface: base albedo, curvature-driven EDGE WEAR, ambient-occlusion-driven CAVITY DIRT, two octaves of micro-detail and non-constant roughness. This is the single biggest jump in perceived quality — flat-coloured geometry never reads as AAA no matter how good the silhouette. Bake it with material.bake_pbr before export.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object to surface |
| `base_color` | any | 'stone_grey' | Base albedo: palette name or #rrggbb |
| `roughness` | number | 0.75 | Mid roughness; the layers vary around it |
| `metallic` | number | 0.0 | Metallic 0..1 |
| `detail_scale` | number | 14.0 | Micro-detail frequency — higher is finer grain |
| `grain` | number | 0.55 | How strongly the noise tints the albedo |
| `edge_wear` | number | 0.55 | Abrasion on convex edges (0..1). Real objects are worn where they stick out |
| `edge_color` | any | '' | Colour of worn edges; defaults to a lighter base |
| `cavity_dirt` | number | 0.5 | Grime settled in crevices (0..1) |
| `dirt_color` | any | '#2b2118' | Colour of the grime |
| `bump` | number | 0.35 | Surface relief strength |
| `name` | string | '' | Material name |
| `seed` | integer | 0 | Random seed for the noise |

### `material.procedural`

Build a noise/voronoi/wave/gradient material. Gives surfaces real variation instead of flat colour — but it must be baked (material.bake) before it can export to glTF.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object to assign to |
| `kind` | noise \| voronoi \| wave \| gradient \| checker | 'noise' | Pattern type: noise=rock/dirt, voronoi=cracked stone/scales, wave=wood grain/strata, gradient=vertical fade, checker=UV debug |
| `name` | string | '' | Material name |
| `color_a` | string | 'stone_grey' | Low colour: palette name or #rrggbb |
| `color_b` | string | 'stone_warm' | High colour: palette name or #rrggbb |
| `scale` | number | 5.0 | Pattern scale — higher is finer |
| `detail` | number | 2.0 | Fractal detail levels |
| `roughness` | number | 0.7 | Base roughness; the pattern modulates around it |
| `metallic` | number | 0.0 | Metallic 0..1 |
| `distortion` | number | 0.0 | Warps the pattern; makes wood grain and marble believable |

### `material.set`

Create and assign a PBR material. Prefer a preset name (stone, wood, metal, gold, crystal...) — the presets have physically sane roughness/metallic values.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object to assign to |
| `preset` | string | 'stone' | Material preset; see meta.palette for the list |
| `name` | string | '' | Material name (defaults to m_<preset>) |
| `color` | any | '' | Override colour: palette name, #rrggbb, or a linear [r,g,b] triple |
| `roughness` | number | -1.0 | Override roughness 0..1; -1 keeps the preset value |
| `metallic` | number | -1.0 | Override metallic 0..1; -1 keeps the preset value |
| `emission` | number | -1.0 | Emission strength; -1 keeps the preset value |
| `slot` | integer | 0 | Material slot index |

### `material.tileable`

Bake a SEAMLESS PBR texture set and apply it repeating across a surface. This is how architecture gets textured: a unique bake for a 725 m stadium works out to ~3 px/m, which is no texture at all, whereas one 1k tiling map gives real surface detail everywhere. Noise uses a symmetric periodic 4D mapping so it tiles perfectly without directional stretching or a visible seam.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object to texture |
| `base_color` | any | 'stone_grey' | Base albedo |
| `roughness` | number | 0.78 | Mid roughness |
| `metallic` | number | 0.0 | Metallic 0..1 |
| `detail_scale` | number | 6.0 | Feature size in the baked map — higher is finer |
| `dirt` | number | 0.35 | Grime settled in the low spots (0..1) |
| `dirt_color` | any | '#2b2118' | Grime colour |
| `bump` | number | 0.4 | Surface relief strength |
| `tiles` | number | 6.0 | How many times the map repeats across the object's UVs |
| `uv_scale` | number | 0.0 | Metres per UV tile for box projection; 0 keeps existing UVs |
| `size` | integer | 1024 | Texture resolution |
| `samples` | integer | 16 | Cycles samples for the bake |
| `maps` | array | ['base_color', 'normal', 'roughness'] | Which maps to bake; omit unused channels to keep browser payloads lean |
| `stem` | string | '' | Filename stem (defaults to the object name) |
| `out_dir` | string | 'textures' | Directory for the PNGs |
| `reuse` | boolean | True | If this stem was already baked, assign the existing material instead of baking again. Bake once, apply to every stone surface in a building — same texture, one set of maps, one draw call |
| `seed` | integer | 0 | Random seed |

## `meta.*`

### `meta.help`

Full parameter schema and defaults for one operation.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Op name, e.g. 'prop.crate' |

### `meta.ops`

List every available operation with its parameters. Call this first if you are unsure what exists.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `tag` | string | '' | Filter by tag (session, build, prop, kit, env, char, gameready, render, export, check) |
| `search` | string | '' | Filter by substring in the op name or summary |
| `detail` | names \| summary \| schema | 'summary' | How much to return per op |

### `meta.palette`

The studio colour palette and material presets. Use these names instead of inventing colours — palette discipline is what makes a set of assets look like one game.

## `object.*`

### `object.delete`

Remove objects from the scene.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `names` | array | None | Objects to delete |

### `object.duplicate`

Copy an object, optionally placing the copy in one call.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Source object |
| `new_name` | string | '' | Name for the copy (auto-derived when empty) |
| `location` | array | None | Where to put the copy |
| `rotation` | array | None | Copy's rotation in degrees |

### `object.inspect`

Detailed report for one object: topology, UV quality, texel density, materials, bounds.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `texture_size` | integer | 1024 | Texture resolution used for the texel-density figure |

### `object.join`

Merge several meshes into one object, de-duplicating material slots. Fewer objects means fewer draw calls.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `names` | array | None | Objects to merge (the first one's transform wins) |
| `into` | string | '' | Name for the merged result |

### `object.list`

List object names in the scene, optionally filtered by a name prefix.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `prefix` | string | '' | Only return names starting with this |

### `object.origin`

Set an object's pivot. Use 'bottom' for floor props, 'center' for pickups, 'world' for modular kit pieces.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `mode` | bottom \| center \| center_xy \| world | 'bottom' | Where the pivot goes |

### `object.rename`

Rename an object, coercing the new name to the studio's snake_case convention.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Current name |
| `to` | string | None | Desired name |

### `object.shade`

Set smooth or flat shading. Smooth shading with an angle threshold is what makes curved props read as curved.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `mode` | smooth \| flat | 'smooth' | Shading mode |
| `angle` | number | 35.0 | Edges sharper than this angle (degrees) stay hard |

### `object.transform`

Move, rotate or scale an object. Rotation is in degrees.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | None | Object name |
| `location` | array | None | World position in metres |
| `rotation` | array | None | Euler XYZ rotation in degrees |
| `scale` | array | None | Per-axis scale multiplier |
| `apply` | boolean | False | Bake rotation+scale into mesh data (required before export) |

## `prop.*`

### `prop.ancient_ship`

A browser-budget ancient Greek fishing boat, war galley or raider galley with a curved multi-chine hull, readable bow, oars, mast and restrained fittings. Fishing boats carry nets and amphorae; galleys carry oar banks, shields and a ram; raiders add a raised fighting rail, boarding spurs and a stern war standard.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'ancient_ship' | Object name |
| `style` | fishing \| galley \| raider | 'fishing' | Naval unit silhouette |
| `length` | number | 5.8 | Bow-to-stern length in metres |
| `beam` | number | 2.0 | Maximum hull width in metres |
| `height` | number | 2.8 | Keel-to-masthead height in metres |
| `hull_color` | string | '#3b2117' | Dark caulked hull planks |
| `wood_color` | string | '#6a4a2d' | Deck, mast and oars |
| `metal_color` | string | '#755431' | Bronze ram and fittings |
| `cloth_color` | string | '#5a2a25' | Muted sail or net bundle |
| `location` | array | [0.0, 0.0, 0.0] | World position |
| `rotation` | number | 0.0 | Yaw in degrees; bow points toward -Y |
| `uv_scale` | number | 0.55 | Metres per UV tile |

### `prop.banner`

Hanging banner or flag with a cloth wave. ~180 tris. Cheap way to add faction identity and colour to grey architecture.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `size` | array | [0.9, 1.8] | Cloth width and drop in metres |
| `wave` | number | 0.09 | Wave amplitude in metres |
| `segments` | integer | 8 | Vertical cloth segments |
| `pole` | boolean | True | Include a crossbar pole |
| `material` | string | 'cloth' | Cloth material preset |
| `color` | string | 'cloth_red' | Cloth colour |

### `prop.barrel`

Lathed barrel with a belly and iron bands. ~500 tris. Bands get their own material slot so they can read as metal.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `height` | number | 1.0 | Height in metres |
| `radius` | number | 0.32 | Radius at the widest point |
| `belly` | number | 0.18 | How much the middle bulges (0 = straight cylinder) |
| `segments` | integer | 14 | Radial segments |
| `bands` | integer | 2 | Number of iron hoops |
| `band_material` | string | 'iron' | Hoop material preset |
| `material` | string | 'wood' | Barrel material preset |
| `color` | string | '' | Override colour |
| `open_top` | boolean | False | Hollow out the top (for water butts, planters) |

### `prop.bow`

Serious hand-ready recurved bow with tapered laminated limbs, wrapped grip, taut drawn string and optional nocked arrow. One joined three-material mesh with its pivot at the grip for direct bone attachment.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `length` | number | 1.42 | Tip-to-tip height in metres |
| `reflex` | number | 0.16 | Forward recurve at each tip |
| `draw` | number | 0.24 | String draw behind the grip in metres |
| `arrow` | boolean | True | Include a nocked arrow |
| `wood_color` | string | '#4a3020' | Laminated limb and grip colour |
| `bronze_color` | string | '#6f512d' | Tip, arrowhead and grip fitting colour |
| `cord_color` | string | '#9b8f77' | Bowstring and fletching colour |
| `uv_scale` | number | 2.0 | Box unwrap scale |

### `prop.chest`

Treasure chest with a curved lid, iron banding and a lock plate. ~700 tris. Lid is a separate object so it can be hinged and animated.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `size` | array | [0.9, 0.55, 0.45] | Base dimensions (lid adds height on top) |
| `lid_height` | number | 0.22 | Height of the curved lid |
| `lid_segments` | integer | 8 | Lid curvature resolution |
| `separate_lid` | boolean | True | Keep the lid as its own object for hinge animation |
| `material` | string | 'wood' | Body material preset |
| `trim_material` | string | 'iron' | Banding and lock material preset |
| `color` | string | '' | Override body colour |

### `prop.crate`

Wooden crate with a recessed-panel frame. ~350 tris. The frame is what makes it read as a crate rather than a box.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `size` | array | [0.8, 0.8, 0.8] | Outer dimensions in metres |
| `frame_width` | number | 0.07 | Width of the corner/edge framing |
| `panel_depth` | number | 0.03 | How far the panels recess |
| `planks` | integer | 2 | Horizontal plank divisions per panel (0 for plain) |
| `bevel` | number | 0.012 | Edge chamfer width |
| `material` | string | 'wood' | Material preset |
| `color` | string | '' | Override colour |
| `uv_scale` | number | 1.0 | Metres per UV tile |

### `prop.crossbow`

Serious game-ready crossbow with a shouldered stock, curved segmented prod, taut three-part string, trigger guard, loaded bolt and integrated optic. Mastery styles add magazines, Daedalus gearing and an Aegis power core without changing the hand-ready pivot. One joined multi-material mesh.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `style` | pilgrim \| repeater \| daedalus \| aegis | 'pilgrim' | Construction and mastery tier |
| `length` | number | 1.18 | Stock length in metres |
| `span` | number | 0.92 | Unstrung prod span in metres |
| `scope` | boolean | True | Mount a compact tube optic and lens |
| `wood_color` | string | '#493323' | Seasoned stock colour |
| `bronze_color` | string | '#73512b' | Bronze fittings and prod colour |
| `iron_color` | string | '#343a3c' | Iron rail, trigger and mechanism colour |
| `cord_color` | string | '#9a8d72' | String and fletching colour |
| `lens_color` | string | '#431514' | Dark optic or Aegis core colour |
| `uv_scale` | number | 2.0 | Box unwrap scale |

### `prop.crystal`

Crystal cluster: several tapered prisms fanned from a common base. ~300 tris. Emissive by default — reads as a light source and a landmark.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `count` | integer | 5 | Number of shards |
| `height` | number | 1.0 | Tallest shard height in metres |
| `radius` | number | 0.16 | Shard base radius |
| `sides` | integer | 6 | Shard cross-section sides |
| `spread` | number | 28.0 | Maximum lean from vertical, in degrees |
| `material` | string | 'crystal' | Material preset |
| `color` | string | '' | Override colour |
| `emission` | number | 1.2 | Glow strength |

### `prop.debris`

Scattered rubble field: broken stone, planks and dust chunks around a point. ~50 tris per piece. Turns a clean floor into a fought-over one.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `count` | integer | 9 | Number of pieces |
| `radius` | number | 1.5 | Scatter radius in metres |
| `piece_size` | number | 0.22 | Average piece size |
| `kind` | stone \| wood \| mixed | 'stone' | Debris type |
| `material` | string | '' | Material preset override |

### `prop.fence`

Fence run with posts and rails. ~40 tris per metre. Blocks player movement and sells scale better than almost any other cheap prop.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `length` | number | 4.0 | Total run length in metres |
| `height` | number | 1.1 | Fence height |
| `style` | picket \| rail \| palisade \| iron | 'rail' | Fence style |
| `post_spacing` | number | 1.3 | Distance between posts |
| `material` | string | 'wood' | Material preset |
| `color` | string | '' | Override colour |

### `prop.furniture`

Table, bench, stool, shelf or bed frame. ~200 tris. The set dressing that makes an interior look inhabited.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `kind` | table \| bench \| stool \| shelf \| bed | 'table' | Furniture type |
| `size` | array | [1.6, 0.8, 0.78] | Overall dimensions in metres |
| `leg_radius` | number | 0.05 | Leg thickness |
| `round_legs` | boolean | False | Turned/round legs instead of square |
| `material` | string | 'wood' | Material preset |
| `color` | string | '' | Override colour |

### `prop.pillar`

Classical column: base, tapered shaft, capital, optional fluting. ~600 tris. Instant architecture.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `height` | number | 3.0 | Total height in metres |
| `radius` | number | 0.28 | Shaft radius |
| `style` | doric \| tuscan \| square \| broken | 'doric' | Column style |
| `flutes` | integer | 0 | Vertical grooves (0 = smooth). 16-20 is classical |
| `segments` | integer | 16 | Radial segments |
| `material` | string | 'stone' | Material preset |
| `color` | string | '' | Override colour |

### `prop.relic`

Grounded game-loot relic as a Greek medallion, signet ring, or votive idol. Separate aged metal, trim, and inset materials remain readable at pickup scale. ~300-700 tris.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `form` | medallion \| ring \| idol | 'medallion' | Loot silhouette: hanging seal, gemstone signet, or small temple votive |
| `motif` | rosette \| lambda \| plain | 'rosette' | Raised face mark for medallions; ignored by ring and idol forms |
| `size` | number | 0.42 | Overall height in metres |
| `material` | string | 'bronze' | Primary aged-metal material preset |
| `trim_material` | string | 'gold' | Raised rim and detail material preset |
| `gem_material` | string | 'crystal' | Inset stone material preset |
| `color` | string | '' | Override primary metal colour |
| `gem_color` | string | 'crystal_violet' | Inset stone colour |

### `prop.rock`

Grounded natural rock authored as a boulder, bedded slab, multi-stone outcrop or scree cluster. Layered displacement and optional strata avoid the inflated-potato silhouette.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `size` | array | [1.0, 0.85, 0.7] | Bounding dimensions in metres |
| `detail` | integer | 2 | Icosphere subdivisions: 1=80 tris, 2=320, 3=1280 |
| `roughness` | number | 0.28 | Surface irregularity (0 = smooth boulder, 0.5 = jagged) |
| `formation` | boulder \| slab \| outcrop \| scree | 'boulder' | Geological silhouette: one mass, bedded shelf, exposed cluster or broken field stone |
| `strata` | number | 0.35 | Horizontal bedding strength from 0 (none) to 1 (strong limestone courses) |
| `flatten_base` | boolean | True | Cut a flat bottom so it beds into terrain |
| `angular` | boolean | False | Faceted/low-poly look instead of smooth |
| `material` | string | 'rock' | Material preset |
| `color` | string | '' | Override colour |

### `prop.sack`

Cloth sack, cinched at the neck. ~400 tris. Good filler for markets, camps and storerooms.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `height` | number | 0.7 | Height in metres |
| `radius` | number | 0.26 | Body radius |
| `segments` | integer | 12 | Radial segments |
| `slump` | number | 0.25 | How much the body sags and spreads at the base |
| `material` | string | 'cloth' | Material preset |
| `color` | string | 'sand' | Colour |

### `prop.torch`

Wall torch or standing brazier with an emissive flame. ~250 tris. Emissive props double as level-design landmarks.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `style` | wall \| standing \| brazier | 'wall' | Mounting style |
| `height` | number | 0.6 | Length or height in metres |
| `flame_color` | string | 'ember' | Flame colour |
| `emission` | number | 6.0 | Flame emission strength |
| `material` | string | 'iron' | Body material preset |

### `prop.tree`

Game-ready tree with stylised and natural Mediterranean forms. Olive and cypress styles add age-authored roots, branch-readable crowns and negative space while preserving the cheap legacy silhouettes.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `height` | number | 4.0 | Total height in metres |
| `trunk_radius` | number | 0.18 | Trunk radius at the base |
| `canopy_style` | cone \| blob \| layered \| palm \| olive \| cypress | 'layered' | Canopy shape or natural species |
| `age` | young \| mature \| ancient | 'mature' | Natural species growth stage: changes roots, trunk forks, crown spread and gaps |
| `canopy_layers` | integer | 3 | layered style: number of tiers |
| `canopy_radius` | number | 1.4 | Canopy spread in metres |
| `detail` | integer | 2 | Natural olive/cypress foliage density, 1-3; ignored by legacy styles |
| `lean` | number | 4.0 | Trunk lean in degrees — a perfectly vertical tree looks fake |
| `trunk_material` | string | 'wood' | Trunk material preset |
| `leaf_material` | string | 'leaf' | Canopy material preset |
| `leaf_color` | string | '' | Override canopy colour |

### `prop.weapon`

Sword, axe, spear, hammer or shield built from a blade/haft/grip breakdown. ~400 tris. Pivot sits at the grip so it parents straight to a hand bone.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | '' | Object name (defaults to the recipe name) |
| `location` | array | [0.0, 0.0, 0.0] | World position in metres |
| `seed` | integer | 0 | Random seed — same seed always gives the same asset |
| `kind` | sword \| axe \| spear \| hammer \| shield \| dagger | 'sword' | Weapon type |
| `length` | number | 1.0 | Overall length in metres |
| `blade_width` | number | 0.09 | Blade or head width |
| `metal` | string | 'iron' | Blade material preset |
| `grip` | string | 'wood' | Handle material preset |
| `color` | string | '' | Override blade colour |

## `render.*`

### `render.camera`

Render from an explicit camera position and target. Auto-framing always fits the WHOLE subject, which is useless on a 700 m stadium or a 40 m terrain — this is how you get a close-up, an eye-level gameplay view, or a hero shot.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out` | string | 'shot.png' | PNG output path |
| `position` | array | None | Camera position in metres |
| `target` | array | [0.0, 0.0, 0.0] | Point to look at |
| `lens` | number | 50.0 | Focal length in mm — 24 is wide, 50 neutral, 105 compressed |
| `resolution` | integer | 640 | Width in pixels |
| `aspect` | number | 1.0 | Width / height. Use 1.78 for a 16:9 gameplay framing |
| `samples` | integer | 32 | Render samples |
| `engine` | auto \| cycles \| eevee | 'auto' | Render engine |
| `light_distance` | number | 0.0 | Light rig scale in metres; 0 fits it to the whole scene |
| `world_light` | number | 0.32 | Ambient dome strength. Higher fills shadows but piles white specular sheen onto every surface, which washes out saturated albedo |
| `transparent` | boolean | False | Render the world as transparent RGBA for UI cards, inventory icons and compositing |

### `render.cinematic`

A film-grade beauty render: physical sun and sky, global illumination, atmospheric haze, depth of field and a filmic tonemap. render.view and render.camera are flat REVIEW rigs built to judge albedo honestly; this one is built to show the asset at its best, and it is the render that tells you whether the art actually holds up.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out` | string | 'hero.png' | PNG output path |
| `position` | array | None | Camera position in metres |
| `target` | array | [0.0, 0.0, 0.0] | Point to look at |
| `lens` | number | 40.0 | Focal length in mm |
| `resolution` | integer | 1280 | Width in pixels |
| `aspect` | number | 2.39 | Width / height. 2.39 is anamorphic, 1.78 is 16:9 |
| `samples` | integer | 96 | Path-tracing samples. This is a beauty render; it costs time |
| `sun_energy` | number | 4.0 | Sun strength in W/m2. 3-6 reads as hard daylight |
| `sun_angle` | array | [52.0, 35.0] | Sun elevation and azimuth in degrees. Low sun = long shadows |
| `sun_color` | any | '#fff2dc' | Sunlight colour; warmer at low elevation |
| `sky_color` | any | '#6fa3dc' | Zenith sky colour, which is also the fill light |
| `horizon_color` | any | '#e8dcc0' | Horizon haze colour |
| `sky_strength` | number | 1.1 | Sky/ambient strength |
| `haze` | number | 0.0 | Volumetric atmosphere density. 0.0005-0.004 separates distant forms; costs render time |
| `focus` | number | 0.0 | Depth of field focus distance; 0 measures it to the target |
| `aperture` | number | 0.0 | f-stop. 0 disables depth of field. 2.8 is shallow, 8 is deep |
| `bounces` | integer | 6 | Light bounces. GI is most of what makes a render look expensive |
| `exposure` | number | 0.0 | Exposure compensation in stops |
| `look` | filmic \| agx \| standard \| contrast | 'agx' | View transform. Filmic/AgX roll off highlights like film; standard clips them |

### `render.contact_sheet`

THE review image. Renders hero/front/side/top plus a wireframe pass (shows topology and wasted triangles) and a checker pass (shows UV stretch and texel-density mismatches), composited into one PNG. Look at this after generating anything — it is how you catch problems a triangle count cannot show.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out` | string | 'contact_sheet.png' | PNG output path |
| `objects` | array | [] | Objects to review (empty = whole scene) |
| `tile` | integer | 400 | Pixel size of each tile |
| `samples` | integer | 20 | Render samples per tile |
| `engine` | auto \| cycles \| eevee | 'auto' | Render engine |
| `panels` | array | ['hero', 'front', 'left', 'top', 'wireframe', 'checker'] | Which panels to include |
| `columns` | integer | 3 | Tiles per row |

### `render.turntable`

Render an orbit of frames around the subject. Use when a single angle cannot settle whether a silhouette works.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out_dir` | string | 'turntable' | Directory for the frames |
| `objects` | array | [] | Objects to frame (empty = whole scene) |
| `frames` | integer | 8 | Number of orbit steps |
| `resolution` | integer | 384 | Square resolution per frame |
| `samples` | integer | 16 | Render samples |
| `elevation` | number | 22.0 | Camera elevation in degrees |
| `engine` | auto \| cycles \| eevee | 'auto' | Render engine |

### `render.view`

Render one framed view of the scene or of specific objects. The camera and a three-point light rig are auto-fitted to the subject, so you never get an empty or blown-out frame.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `out` | string | 'preview.png' | PNG output path |
| `objects` | array | [] | Objects to frame and show (empty = whole scene) |
| `view` | hero \| front \| back \| left \| right \| top \| low | 'hero' | Camera angle |
| `resolution` | integer | 512 | Square render resolution in pixels |
| `samples` | integer | 24 | Render samples — 24 is enough to judge form |
| `engine` | auto \| cycles \| eevee | 'auto' | Render engine. 'auto' means Cycles/CPU, which is the only one that works without a GPU context; 'eevee' is faster but crashes headless on machines with no display server |
| `ortho` | boolean | False | Orthographic projection (right for front/side/top reference) |
| `world_light` | number | 0.32 | Ambient dome strength. Higher fills shadows but piles white specular sheen onto every surface, which washes out saturated albedo |
| `transparent` | boolean | False | Render the world as transparent RGBA for UI cards, inventory icons and compositing |
| `padding` | number | 1.0 | Auto-frame multiplier: values above 1 add border; values below 1 make the subject fill more of the frame |

## `rig.*`

### `rig.keyframe`

Author an animation clip from explicit per-frame bone poses. Give the poses that define the motion and let the interpolation do the rest — this is how a real cycle is built, not by driving bones with sine waves.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `rig` | string | None | Armature object |
| `action` | string | 'action' | Action (clip) name |
| `keys` | object | None | {"1": {"spine": [rx, ry, rz]}, "12": {...}} — frame -> bone -> XYZ degrees |
| `locations` | object | None | Optional {"frame": {"bone": [x, y, z]}} bone translations in metres |
| `length` | integer | 24 | Clip length in frames |
| `loop` | boolean | True | Match the last frame to the first so the clip cycles seamlessly |
| `interpolation` | BEZIER \| LINEAR \| CONSTANT | 'BEZIER' | Keyframe interpolation |

### `rig.mirror_bones`

Duplicate a set of bones mirrored across an axis, renaming _l to _r (or vice versa). Halves the work of describing a symmetrical skeleton.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `bones` | array | None | Bone specs to mirror, same shape as rig.skeleton |
| `axis` | x \| y \| z | 'x' | Axis to mirror across |
| `from_suffix` | string | '_l' | Suffix on the source bones |
| `to_suffix` | string | '_r' | Suffix for the mirrored copies |

### `rig.skeleton`

Build an armature from an explicit bone list — any creature, not just humanoids. Each bone is {name, head:[x,y,z], tail:[x,y,z], parent}. Exactly one bone may be parentless, because engines and the studio validator both require a single root.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'rig' | Armature object name |
| `bones` | array | None | Bones: [{"name": "spine", "head": [0,0,1], "tail": [0,0.3,1], "parent": ""}, ...] |
| `location` | array | [0.0, 0.0, 0.0] | Armature position in metres |

### `rig.skin`

Bind a mesh to an armature using distance-to-bone falloff weights. Works on any skeleton and never fails the way Blender's bone-heat solver does on a non-watertight mesh.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `mesh` | string | None | Mesh object to bind |
| `rig` | string | None | Armature object |
| `falloff` | number | 2.0 | Weight sharpness; higher is more rigid, lower is smoother |
| `influences` | integer | 2 | Bones influencing each vertex (2 is right for game skins) |
| `only_bones` | array | [] | Restrict binding to these bones (empty = all deform bones) |

## `session.*`

### `session.import`

Import an existing glTF/GLB, OBJ, FBX or .blend into the current scene. Use this to inspect, critique, fix or extend assets a game already ships — not just ones you generated.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `path` | string | None | File to import (.glb/.gltf/.obj/.fbx/.blend) |
| `prefix` | string | '' | Rename imported objects with this prefix (keeps names snake_case) |
| `location` | array | [0.0, 0.0, 0.0] | Offset to place the import at |
| `reset_first` | boolean | False | Clear the scene before importing |

### `session.info`

Full scene report: every object with triangle counts, materials, UVs and bounds. Cheap; call it often.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `detail` | summary \| full | 'summary' | 'full' adds per-object UV statistics |

### `session.open`

Load an existing .blend so you can inspect, fix or extend an asset instead of rebuilding it.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `path` | string | None | Path to a .blend file |

### `session.reset`

Clear the scene to a deterministic empty metric-unit state. Start every new asset with this.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `unit_scale` | number | 1.0 | Blender unit scale; keep 1.0 = 1 metre for game engines |

### `session.restore`

Roll the scene back to a snapshot taken earlier in this session.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'default' | Checkpoint label passed to session.snapshot |

### `session.save`

Write the scene to a .blend master file (the committed source of truth in ADR 0006).

| parameter | type | default | description |
| --- | --- | --- | --- |
| `path` | string | 'asset.blend' | Output .blend path; relative paths land under the output dir |
| `compress` | boolean | True | Zstd-compress the .blend |

### `session.snapshot`

Save an in-memory scene checkpoint you can roll back to. Take one before any risky or destructive edit.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `name` | string | 'default' | Checkpoint label |

## `uv.*`

### `uv.lightmap`

Add a second, non-overlapping UV channel for baked lighting. Godot and Unity both require this for static lightmaps.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object name |
| `name` | string | 'UVLightmap' | Name of the new UV layer |
| `margin` | number | 0.03 | Island padding — lightmaps need more than base textures |

### `uv.normalize`

Fit existing UVs into the 0..1 square, preserving proportions.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object name |

### `uv.pack`

Repack existing UV islands into 0..1 without re-unwrapping. Use after joining objects or editing seams.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object name |
| `margin` | number | 0.02 | Island padding |

### `uv.report`

Measure UV quality: texel density, coverage, island count, overlap. Texel density is the number to match across an asset set — mismatched density is the most common reason AI-made assets look wrong together.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object name |
| `texture_size` | integer | 1024 | Texture resolution the density figure assumes |

### `uv.unwrap`

Generate UVs. Use 'box' with a shared uv_scale for anything using a tiling or trim texture (keeps texel density uniform across a whole kit); use 'smart_packed' for props that need their own baked texture.

| parameter | type | default | description |
| --- | --- | --- | --- |
| `object` | string | None | Object name |
| `style` | box \| cylinder \| smart \| smart_packed \| none | 'smart_packed' | Unwrap strategy |
| `scale` | number | 1.0 | box only: metres per UV tile. Use the SAME value across a kit |
| `margin` | number | 0.02 | smart only: island padding, prevents bleed at low mip levels |

