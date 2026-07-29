#!/usr/bin/env node
// The sensor. Drives a build, captures a fixed shot set on real hardware,
// measures frame timing, and writes an objective report.
//
//   node harness/shotset.mjs --url http://localhost:5173 --out runs/r001
//   node harness/shotset.mjs --url https://example.com/game --shots shots.json
//
// Engine-agnostic on purpose: it drives a URL and reads pixels, so the same
// harness measures a Three.js build, a Babylon build, and a Godot web export
// without knowing which is which.

import { mkdir, writeFile, readFile, stat, readdir } from 'node:fs/promises';
import path from 'node:path';
import { launch, probeGpu } from './browser.mjs';
import { connectRemote } from './remote.mjs';
import { openAnalyzer, analyzeFrame, diffFrames, findings } from './analyze.mjs';

// ---------------------------------------------------------------------------
// args

function parseArgs(argv) {
  const a = { seconds: 6, size: '1600x900', bootTimeoutMs: 30000 };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const next = () => argv[++i];
    if (k === '--url') a.url = next();
    else if (k === '--out') a.out = next();
    else if (k === '--shots') a.shots = next();
    else if (k === '--geometry-pass') a.geometryPass = true;
    else if (k === '--seconds') a.seconds = Number(next());
    else if (k === '--size') a.size = next();
    else if (k === '--boot-timeout') a.bootTimeoutMs = Number(next());
    else if (k === '--label') a.label = next();
    else if (k === '--remote') a.remote = next();       // run the browser on a GPU host
    else if (k === '--serve-port') a.servePort = Number(next());
    else if (k === '--gpu-profile') a.gpuProfile = next(); // 'webgpu' (P40) | 'raster' (V100)
    else if (k === '--calibration') a.calibration = next(); // reference-derived thresholds
    // Repeatable: pass every upstream layer the build depends on. A game export
    // is downstream of BOTH its project source AND the engine template it was
    // built from, and only checking the former produced a confident "not stale"
    // on an export made from a four-day-old template.
    else if (k === '--source') (a.sources ??= []).push(next());
    else if (k === '--build') a.build = next();     // built artefact the URL serves
    // Dependency CHAIN, in build order, e.g.
    //   --chain engine/patches,engine/artifacts/templates,games/x/project/exports/web-webgpu
    // Each element must be newer than the one before it. A fan-in check
    // (many sources, one build) cannot catch a middle layer that was never
    // rebuilt: an export made today from a four-day-old template is newer
    // than everything and looks fresh, while consuming stale code.
    else if (k === '--chain') a.chain = next().split(',').map((x) => x.trim()).filter(Boolean);
  }
  if (!a.url) throw new Error('--url is required');
  a.out = a.out || path.join('runs', `run-${Date.now()}`);
  const [w, h] = a.size.split('x').map(Number);
  a.viewport = { width: w, height: h };
  return a;
}

/**
 * Newest mtime under a path, recursively.
 *
 * A quality gate that measures a build older than its source is reporting on
 * work that no longer exists. This was already guarded for TypeScript (preflight
 * emits before capture), but an engine export is just as capable of being days
 * behind -- and nothing in the report would say so. Found by pointing the
 * harness at a real game export that turned out to be two days stale.
 */
