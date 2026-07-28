/**
 * Render probe: does this export actually draw, and how cleanly?
 *
 * The smoke test answers "did the page come up without erroring". That is not
 * the same question as "did a frame render", and conflating the two is exactly
 * how a renderer gets claimed before it works.
 *
 *   - counts every GPUValidationError the device reports, by class
 *   - records the adapter and device THE GAME requested, not a second one of our
 *     own, and rejects a fallback adapter by isFallbackAdapter
 *   - reads Godot's own draw / object / primitive counters out of the running game
 *   - samples the canvas to tell a rendered image from a cleared buffer
 *
 * The verdict has three states, because "rendered" and "not rendered" are both
 * positive claims and some runs support neither. Varied pixels alone are NOT
 * enough to claim a frame -- a loading screen, a 2D error overlay or a gradient
 * background all produce varied pixels -- so a rendered verdict additionally
 * requires verified hardware and non-zero engine draw counters. A uniform canvas
 * is a definite negative; anything else unproven is `inconclusive`, never a pass.
 *
 * Usage:
 *   node render-probe.mjs --url URL [--out DIR] [--seconds N] [--label NAME]
 */

import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const argv = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const URL = arg("url", "http://127.0.0.1:8099/index.html");
const OUT = arg("out", "./render-probe-out");
const SECONDS = Number(arg("seconds", "25"));
const LABEL = arg("label", "render-probe");

// Headed Chrome under a virtual display is the only configuration that gets a
// real Vulkan adapter on this class of host; headless falls back to SwiftShader
// and would quietly measure a software renderer.
const CHROME_ARGS = [
  "--no-sandbox",
  "--enable-unsafe-webgpu",
  "--enable-features=Vulkan",
  "--ignore-gpu-blocklist",
  "--disable-vulkan-fallback-to-gl-for-testing",
];

mkdirSync(OUT, { recursive: true });

const consoleLines = [];
const pageErrors = [];

/** Group validation errors so a report says which defect class remains, not just a count. */
function classify(message) {
  const m = message.toLowerCase();
  if (m.includes("bind group") || m.includes("bindgroup")) return "bind-group";
  if (m.includes("sampletype") || m.includes("sample type")) return "sample-type";
  if (m.includes("storage") && m.includes("format")) return "storage-format";
  if (m.includes("lod")) return "lod";
  if (m.includes("pipeline")) return "pipeline";
  if (m.includes("buffer")) return "buffer";
  if (m.includes("texture")) return "texture";
  return "other";
}

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
  headless: false,
  args: CHROME_ARGS,
});

const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });

page.on("console", (msg) => consoleLines.push(`[${msg.type()}] ${msg.text()}`));
page.on("pageerror", (err) => pageErrors.push(String(err)));

// Record the adapter and device THE GAME actually got, by wrapping the WebGPU
// entry points before the page runs.
//
// Requesting a second adapter of our own and reporting its properties proves
// nothing about the build under test: requestAdapter may hand back a different
// adapter each call, and the spec explicitly allows it to return a fallback
// adapter even when forceFallbackAdapter is false. A report that says "nvidia"
// while the engine is running on SwiftShader is worse than no report.
await page.addInitScript(() => {
  globalThis.__studioAdapter = null;
  globalThis.__studioDevice = null;
  if (!navigator.gpu) return;

  const gpu = navigator.gpu;
  const origRequestAdapter = gpu.requestAdapter.bind(gpu);
  gpu.requestAdapter = async function (options) {
    const adapter = await origRequestAdapter(options);
    if (!adapter) return adapter;
    try {
      const info = adapter.info ?? {};
      globalThis.__studioAdapter = {
        vendor: info.vendor ?? null,
        architecture: info.architecture ?? null,
        device: info.device ?? null,
        description: info.description ?? null,
        // The spec's own answer to "is this real hardware".
        isFallbackAdapter: info.isFallbackAdapter ?? adapter.isFallbackAdapter ?? null,
        features: [...(adapter.features ?? [])],
        forceFallbackRequested: Boolean(options?.forceFallbackAdapter),
      };
      const origRequestDevice = adapter.requestDevice.bind(adapter);
      adapter.requestDevice = async function (desc) {
        const device = await origRequestDevice(desc);
        try {
          globalThis.__studioDevice = {
            requestedFeatures: [...(desc?.requiredFeatures ?? [])],
            enabledFeatures: [...(device?.features ?? [])],
          };
        } catch (e) {}
        return device;
      };
    } catch (e) {}
    return adapter;
  };
});

