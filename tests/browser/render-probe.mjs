/**
 * Render probe: does this export actually draw, and how cleanly?
 *
 * The smoke test answers "did the page come up without erroring". That is not
 * the same question as "did a frame render", and conflating the two is exactly
 * how a renderer gets claimed before it works. This probe answers the second
 * one, and refuses to answer it from anything but pixels:
 *
 *   - counts every GPUValidationError the device reports, by class
 *   - reads Godot's own draw-call / primitive counters out of the running game
 *   - screenshots the canvas and measures whether it is a rendered image or a
 *     cleared buffer, by sampling pixels
 *
 * A frame counts as rendered only if the canvas shows more than one distinct
 * colour. A device that clears to grey and dies produces a perfectly uniform
 * canvas, which is the failure this check exists to catch.
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

// The adapter check must happen on the target origin, not on about:blank:
// navigator.gpu is not exposed to an opaque origin, so probing there reports
// "no WebGPU" on a machine that has it.
await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60_000 });

const adapter = await page.evaluate(async () => {
  if (!navigator.gpu) return null;
  const a = await navigator.gpu.requestAdapter();
  if (!a) return null;
  return {
    vendor: a.info?.vendor ?? null,
    architecture: a.info?.architecture ?? null,
    device: a.info?.device ?? null,
    description: a.info?.description ?? null,
  };
});

if (!adapter) {
  console.error("FATAL: no WebGPU adapter. Refusing to report a software result as a GPU result.");
  await browser.close();
  process.exit(3);
}

// Give the engine its cold-start shader compile. This is genuinely slow the
// first time -- ~20s is normal and is itself a documented property of the build.
const started = Date.now();
await page.waitForTimeout(SECONDS * 1000);
const waitedMs = Date.now() - started;

const canvasReport = await page.evaluate(async () => {
  const canvas = document.querySelector("canvas");
  if (!canvas) return { present: false };

  // Read back the composited canvas. drawImage works for both webgpu and webgl
  // contexts and does not require the source context to be preserveDrawingBuffer.
  const w = canvas.width;
  const h = canvas.height;
  if (!w || !h) return { present: true, width: w, height: h, readable: false };

  const off = document.createElement("canvas");
  off.width = w;
  off.height = h;
  const ctx = off.getContext("2d", { willReadFrequently: true });
  try {
    ctx.drawImage(canvas, 0, 0);
  } catch (e) {
    return { present: true, width: w, height: h, readable: false, error: String(e) };
  }

  const { data } = ctx.getImageData(0, 0, w, h);
  const seen = new Set();
  let nonBlack = 0;
  // Sample on a stride: a full 1280x720 scan in JS is slow and unnecessary.
  const stride = 4 * 7;
  for (let i = 0; i < data.length; i += stride) {
    const r = data[i], g = data[i + 1], b = data[i + 2];
    if (r + g + b > 24) nonBlack += 1;
    // Quantise to 5 bits/channel so imperceptible gradients do not inflate the count.
    seen.add(((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3));
    if (seen.size > 4096) break;
  }
  const sampled = Math.ceil(data.length / stride);
  return {
    present: true,
    width: w,
    height: h,
    readable: true,
    distinctColors: seen.size,
    nonBlackFraction: nonBlack / sampled,
  };
});

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

const shotPath = join(OUT, `${LABEL}.png`);
await page.screenshot({ path: shotPath, fullPage: false });

// A canvas showing one flat colour is a cleared buffer, not a rendered frame.
const rendered =
  canvasReport.present === true &&
  canvasReport.readable === true &&
  canvasReport.distinctColors > 1 &&
  canvasReport.nonBlackFraction > 0.01;

const report = {
  label: LABEL,
  url: URL,
  adapter,
  waited_ms: waitedMs,
  frame_rendered: rendered,
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
process.exit(rendered ? 0 : 1);