async function newestMtime(target, skip = /node_modules|\.git|exports|\.import|assets-generated/) {
  let newest = 0;
  async function walk(p) {
    let st;
    try { st = await stat(p); } catch { return; }
    if (st.isFile()) { newest = Math.max(newest, st.mtimeMs); return; }
    if (!st.isDirectory()) return;
    let entries = [];
    try { entries = await readdir(p, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (skip.test(e.name)) continue;
      await walk(path.join(p, e.name));
    }
  }
  await walk(target);
  return newest;
}

// ---------------------------------------------------------------------------
// per-frame instrumentation, installed before any page script runs

const INSTRUMENT = `
(() => {
  // Named __gauntletProbe, NOT __gauntlet: the runtime contract owns that
  // global, and this init script runs first, so a collision would be silently
  // overwritten by the game's own hooks.
  const G = (window.__gauntletProbe = { dt: [], cb: [], started: performance.now(), longTasks: 0 });
  const orig = window.requestAnimationFrame.bind(window);
  let lastT = null;
  window.requestAnimationFrame = function (fn) {
    return orig(function (t) {
      const s = performance.now();
      try { fn(t); } finally {
        const e = performance.now();
        G.cb.push(e - s);
        if (lastT !== null) G.dt.push(t - lastT);
        lastT = t;
        if (G.dt.length > 20000) { G.dt.shift(); G.cb.shift(); }
      }
    });
  };
  // Record which context type the page ASKS for, passively.
  //
  // Probing with getContext() afterwards is destructive: on a canvas that has
  // no context yet, getContext('webgpu') CREATES one rather than reporting one.
  // That made a web-webgl export -- which had failed to boot, so its canvas was
  // still bare -- report "rendered through webgpu". The tool manufactured the
  // answer it then reported. Hooking the call is the only passive way to know.
  const origGetContext = HTMLCanvasElement.prototype.getContext;
  G.contexts = [];
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
    const ctx = origGetContext.call(this, type, ...rest);
    if (ctx && !G.contexts.includes(type)) G.contexts.push(type);
    return ctx;
  };

  try {
    new PerformanceObserver((l) => { G.longTasks += l.getEntries().length; })
      .observe({ entryTypes: ['longtask'] });
  } catch (e) { /* longtask unsupported */ }
})();
`;

/**
 * A canvas rendering flat out can keep the compositor too busy to service a
 * screenshot. Give it a bounded window, and on timeout yield a moment and try
 * once more before admitting defeat.
 */
// Measured on a GPU-starved WebGL page: raw CDP Page.captureScreenshot took
// 1.8s where Playwright's page.screenshot took 19s+ and then timed out. The
// difference is Playwright's stability waiting, which a continuously animating
// canvas never satisfies. So we go straight to CDP and keep page.screenshot as
// the fallback.
async function safeScreenshot(page, cdp, { timeout = 20000 } = {}) {
  if (cdp) {
    try {
      const r = await Promise.race([
        cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('cdp screenshot timeout')), timeout)),
      ]);
      return Buffer.from(r.data, 'base64');
    } catch {
      /* fall through to the Playwright path */
    }
  }
  try {
    return await page.screenshot({ type: 'png', timeout, animations: 'allow' });
  } catch (e) {
    if (!/Timeout/i.test(String(e))) throw e;
    await page.waitForTimeout(500);
    return page.screenshot({ type: 'png', timeout: timeout * 2, animations: 'allow' });
  }
}

function percentile(sorted, p) {
  if (!sorted.length) return null;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
  return +sorted[i].toFixed(2);
}

function summarizeTiming(dt, cb, longTasks) {
  if (!dt.length) return { frames: 0, note: 'page never called requestAnimationFrame' };
  const s = [...dt].sort((x, y) => x - y);
  const c = [...cb].sort((x, y) => x - y);
  const fps = (ms) => (ms && ms > 0 ? +(1000 / ms).toFixed(1) : null);

  // WHERE the worst frame happened, as a fraction of the session.
  //
  // "worst frame 2149 ms" is two completely different bugs depending on when it
  // lands. Early means load cost -- shader compilation, texture upload, the
  // first shadow pass -- which players see once as a longer wait. Late means a
  // genuine runtime hitch, which they feel every time it recurs. The report
  // could not tell them apart, so every spike looked equally alarming.
  let worst = -Infinity;
  let worstAt = 0;
  for (let i = 0; i < dt.length; i++) {
    if (dt[i] > worst) { worst = dt[i]; worstAt = i; }
  }
  const spikes = dt.filter((x) => x > 100).length;
  const lateSpikes = dt.filter((x, i) => x > 100 && i > dt.length * 0.25).length;

  return {
    frames: dt.length,
    frameMsP50: percentile(s, 50),
    frameMsP95: percentile(s, 95),
    frameMsP99: percentile(s, 99),
    frameMsWorst: +worst.toFixed(2),
    worstFrameIndex: worstAt,
    worstFrameAtPct: +((worstAt / Math.max(1, dt.length - 1)) * 100).toFixed(1),
    spikesOver100ms: spikes,
    spikesAfterFirstQuarter: lateSpikes,
    fpsP50: fps(percentile(s, 50)),
    fpsP99: fps(percentile(s, 99)), // the number players actually feel
    scriptMsP50: percentile(c, 50),
    scriptMsP99: percentile(c, 99),
    longTasks,
  };
}