await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60_000 });

// Give the engine its cold-start shader compile. This is genuinely slow the
// first time -- ~20s is normal and is itself a documented property of the build.
const started = Date.now();
await page.waitForTimeout(SECONDS * 1000);
const waitedMs = Date.now() - started;

// Measure the CANVAS REGION OF THE COMPOSITED SCREENSHOT, not a canvas readback.
//
// drawImage(canvas) + getImageData returns an all-black image on this
// Chrome/Xvfb/WebGPU configuration even while the page is demonstrably
// rendering. That was caught by a positive control: Chariot on Forward Mobile,
// which renders 3D at 60 fps here with zero validation errors, was reported as a
// uniform cleared buffer by the readback path while its screenshot was a
// 751 KB detailed frame. Every verdict from the readback path was therefore a
// false negative.
//
// page.screenshot() goes through the compositor and sees what the user sees, so
// the screenshot is the source of truth. It is decoded back inside the browser
// -- the browser already has a PNG decoder, and shipping one here would be a
// second thing that can be wrong.
const canvasBox = await page.evaluate(() => {
  const canvas = document.querySelector("canvas");
  if (!canvas) return null;
  const r = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.round(r.x)),
    y: Math.max(0, Math.round(r.y)),
    width: Math.round(r.width),
    height: Math.round(r.height),
    bufferWidth: canvas.width,
    bufferHeight: canvas.height,
  };
});

const shotPath = join(OUT, `${LABEL}.png`);
await page.screenshot({ path: shotPath, fullPage: false });

let canvasReport;
if (!canvasBox || !canvasBox.width || !canvasBox.height) {
  canvasReport = { present: false };
} else {
  // Clip to the canvas so a coloured HTML overlay elsewhere on the page cannot
  // be mistaken for the game drawing something.
  const clipped = await page.screenshot({
    clip: { x: canvasBox.x, y: canvasBox.y, width: canvasBox.width, height: canvasBox.height },
  });
  const stats = await page.evaluate(async (b64) => {
    const blob = await (await fetch(`data:image/png;base64,${b64}`)).blob();
    const bmp = await createImageBitmap(blob);
    const off = document.createElement("canvas");
    off.width = bmp.width;
    off.height = bmp.height;
    const ctx = off.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(bmp, 0, 0);
    const { data } = ctx.getImageData(0, 0, bmp.width, bmp.height);
    const counts = new Map();
    let nonBlack = 0;
    let sampled = 0;
    const stride = 4 * 7; // A full 1280x720 scan in JS is slow and unnecessary.
    for (let i = 0; i < data.length; i += stride) {
      const r = data[i], g = data[i + 1], b = data[i + 2];
      if (r + g + b > 24) nonBlack += 1;
      // Quantise to 5 bits/channel so imperceptible gradients do not inflate it.
      const key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
      counts.set(key, (counts.get(key) ?? 0) + 1);
      sampled += 1;
    }
    // A cleared buffer is not exactly one colour once it has been through PNG
    // encoding and the compositor -- a flat grey frame measures ~6 quantised
    // colours. What distinguishes a clear is that essentially every sample lands
    // in ONE bucket, so dominance is the real test and a raw distinct count is
    // not.
    let dominant = 0;
    for (const n of counts.values()) if (n > dominant) dominant = n;
    return {
      distinctColors: counts.size,
      dominantColorFraction: sampled ? dominant / sampled : 1,
      nonBlackFraction: sampled ? nonBlack / sampled : 0,
    };
  }, clipped.toString("base64"));

  canvasReport = {
    present: true,
    width: canvasBox.bufferWidth,
    height: canvasBox.bufferHeight,
    readable: true,
    source: "composited screenshot, clipped to the canvas",
    ...stats,
  };
}

// Godot's own counters, if the game exposes them. Absent counters are reported
// as null rather than zero -- "we could not read it" is not "it drew nothing".
const engineCounters = await page.evaluate(() => {
  const probe = globalThis.__studioRenderProbe;
  return probe && typeof probe === "object" ? probe : null;
});

const validation = consoleLines.filter((l) => /GPUValidationError|Validation error/i.test(l));
const byClass = {};
for (const line of validation) {
  const k = classify(line);
  byClass[k] = (byClass[k] || 0) + 1;
}

const adapter = await page.evaluate(() => globalThis.__studioAdapter ?? null);
const device = await page.evaluate(() => globalThis.__studioDevice ?? null);

