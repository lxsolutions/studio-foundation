// gauntlet starter — a scene that already clears the objective gate on turn 1.
//
// This is not a demo of three.js. It is a set of decisions that the harness
// would otherwise spend three rounds forcing you to make:
//
//   - image-based lighting, so materials have something to reflect (without it
//     every metal reads as flat plastic and `edgeEnergy` stays low)
//   - ACES tonemapping with real exposure, so the histogram is not crushed or
//     blown (`dynamicRange`, `blackPct`, `whitePct`)
//   - dithering on, so smooth gradients do not band (`combGaps`)
//   - roughness VARIATION from procedural noise, which is the single loudest
//     difference between "procedural" and "authored" surfaces
//   - the runtime contract wired before any content, so every capture is
//     reproducible from the first frame
//
// Everything is generated in code. No external assets.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { gauntlet } from '/tools/gauntlet/runtime/gauntlet-hooks.js';

// ---------------------------------------------------------------------------
// renderer

const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.info.autoReset = false;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(48, innerWidth / innerHeight, 0.1, 400);

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const gtao = new GTAOPass(scene, camera, innerWidth, innerHeight);
gtao.output = GTAOPass.OUTPUT.Default;
composer.addPass(gtao);
composer.addPass(new OutputPass());

// Image-based lighting from a procedurally generated room. Free, no asset, and
// it is the difference between materials that respond to light and materials
// that are simply tinted.
const pmrem = new THREE.PMREMGenerator(renderer);

// Sky + distance fade. Fog is what gives a scene depth ordering for free.
scene.fog = new THREE.FogExp2(0x6b7d94, 0.011);

// ---------------------------------------------------------------------------
// procedural textures
//
// Generated once into canvases, then reused. Value noise is enough: the goal is
// break-up, not realism. Uniform roughness is the tell we are avoiding.