// ---------------------------------------------------------------------------
// shot actions

async function applyShot(page, shot) {
  if (shot.script) await page.evaluate(shot.script);
  if (shot.click) await page.mouse.click(shot.click[0], shot.click[1]);
  if (shot.keys) for (const k of shot.keys) await page.keyboard.press(k);
  if (shot.hold) {
    for (const k of shot.hold.keys) await page.keyboard.down(k);
    await page.waitForTimeout(shot.hold.ms ?? 1000);
    for (const k of shot.hold.keys) await page.keyboard.up(k);
  }
  if (shot.mouseMove) await page.mouse.move(shot.mouseMove[0], shot.mouseMove[1]);
  if (shot.afterMs) await page.waitForTimeout(shot.afterMs);
}

const DEFAULT_SHOTS = {
  shots: [
    { name: 'boot', afterMs: 500, static: true },
    { name: 'settled', afterMs: 3000, static: true },
  ],
};

// ---------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const framesDir = path.join(args.out, 'frames');
  await mkdir(framesDir, { recursive: true });

  const config = args.shots
    ? JSON.parse(await readFile(args.shots, 'utf8'))
    : DEFAULT_SHOTS;
  // Reference-derived thresholds. Without these the objective gate is guessing:
  // fixed constants flagged a beautiful dark frame as broken AND passed a frame
  // 3x short of the real bar.
  const calibration = args.calibration
    ? JSON.parse(await readFile(args.calibration, 'utf8'))
    : null;
  const viewport = config.viewport
    ? { width: config.viewport[0], height: config.viewport[1] }
    : args.viewport;

  let browser;
  let context;
  let closeRemote = null;
  let remoteInfo = null;
  if (args.remote) {
    const r = await connectRemote({
      host: args.remote,
      servePort: args.servePort ?? 8099,
      gpuProfile: args.gpuProfile ?? 'webgpu',
    });
    browser = r.browser;
    closeRemote = r.close;
    remoteInfo = { host: r.host, gpuProfile: r.gpuProfile, gpuProfileLabel: r.gpuProfileLabel };
    // A CDP-attached browser already has a default context; newContext() is
    // not available over CDP the way it is for a launched browser.
    context = browser.contexts()[0] ?? (await browser.newContext());
  } else {
    browser = await launch();
    context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  }
  const page = await context.newPage();
  if (args.remote) await page.setViewportSize(viewport);

  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 8000));
  });
  page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 8000)));

  await page.addInitScript(INSTRUMENT);
  const cdp = await context.newCDPSession(page);

  // Staleness check before anything expensive. Measuring a build that predates
  // its source is worse than not measuring: the numbers look valid.
  let staleness = null;
  if (args.chain?.length >= 2) {
    const stamps = [];
    for (const link of args.chain) {
      const ms = await newestMtime(link);
      // A path that does not exist must be an error, not "infinitely stale".
      // Silently treating a typo as epoch 0 reports a spurious 495908h break
      // and buries the real answer.
      if (ms === 0) {
        throw new Error(`--chain link does not exist or is empty: ${link}`);
      }
      stamps.push({ path: link, ms });
    }
    const breaks = [];
    for (let i = 1; i < stamps.length; i++) {
      if (stamps[i - 1].ms > stamps[i].ms) {
        breaks.push({
          upstream: stamps[i - 1].path,
          downstream: stamps[i].path,
          behindHours: +((stamps[i - 1].ms - stamps[i].ms) / 3.6e6).toFixed(1),
        });
      }
    }
    staleness = {
      chain: stamps.map((s2) => ({ path: s2.path, newest: new Date(s2.ms).toISOString() })),
      breaks,
      stale: breaks.length > 0,
      behindHours: breaks.length ? Math.max(...breaks.map((b) => b.behindHours)) : 0,
      staleLayer: breaks.length ? breaks[0].downstream : null,
    };
    if (staleness.stale) {
      console.error('');
      console.error('[shotset] STALE CHAIN: a build step was skipped.');
      for (const s2 of staleness.chain) console.error(`  ${s2.newest}  ${s2.path}`);
      for (const b of breaks) {
        console.error(`  BREAK: ${b.downstream} is ${b.behindHours}h older than ${b.upstream}`);
      }
      console.error('  Rebuild the stale step before trusting anything below.');
      console.error('');
    }
  } else if (args.sources?.length && args.build) {
    const buildMs = await newestMtime(args.build);
    const layers = [];
    for (const src of args.sources) {
      const ms = await newestMtime(src);
      layers.push({
        source: src,
        sourceNewest: new Date(ms).toISOString(),
        stale: ms > buildMs,
        behindHours: ms > buildMs ? +((ms - buildMs) / 3.6e6).toFixed(1) : 0,
      });
    }
    const worst = layers.filter((l) => l.stale).sort((a, b) => b.behindHours - a.behindHours)[0];
    const stale = !!worst;
    staleness = {
      layers,
      build: args.build,
      buildNewest: new Date(buildMs).toISOString(),
      stale,
      behindHours: worst?.behindHours ?? 0,
      staleLayer: worst?.source ?? null,
    };
    if (stale) {
      console.error('');
      console.error(`[shotset] STALE BUILD: an upstream layer is ${staleness.behindHours}h newer than the build.`);
      for (const l of staleness.layers) {
        console.error(`  ${l.stale ? 'STALE' : '  ok '}  ${l.sourceNewest}  ${l.source}`);
      }
      console.error(`  build   ${staleness.buildNewest}  ${args.build}`);
      console.error('  Rebuild every stale layer before trusting anything below.');
      console.error('');
    }
  }

  const analyzer = await openAnalyzer(browser);

  const t0 = Date.now();
  await page.goto(args.url, { waitUntil: 'domcontentloaded', timeout: 60000 });

  // Boot = first frame with something actually on it. Polling composited
  // screenshots works regardless of renderer, preserveDrawingBuffer, or engine.
  let bootMs = null;
  const bootDeadline = Date.now() + args.bootTimeoutMs;
  while (Date.now() < bootDeadline) {
    const shot = await safeScreenshot(page, cdp);
    const m = await analyzeFrame(analyzer, shot);
    if (m.lumaStd > 3 && m.blackPct < 97) {
      bootMs = Date.now() - t0;
      break;
    }
    await page.waitForTimeout(400);
  }

  const gpu = await probeGpu(page);

  // Let the renderer reach steady state before timing anything.
  await page.waitForTimeout(1000);
  await page.evaluate(() => {
    window.__gauntletProbe.dt.length = 0;
    window.__gauntletProbe.cb.length = 0;
  });

  // Does the build implement the gauntlet runtime contract? If so we can pose
  // it deterministically and -- critically -- pause it before capturing, which
  // takes a screenshot from ~19s on a saturated canvas down to ~200ms.
  const contract = await page.evaluate(() => {
    const g = globalThis.__gauntlet;
    if (!g || typeof g.pause !== 'function') return null;
    return { version: g.version ?? 1, cameras: g.cameras ? g.cameras() : [] };
  });

  const results = [];
  for (const shot of config.shots ?? DEFAULT_SHOTS.shots) {
    let posed = false;

    if (contract) {
      // Deterministic path: seed, pose, step a fixed number of frames from a
      // paused state. Same shot definition always yields the same pixels.
      posed = await page.evaluate(async (s) => {
        const g = globalThis.__gauntlet;
        g.pause();
        if (s.seed !== undefined) g.seed(s.seed);
        if (s.camera) g.setCamera(s.camera);
        await g.step(s.steps ?? 8);
        return true;
      }, shot);
      // Input still applies (menus, key presses) but against a paused clock.
      if (shot.keys || shot.click || shot.script) {
        await applyShot(page, { ...shot, afterMs: 0, hold: null });
        await page.evaluate(async (s) => globalThis.__gauntlet.step(s.steps ?? 4), shot);
      }
    } else {
      await applyShot(page, shot);
    }

    const pngA = await safeScreenshot(page, cdp);
    const fileA = path.join(framesDir, `${shot.name}.png`);
    await writeFile(fileA, pngA);

    const metrics = await analyzeFrame(analyzer, pngA);

    // Geometry pass: re-render THIS frame with shading stripped, to separate
    // detail that was modelled from detail that was printed on a texture. See
    // the long note on `setMaterialMode` in runtime/gauntlet-hooks.js -- the
    // short version is that edgeEnergy alone called a nearly-flat room "at the
    // reference bar" three times running.
    let geometry = null;
    if (args.geometryPass && contract) {
      const swapped = await page.evaluate(async () => {
        const g = globalThis.__gauntlet;
        if (!g.setMaterialMode) return { ok: false, reason: 'harness newer than runtime hooks' };
        const r = g.setMaterialMode('flat');
        if (r.ok) await g.step(1, 0); // dt=0: identical world state, different shading
        return r;
      });
      if (swapped.ok) {
        const pngG = await safeScreenshot(page, cdp);
        // A registered-but-inert hook is worse than no hook: identical frames
        // would report ~100% of the detail as modelled, which is precisely the
        // fabricated number this pass exists to avoid. A game whose asset
        // failed to load registers `materials` and then swaps nothing.
        if (pngG.equals(pngA)) {
          geometry = { skipped: 'material swap produced an identical frame — hook registered but inert' };
        } else {
        const fileG = path.join(framesDir, `${shot.name}.flat.png`);
        await writeFile(fileG, pngG);
        const gm = await analyzeFrame(analyzer, pngG);
        geometry = {
          file: path.relative(args.out, fileG).split(path.sep).join('/'),
          edgeEnergy: gm.edgeEnergy,
          blockEdgeP50: gm.composition?.blockEdgeP50 ?? null,
          // What fraction of the shaded frame's edge energy survives with the
          // textures off. Low means the form is carried by maps, not by mesh.
          earnedDetailPct: metrics.edgeEnergy > 0
            ? +((gm.edgeEnergy / metrics.edgeEnergy) * 100).toFixed(1)
            : null,
        };
        }
        await page.evaluate(async () => {
          globalThis.__gauntlet.setMaterialMode('beauty');
          await globalThis.__gauntlet.step(1, 0);
        });
      } else {
        geometry = { skipped: swapped.reason };
      }
    }

    let staticDiff = null;
    if (shot.static) {
      // Advance the world without moving the camera. On a correct renderer this
      // is near-identical; differences are z-fighting, shadow acne, or
      // unresolved temporal noise -- the defects that survive every eyeball
      // review because they only show up in motion.
      if (contract) {
        // dt = 0: re-render at the SAME simulation time. Stepping real time
        // here was a bug -- it advanced the world, so any legitimate animation
        // (a rotating textured prop) registered as "instability". Rendering the
        // identical world state twice isolates genuinely non-deterministic
        // output: z-fighting, shadow acne, unresolved TAA jitter.
        await page.evaluate(async () => globalThis.__gauntlet.step(1, 0));
      } else {
        await page.waitForTimeout(120);
      }
      const pngB = await safeScreenshot(page, cdp);
      staticDiff = await diffFrames(analyzer, pngA, pngB);
    }

    if (contract) await page.evaluate(() => globalThis.__gauntlet.resume());

    results.push({
      posed,
      name: shot.name,
      file: path.relative(args.out, fileA).split(path.sep).join('/'),
      metrics,
      geometry,
      staticDiff,
      findings: findings(metrics, { staticDiff, calibration }),
    });
  }

  await page.waitForTimeout(args.seconds * 1000);
  const timing = await page.evaluate(() => ({
    dt: window.__gauntletProbe.dt,
    cb: window.__gauntletProbe.cb,
    longTasks: window.__gauntletProbe.longTasks,
  }));

  const contractStats = contract
    ? await page.evaluate(() => globalThis.__gauntlet.stats())
    : null;

  const report = {
    label: args.label ?? args.url,
    url: args.url,
    capturedAtMs: t0,
    viewport,
    gpu,
    remote: remoteInfo, // null => rendered locally
    staleness,          // null => not checked; .stale => the report describes an old build
    calibratedAgainst: calibration?.reference ?? null,
    contract, // null => shots are best-effort, not reproducible
    contractStats,
    bootMs,
    timing: summarizeTiming(timing.dt, timing.cb, timing.longTasks),
    consoleErrors: consoleErrors.slice(0, 25),
    pageErrors: pageErrors.slice(0, 25),
    shots: results,
  };

  // Roll findings up so a caller can gate on one number.
  const all = results.flatMap((r) => r.findings);
  report.summary = {
    fatal: all.filter((f) => f.severity === 'fatal').length,
    warn: all.filter((f) => f.severity === 'warn').length,
    info: all.filter((f) => f.severity === 'info').length,
    consoleErrors: consoleErrors.length,
    pageErrors: pageErrors.length,
    softwareRenderer: gpu.software === true,
    staleBuild: staleness?.stale === true,
  };

  await writeFile(path.join(args.out, 'report.json'), JSON.stringify(report, null, 2));
  await writeFile(path.join(args.out, 'report.md'), renderMarkdown(report));

  if (closeRemote) await closeRemote();
  else await browser.close();

  console.log(renderMarkdown(report));
  // Non-zero only on hard failures; warnings are for the loop to act on, not
  // for CI to choke on.
  process.exit(report.summary.fatal > 0 || report.summary.pageErrors > 0 ? 1 : 0);
}