// Three states, not two. "Rendered" and "not rendered" are both positive claims,
// and there are results that support neither.
//
//   not-rendered  the canvas is readable and uniform. A cleared buffer is a
//                 definite negative regardless of what else is unknown.
//   rendered      hardware adapter, varied pixels, AND the engine's own draw
//                 counters agree that geometry was submitted.
//   inconclusive  everything else -- a fallback adapter, an unreadable canvas,
//                 or varied pixels with no counters to corroborate them. Varied
//                 pixels alone would also be satisfied by a loading screen, a 2D
//                 error overlay or a gradient background, so they are not enough
//                 on their own to claim a rendered 3D frame.
const counters = engineCounters ?? {};
const counterValues = ["draws", "objects", "primitives"]
  .map((k) => counters[k])
  .filter((v) => typeof v === "number");
const countersPositive = counterValues.length > 0 && counterValues.every((v) => v > 0);
const hardwareAdapter = adapter !== null && adapter.isFallbackAdapter === false;
// A clear frame is one colour plus encoding noise, so dominance decides, not a
// raw distinct count. Calibrated against controls on this host: a WebGPU
// clear-only page measures 0.968 dominance (not 1.0 -- PNG encoding and the
// compositor add noise), while Chariot rendering a real 3D scene measures 0.336.
// The gap is wide, so the threshold is not delicate.
const UNIFORM_DOMINANCE = 0.95;
const pixelsVaried =
  canvasReport.present === true &&
  canvasReport.readable === true &&
  canvasReport.dominantColorFraction < UNIFORM_DOMINANCE &&
  canvasReport.nonBlackFraction > 0.01;
const pixelsUniform =
  canvasReport.present === true &&
  canvasReport.readable === true &&
  canvasReport.dominantColorFraction >= UNIFORM_DOMINANCE;

// Order matters, and it is not the obvious one. Hardware identity is checked
// BEFORE a blank canvas is called a negative: a uniform frame on a fallback
// adapter, an unidentified adapter, or a page that never initialised WebGPU
// proves nothing about the build under test, and reporting it as a definite
// negative is the same overclaim in the opposite direction.
let verdict;
let why;
if (!hardwareAdapter) {
  verdict = "inconclusive";
  why =
    adapter === null
      ? "the page never requested a WebGPU adapter, so nothing was measured"
      : `adapter isFallbackAdapter=${adapter.isFallbackAdapter} — not verified hardware`;
} else if (canvasReport.present !== true || canvasReport.readable !== true) {
  verdict = "inconclusive";
  why = "the canvas could not be captured";
} else if (pixelsUniform) {
  verdict = "not-rendered";
  why = "verified hardware, and the canvas is a single colour — a cleared buffer";
} else if (!pixelsVaried) {
  verdict = "inconclusive";
  why = "canvas brightness is between the flat and detailed calibration bands";
} else if (!countersPositive) {
  verdict = "inconclusive";
  why =
    "pixels vary but the engine reported no draw/object/primitive counters; " +
    "varied pixels alone are also produced by a loading screen or overlay";
} else {
  verdict = "rendered";
  why = "hardware adapter, varied pixels, and non-zero engine draw counters";
}

const report = {
  label: LABEL,
  url: URL,
  adapter,
  device,
  waited_ms: waitedMs,
  verdict,
  verdict_reason: why,
  // Kept as a strict boolean for callers that only want the headline, and it is
  // true only for the "rendered" verdict -- never for "inconclusive".
  frame_rendered: verdict === "rendered",
  canvas: canvasReport,
  engine_counters: engineCounters,
  gpu_validation_errors: validation.length,
  gpu_validation_by_class: byClass,
  page_errors: pageErrors.length,
  screenshot: shotPath,
};

writeFileSync(join(OUT, `${LABEL}.json`), JSON.stringify(report, null, 2) + "\n");
writeFileSync(join(OUT, `${LABEL}.console.log`), consoleLines.join("\n") + "\n");
if (pageErrors.length) {
  writeFileSync(join(OUT, `${LABEL}.pageerrors.log`), pageErrors.join("\n") + "\n");
}

console.log(JSON.stringify(report, null, 2));

await browser.close();

// Exit code carries the headline result so a caller can gate on it.
//   0  rendered
//   1  not-rendered   (a definite negative)
//   2  inconclusive   (deliberately distinct: an unproven run must not read as
//                      either a pass or a measured failure)
process.exit(verdict === "rendered" ? 0 : verdict === "not-rendered" ? 1 : 2);