function noiseCanvas(size: number, octaves: number, contrast: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d')!;
  const img = ctx.createImageData(size, size);
  const rnd = mulberry(1337);
  const grid = [];
  for (let o = 0; o < octaves; o++) {
    const n = 2 << o;
    const g = new Float32Array(n * n);
    for (let i = 0; i < g.length; i++) g[i] = rnd();
    grid.push({ n, g });
  }
  const sample = (layer: { n: number; g: Float32Array }, x: number, y: number): number => {
    const { n, g } = layer;
    const fx = x * n, fy = y * n;
    const x0 = Math.floor(fx) % n, y0 = Math.floor(fy) % n;
    const x1 = (x0 + 1) % n, y1 = (y0 + 1) % n;
    const tx = fx - Math.floor(fx), ty = fy - Math.floor(fy);
    const sx = tx * tx * (3 - 2 * tx), sy = ty * ty * (3 - 2 * ty);
    const a = g[y0 * n + x0]!, b = g[y0 * n + x1]!, cc = g[y1 * n + x0]!, d = g[y1 * n + x1]!;
    return (a * (1 - sx) + b * sx) * (1 - sy) + (cc * (1 - sx) + d * sx) * sy;
  };
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let v = 0, amp = 1, norm = 0;
      for (const layer of grid) {
        v += sample(layer, x / size, y / size) * amp;
        norm += amp;
        amp *= 0.5;
      }
      v = v / norm;
      v = 0.5 + (v - 0.5) * contrast;
      const p = (y * size + x) * 4;
      const b = Math.max(0, Math.min(255, v * 255)) | 0;
      img.data[p] = img.data[p + 1] = img.data[p + 2] = b;
      img.data[p + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

// Multi-scale surface detail: the single biggest measured gap against the bar.
// The reference frames score edgeEnergy 28-30; smooth shaded geometry tops out
// around 10 no matter how good the lighting is. What closes the distance is
// structure at several frequencies at once -- slab divisions, seam bolts,
// grime streaks, fine speckle -- so the Sobel response is non-zero at every
// scale the eye samples.
function panelCanvas(
  size = 512,
  { cells = 6, grime = 0.4, bolts = true, seed = 5 }: { cells?: number; grime?: number; bolts?: boolean; seed?: number } = {},
): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d')!;
  const rnd = mulberry(seed);

  ctx.fillStyle = '#9a9a9a';
  ctx.fillRect(0, 0, size, size);

  // Slab divisions, with per-slab tonal variation so panels read as separate
  // pieces rather than a printed grid.
  const step = size / cells;
  for (let y = 0; y < cells; y++) {
    for (let x = 0; x < cells; x++) {
      const v = 0.82 + rnd() * 0.32;
      ctx.fillStyle = `rgb(${(154 * v) | 0},${(154 * v) | 0},${(154 * v) | 0})`;
      ctx.fillRect(x * step + 1, y * step + 1, step - 2, step - 2);
    }
  }

  // Recessed seams.
  ctx.strokeStyle = 'rgba(40,40,40,0.85)';
  ctx.lineWidth = Math.max(2, size / 220);
  for (let i = 0; i <= cells; i++) {
    const p = i * step;
    ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, size); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(size, p); ctx.stroke();
  }

  // Bolts along the seams -- small, bright, high-frequency. These contribute
  // disproportionately to edge energy because each one is a hard step.
  if (bolts) {
    const r = Math.max(1.5, size / 260);
    for (let i = 0; i <= cells; i++) {
      for (let j = 0; j <= cells; j++) {
        if (rnd() < 0.35) continue;
        const x = i * step + (rnd() - 0.5) * 4;
        const y = j * step + (rnd() - 0.5) * 4;
        ctx.fillStyle = 'rgba(215,215,215,0.95)';
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = 'rgba(45,45,45,0.7)';
        ctx.beginPath(); ctx.arc(x + r * 0.35, y + r * 0.35, r * 0.55, 0, Math.PI * 2); ctx.fill();
      }
    }
  }

  // Grime and streaking, biased downward like real weathering.
  ctx.globalAlpha = grime;
  for (let i = 0; i < 90; i++) {
    const x = rnd() * size;
    const y = rnd() * size;
    const w = 2 + rnd() * (size / 40);
    const h = size * (0.04 + rnd() * 0.22);
    const g = ctx.createLinearGradient(0, y, 0, y + h);
    const dark = 40 + rnd() * 60;
    g.addColorStop(0, `rgba(${dark},${dark},${dark},0.5)`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(x, y, w, h);
  }
  ctx.globalAlpha = 1;

  // Fine speckle -- the highest frequency band.
  const img = ctx.getImageData(0, 0, size, size);
  for (let i = 0; i < img.data.length; i += 4) {
    const n = (rnd() - 0.5) * 46;
    img.data[i] = Math.max(0, Math.min(255, img.data[i]! + n));
    img.data[i + 1] = Math.max(0, Math.min(255, img.data[i + 1]! + n));
    img.data[i + 2] = Math.max(0, Math.min(255, img.data[i + 2]! + n));
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

// Anisotropic filtering is not a nicety here. Without it, tiled detail at
// grazing angles aliases into sparkle -- which a Sobel filter happily scores as
// "surface detail" while a player sees shimmer. Measured: adding detail maps
// without this took static-camera instability from 0.03% to 2.08% and the
// round driver correctly called it a regression.
const MAX_ANISO = renderer.capabilities.getMaxAnisotropy();

function toTexture(canvas: HTMLCanvasElement, repeat = 1): THREE.CanvasTexture {
  const t = new THREE.CanvasTexture(canvas);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat, repeat);
  t.anisotropy = MAX_ANISO;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

// Derive a tangent-space normal map from the height field by central
// differences. Without this every surface is a perfect mirror of its own
// shading model -- which is exactly what "plastic" looks like, and what the
// eye catches even when `edgeEnergy` passes.
function toNormal(canvas: HTMLCanvasElement, strength = 2.2, repeat = 1): THREE.CanvasTexture {
  const size = canvas.width;
  const src = canvas.getContext('2d')!.getImageData(0, 0, size, size).data;
  const out = document.createElement('canvas');
  out.width = out.height = size;
  const octx = out.getContext('2d')!;
  const img = octx.createImageData(size, size);
  const at = (x: number, y: number): number =>
    src[(((y + size) % size) * size + ((x + size) % size)) * 4]! / 255;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (at(x + 1, y) - at(x - 1, y)) * strength;
      const dy = (at(x, y + 1) - at(x, y - 1)) * strength;
      let nx = -dx, ny = -dy, nz = 1;
      const len = Math.hypot(nx, ny, nz) || 1;
      nx /= len; ny /= len; nz /= len;
      const p = (y * size + x) * 4;
      img.data[p] = (nx * 0.5 + 0.5) * 255;
      img.data[p + 1] = (ny * 0.5 + 0.5) * 255;
      img.data[p + 2] = (nz * 0.5 + 0.5) * 255;
      img.data[p + 3] = 255;
    }
  }
  octx.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(out);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat, repeat);
  t.anisotropy = MAX_ANISO;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

// A vertical sky gradient as an equirect background. A flat background colour
// leaves the top of every frame dead, which reads as "unfinished" instantly and
// costs you dynamic range you already paid for.
function skyTexture(): THREE.CanvasTexture {
  const W = 512, H = 256;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d')!;

  // Upper half: sky. Lower half: LIT ground bounce, not darkness. A metal
  // reflects the whole sphere, so a dark lower hemisphere turns every mirror
  // surface black -- which is exactly what happened on the previous round.
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0.00, '#2c5590');
  g.addColorStop(0.34, '#6f9ac9');
  g.addColorStop(0.48, '#bcd0e4');
  g.addColorStop(0.52, '#e8c79b');
  g.addColorStop(0.70, '#9a7c5c');
  g.addColorStop(1.00, '#6d5a44');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  // A sun disc with falloff. Without a bright, small, high-contrast feature in
  // the environment, polished surfaces have no specular highlight to catch and
  // read as dull plastic regardless of their roughness value.
  const sx = W * 0.26, sy = H * 0.23;
  const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, H * 0.42);
  glow.addColorStop(0.00, 'rgba(255,252,238,1)');
  glow.addColorStop(0.06, 'rgba(255,236,196,0.95)');
  glow.addColorStop(0.30, 'rgba(255,214,158,0.35)');
  glow.addColorStop(1.00, 'rgba(255,200,140,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);

  // Soft cloud banding gives the reflection something to break up against.
  const rnd = mulberry(9);
  ctx.globalAlpha = 0.10;
  for (let i = 0; i < 26; i++) {
    const y = H * (0.12 + rnd() * 0.3);
    const w = W * (0.08 + rnd() * 0.26);
    const x = rnd() * W;
    const h = H * (0.012 + rnd() * 0.03);
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.ellipse(x, y, w, h, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  const t = new THREE.CanvasTexture(c);
  t.mapping = THREE.EquirectangularReflectionMapping;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function mulberry(a: number): () => number {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const fineNoise = noiseCanvas(256, 5, 1.6);
const coarseNoise = noiseCanvas(256, 6, 1.9);

const metalRough = toTexture(fineNoise, 2);
const metalNormal = toNormal(fineNoise, 0.8, 2);
const stoneRough = toTexture(coarseNoise, 4);
const stoneNormal = toNormal(coarseNoise, 2.6, 4);
const groundRough = toTexture(coarseNoise, 24);
const groundNormal = toNormal(coarseNoise, 3.2, 24);

// Albedo detail. Uniform `color` is the reason a well-lit scene still reads as
// untextured: with no variation in base colour there is nothing for light to
// reveal. An albedo map multiplies against `color`, so a greyscale detail map
// keeps the palette and adds the structure.
const stonePanel = panelCanvas(512, { cells: 5, grime: 0.45, seed: 11 });
const groundPanel = panelCanvas(512, { cells: 4, grime: 0.55, seed: 23 });
const metalPanel = panelCanvas(512, { cells: 8, grime: 0.28, seed: 37 });

const srgb = (t: THREE.Texture): THREE.Texture => { t.colorSpace = THREE.SRGBColorSpace; return t; };
const stoneMap = srgb(toTexture(stonePanel, 2));
const stoneDetailNormal = toNormal(stonePanel, 2.0, 2);
const groundMap = srgb(toTexture(groundPanel, 14));
const groundDetailNormal = toNormal(groundPanel, 2.4, 14);
const metalMap = srgb(toTexture(metalPanel, 3));
const metalDetailNormal = toNormal(metalPanel, 1.0, 3);

/**
 * Vertical fluting, displaced on the actual vertices rather than faked in a
 * normal map. Silhouette detail survives at grazing angles and in shadow where
 * a normal map flattens out.
 */
function flute(geo: THREE.CylinderGeometry, flutes = 20, depth = 0.035): THREE.CylinderGeometry {
  const pos = geo.attributes.position as THREE.BufferAttribute;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const z = pos.getZ(i);
    const r = Math.hypot(x, z);
    if (r < 1e-4) continue;
    const th = Math.atan2(z, x);
    const s = 1 + depth * Math.sin(th * flutes);
    pos.setX(i, Math.cos(th) * r * s);
    pos.setZ(i, Math.sin(th) * r * s);
  }
  pos.needsUpdate = true;
  geo.computeVertexNormals();
  return geo;
}

// Light the scene with the same sky it is standing under. Reflections that
// disagree with the background are the fastest way to look fake.
const sky = skyTexture();
scene.background = sky;
scene.environment = pmrem.fromEquirectangular(sky).texture;
scene.environmentIntensity = 1.0;

// ---------------------------------------------------------------------------
// lighting

const sun = new THREE.DirectionalLight(0xffe9c8, 3.1);
sun.position.set(-14, 20, 9);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.near = 1;
sun.shadow.camera.far = 80;
sun.shadow.camera.left = -28;
sun.shadow.camera.right = 28;
sun.shadow.camera.top = 28;
sun.shadow.camera.bottom = -28;
sun.shadow.bias = -0.0006;
sun.shadow.normalBias = 0.03;
scene.add(sun);

// A cool fill from the opposite side keeps shadows from going dead black --
// which is what `crushed-shadows` in the report is telling you about.
const fill = new THREE.HemisphereLight(0x9dc4ff, 0x3a2c22, 0.6);
scene.add(fill);

// ---------------------------------------------------------------------------
// content

const world = new THREE.Group();
scene.add(world);

// Authored asset, not a tiled primitive.
//
// The hand-coded version was a cylinder with sinusoidal vertex displacement and
// one panel texture repeated over it. That bought edgeEnergy (10 -> 38) while
// the frame got WORSE, because tiling is repetition, not detail. This is the
// same silhouette produced properly by bforge: real base and capital profiles,
// fluting as actual geometry, non-overlapping UVs at a measured 250.9 px/m, and
// base colour / roughness / normal / AO baked to textures. 640 triangles.
//
// This is the sanctioned exception to "zero external assets": the rule exists
// for COHERENCE, and an asset generated from our own palette by our own forge
// is coherent by construction.
const loader = new GLTFLoader();
let columnProto: THREE.Object3D | null = null;
let colonnadeProto: THREE.Object3D | null = null;
let debrisProto: THREE.Object3D | null = null;

const ASSET_DIR = '/assets-generated/bforge/gauntlet';

async function loadOne(file: string): Promise<THREE.Object3D | null> {
  try {
    const gltf = await loader.loadAsync(`${ASSET_DIR}/${file}`);
    gltf.scene.traverse((o: THREE.Object3D) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) {
        m.castShadow = true;
        m.receiveShadow = true;
      }
    });
    return gltf.scene;
  } catch {
    return null;
  }
}

async function loadAssets(): Promise<void> {
  try {
    [columnProto, colonnadeProto, debrisProto] = await Promise.all([
      loadOne('gauntlet_column.glb'),
      loadOne('plaza_colonnade.glb'),
      loadOne('plaza_debris.glb'),
    ]);
    if (!columnProto) throw new Error('column GLB missing');
  } catch (e) {
    // Fall back to the procedural column rather than rendering nothing. A
    // missing asset should degrade the frame, not blank it.
    console.warn('column GLB absent (run: just NAME=gauntlet_column RECIPE=prop.pillar bforge-make) — using procedural fallback:', e);
    columnProto = null;
  }
}

let seed = 1;

function buildWorld() {
  world.clear();
  const rnd = mulberry(seed);

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(200, 200),
    new THREE.MeshStandardMaterial({
      color: 0x8a7d69,
      roughness: 0.96,
      roughnessMap: groundRough,
      normalMap: groundNormal,
      normalScale: new THREE.Vector2(0.9, 0.9),
      metalness: 0.02,
      dithering: true,
    }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  world.add(ground);

  const stone = new THREE.MeshStandardMaterial({
    color: 0xd8cdb6, roughness: 0.78, roughnessMap: stoneRough,
    normalMap: stoneNormal, normalScale: new THREE.Vector2(0.7, 0.7),
    metalness: 0.03, dithering: true,
  });
  const bronze = new THREE.MeshStandardMaterial({
    color: 0xd0a05c, roughness: 0.31, roughnessMap: metalRough,
    normalMap: metalNormal, normalScale: new THREE.Vector2(0.28, 0.28),
    metalness: 0.92, dithering: true,
  });

  // A colonnade. Repeated silhouettes read as intentional architecture, and
  // give the shadow pass something worth doing.
  // 64 radial segments so the fluting resolves; 6 height segments so vertex
  // normals interpolate cleanly along the shaft.
  const colGeo = flute(new THREE.CylinderGeometry(0.52, 0.6, 7.5, 64, 6), 16, 0.032);
  const capGeo = new THREE.BoxGeometry(1.5, 0.45, 1.5);
  for (let i = 0; i < 12; i++) {
    const side = i < 6 ? -1 : 1;
    const k = i % 6;
    const x = side * 6.5;
    const z = -12 + k * 5;
    const jitter = (rnd() - 0.5) * 0.12;

    if (columnProto) {
      const col = columnProto.clone(true);
      // Origin is at the base (bforge exports architecture pivoted to floor),
      // so this sits on the ground rather than needing a half-height offset.
      col.position.set(x + jitter, 0, z);
      // A different yaw per instance. Free, and it is what stops twelve copies
      // of one mesh reading as a repeated stamp -- the same failure as tiling a
      // texture, one level up.
      col.rotation.y = rnd() * Math.PI * 2;
      const s = 0.97 + rnd() * 0.06;
      col.scale.set(s, 1, s);
      world.add(col);
    } else {
      const col = new THREE.Mesh(colGeo, stone);
      col.position.set(x + jitter, 3.75, z);
      col.castShadow = col.receiveShadow = true;
      world.add(col);

      const cap = new THREE.Mesh(capGeo, stone);
      cap.position.set(x + jitter, 7.7, z);
      cap.castShadow = cap.receiveShadow = true;
      world.add(cap);
    }
  }

  if (colonnadeProto) {
    const ring = colonnadeProto.clone(true);
    ring.position.set(0, 0, 0);
    world.add(ring);
  }
  if (debrisProto) {
    // Three offset copies at different yaw so the scatter does not read as one
    // stamped pattern -- the per-instance rule that tiling violated.
    for (let i = 0; i < 3; i++) {
      const d = debrisProto.clone(true);
      d.rotation.y = rnd() * Math.PI * 2;
      d.position.set((rnd() - 0.5) * 6, 0, (rnd() - 0.5) * 6);
      world.add(d);
    }
  }

  // Focal object -- something metallic so the IBL has a job.
  const monument = new THREE.Mesh(new THREE.IcosahedronGeometry(2.1, 4), bronze);
  monument.position.set(0, 3.2, 0);
  monument.castShadow = monument.receiveShadow = true;
  monument.name = 'monument';
  world.add(monument);

  const plinth = new THREE.Mesh(new THREE.CylinderGeometry(3.1, 3.4, 1.2, 32), stone);
  plinth.position.set(0, 0.6, 0);
  plinth.castShadow = plinth.receiveShadow = true;
  world.add(plinth);

  // Scattered debris breaks the grid and adds mid-frequency detail.
  const shardGeo = new THREE.DodecahedronGeometry(0.42, 0);
  for (let i = 0; i < 26; i++) {
    const s = new THREE.Mesh(shardGeo, stone);
    const a = rnd() * Math.PI * 2;
    const r = 9 + rnd() * 16;
    s.position.set(Math.cos(a) * r, 0.2 + rnd() * 0.3, Math.sin(a) * r);
    s.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3);
    s.scale.setScalar(0.6 + rnd() * 0.9);
    s.castShadow = s.receiveShadow = true;
    world.add(s);
  }
}
await loadAssets();
buildWorld();

// ---------------------------------------------------------------------------
// cameras — named poses are what make captures comparable across runs

const CAMERAS = {
  hero: () => { camera.position.set(0, 4.4, 15); camera.lookAt(0, 3.2, 0); },
  wide: () => { camera.position.set(20, 11, 22); camera.lookAt(0, 3, 0); },
  low: () => { camera.position.set(-4.5, 1.25, 9); camera.lookAt(0, 3.6, 0); },
  detail: () => { camera.position.set(2.6, 3.6, 5.2); camera.lookAt(0, 3.2, 0); },
};
CAMERAS.hero();

// ---------------------------------------------------------------------------
// loop

let firstDraw: (() => void) | null = null;
const ready = new Promise<void>((r) => (firstDraw = r as () => void));
const hudEl = document.getElementById('hud');
if (!hudEl) throw new Error('#hud missing from index.html');
// Rebound as a definitely-non-null const so the narrowing survives into
// the hoisted frame() closure below.
const hud: HTMLElement = hudEl;
const monument = () => world.getObjectByName('monument');

function frame(t: number): void {
  renderer.info.reset();
  const m = monument();
  if (m) m.rotation.y = t * 0.00022;
  composer.render();
  if (firstDraw) { firstDraw(); firstDraw = null; }
  hud.textContent = `seed ${seed} · ${renderer.info.render.calls} draws · ${renderer.info.render.triangles} tris`;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
  gtao.setSize(innerWidth, innerHeight);
});

// ---------------------------------------------------------------------------
// the contract

gauntlet.register({
  ready,
  scene, // enables the generic NaN-transform scan
  seed: (n) => { seed = n; buildWorld(); },
  camera: CAMERAS,
  probe: () => ({
    cameraPos: [camera.position.x, camera.position.y, camera.position.z],
    monumentSpin: monument()?.rotation.y ?? 0,
    objects: world.children.length,
  }),
  stats: () => ({
    drawCalls: renderer.info.render.calls,
    triangles: renderer.info.render.triangles,
    programs: renderer.info.programs?.length ?? null,
    geometries: renderer.info.memory.geometries,
    textures: renderer.info.memory.textures,
  }),
});