function renderMarkdown(r) {
  const L = [];
  L.push(`# gauntlet shotset — ${r.label}`);
  L.push('');
  L.push(`- URL: ${r.url}`);
  L.push(`- Viewport: ${r.viewport.width}x${r.viewport.height}`);
  L.push(`- Boot to first non-empty frame: ${r.bootMs === null ? '**NEVER RENDERED**' : r.bootMs + ' ms'}`);
  if (r.remote) {
    L.push(`- Rendered on: **${r.remote.host}** · profile \`${r.remote.gpuProfile}\` — ${r.remote.gpuProfileLabel}`);
  } else {
    L.push('- Rendered on: this machine (no GPU) — use `--remote smeagol` for anything you intend to trust');
  }
  // Capability and actual backend are separate claims. Reporting only the
  // former invites "webgpu=nvidia" to be read as "this rendered via WebGPU",
  // which it never meant.
  L.push(`- **Application rendered through: \`${r.gpu.applicationRenderer ?? 'unknown'}\`** (${r.gpu.canvases ?? 0} canvas${(r.gpu.canvases ?? 0) === 1 ? '' : 'es'})`);
  L.push(`- Browser capability — WebGL adapter: ${r.gpu.availableWebGL ?? 'n/a'}`);
  L.push(`- Browser capability — WebGPU adapter: ${r.gpu.availableWebGPU ?? 'n/a'}${r.gpu.hasWebGPU ? '' : ' (navigator.gpu absent)'}`);
  if (r.gpu.availableWebGPU && r.gpu.applicationRenderer && !String(r.gpu.applicationRenderer).includes('webgpu')) {
    L.push('  > A WebGPU adapter was available but this application did NOT use it.');
  }
  if (r.staleness?.stale) {
    L.push('');
    L.push(`> **STALE — a build step was skipped (${r.staleness.behindHours}h).**`);
    if (r.staleness.breaks) {
      for (const b of r.staleness.breaks) {
        L.push(`> \`${b.downstream}\` is ${b.behindHours}h older than \`${b.upstream}\``);
      }
    } else {
      L.push(`> stale: \`${r.staleness.staleLayer}\``);
    }
    L.push('> Re-export before acting on anything in this report.');
    L.push('');
  }
  if (r.contract) {
    L.push(`- runtime contract: **v${r.contract.version}, deterministic** · cameras: ${r.contract.cameras.join(', ') || '(none registered)'}`);
  } else {
    L.push('- runtime contract: **absent** — shots are best-effort and NOT reproducible run-to-run.');
    L.push('  Import `runtime/gauntlet-hooks.js` to make captures deterministic and ~100x cheaper.');
  }
  if (r.gpu.software) {
    L.push('');
    L.push('> **SOFTWARE RENDERER DETECTED — every timing number below is fiction.**');
    L.push('> Re-run with GAUNTLET_HEADED=1, or on a box with a working GPU.');
  }
  L.push('');
  const t = r.timing;
  L.push('## Timing');
  if (!t.frames) {
    L.push(`- ${t.note ?? 'no frames captured'}`);
  } else {
    L.push(`- fps p50 **${t.fpsP50}** / p99 **${t.fpsP99}**  (frame ms p50 ${t.frameMsP50}, p99 ${t.frameMsP99}, worst ${t.frameMsWorst})`);
    if (t.spikesOver100ms) {
      const verdict = t.spikesAfterFirstQuarter === 0
        ? 'all in the first quarter — load cost, not a runtime hitch'
        : `${t.spikesAfterFirstQuarter} after the first quarter — genuine runtime hitches`;
      L.push(`- spikes over 100 ms: ${t.spikesOver100ms} (${verdict}); worst at frame ${t.worstFrameIndex} of ${t.frames} (${t.worstFrameAtPct}% in)`);
    }
    L.push(`- page script per frame: p50 ${t.scriptMsP50} ms, p99 ${t.scriptMsP99} ms`);
    L.push(`- long tasks: ${t.longTasks}`);
  }
  L.push('');
  L.push('## Shots');
  for (const s of r.shots) {
    const m = s.metrics;
    L.push(`### ${s.name}`);
    L.push(`\`${s.file}\``);
    L.push(
      `- luma mean ${m.lumaMean} · p01/p50/p99 ${m.lumaP01}/${m.lumaP50}/${m.lumaP99} · dynamic range ${m.dynamicRange}`,
    );
    L.push(`- black ${m.blackPct}% · white ${m.whitePct}% · levels ${m.occupiedLevels} · chroma ${m.chromaMean}`);
    L.push(`- edge energy ${m.edgeEnergy} · smooth span ${m.smoothSpan} over ${m.smoothLevels} levels (${m.combGaps} gaps)`);
    if (s.geometry?.skipped) {
      L.push(`- geometry pass: **skipped** — ${s.geometry.skipped}`);
    } else if (s.geometry) {
      L.push(
        `- geometry pass (shading off): edge energy ${s.geometry.edgeEnergy} — ` +
          `**${s.geometry.earnedDetailPct}%** of the shaded frame's detail is modelled, not textured  ` +
          `_(diagnostic; not validated as a gate)_`,
      );
    }
    if (s.staticDiff) {
      L.push(`- static-camera instability: ${s.staticDiff.changedPct}% pixels changed (max delta ${s.staticDiff.maxDelta})`);
    }
    if (s.findings.length) {
      for (const f of s.findings) L.push(`  - **${f.severity}** \`${f.code}\` — ${f.message}`);
    } else {
      L.push('  - no objective defects');
    }
    L.push('');
  }
  if (r.pageErrors.length) {
    L.push('## Uncaught page errors');
    for (const e of r.pageErrors) L.push(`- ${e}`);
    L.push('');
  }
  if (r.consoleErrors.length) {
    L.push('## Console errors');
    for (const e of r.consoleErrors) L.push(`- ${e}`);
    L.push('');
  }
  L.push(
    `**Summary:** ${r.summary.fatal} fatal · ${r.summary.warn} warn · ${r.summary.info} info · ${r.summary.pageErrors} page errors`,
  );
  return L.join('\n');
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
