/**
 * Measure what a player actually waits through before a game is playable.
 *
 * "45.8 MiB" is a directory listing, not a measurement. What matters is bytes on
 * the wire after compression, on a connection someone might really have, and how
 * that time divides between downloading, compiling wasm, compiling shaders and
 * reaching a frame. Those four have completely different fixes, so reporting one
 * number for all of them tells you nothing about what to do.
 *
 * Measured on localhost, download time is a fiction — a 45 MiB payload arrives in
 * under a second and the profile says the problem is shader compilation. So this
 * throttles by default, via CDP, and records which profile produced the number.
 * An unthrottled run is still available and is labelled as such, because it is
 * the right measurement for isolating compile cost and the wrong one for
 * answering "how long does this take to load".
 *
 * Cold vs warm is a separate axis: a warm run keeps the HTTP cache, which is what
 * a returning player sees, and the gap between them is the entire argument for
 * caching work.
 *
 *   node startup-probe.mjs --url URL [--throttle broadband|fast4g|slow4g|none]
 *                                    [--warm] [--out DIR] [--label NAME]
 */

import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : d;
};

const URL = arg("url", "http://127.0.0.1:8099/index.html");
const OUT = arg("out", "./startup-profile");
const LABEL = arg("label", "startup");
const THROTTLE = arg("throttle", "broadband");
const WARM = argv.includes("--warm");
const BUDGET_MS = Number(arg("budget", "180000"));

// Round numbers chosen to be defensible rather than flattering. Latency is
// included because handshake cost is a real part of a cold start and omitting it
// makes small-file counts look free.
const PROFILES = {
  none: null,
  broadband: { downloadThroughput: (25 * 1024 * 1024) / 8, uploadThroughput: (5 * 1024 * 1024) / 8, latency: 20 },
  fast4g: { downloadThroughput: (9 * 1024 * 1024) / 8, uploadThroughput: (1.5 * 1024 * 1024) / 8, latency: 60 },
  slow4g: { downloadThroughput: (3 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8, latency: 150 },
};
if (!(THROTTLE in PROFILES)) {
  console.error(`unknown throttle profile ${THROTTLE}; expected one of ${Object.keys(PROFILES).join(", ")}`);
  process.exit(2);
}

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
  headless: false,
  args: [
    "--no-sandbox",
    "--enable-unsafe-webgpu",
    "--enable-features=Vulkan",
    "--ignore-gpu-blocklist",
    "--disable-vulkan-fallback-to-gl-for-testing",
  ],
});

const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
const page = await context.newPage();

// Transfer sizes come from the network layer, not from the file system: what a
// player pays for is the encoded body after content-encoding, which for wasm is
// usually far smaller than the file on disk.
const resources = [];
page.on("response", async (res) => {
  try {
    const url = res.url();
    if (url.startsWith("data:")) return;
    const h = res.headers();
    resources.push({
      url: url.split("/").pop().slice(0, 60),
      status: res.status(),
      encoding: h["content-encoding"] ?? null,
      // Header length is what the server declared; the real transferred size is
      // taken from the Resource Timing API below, which accounts for headers and
      // actual compression.
      declared_length: Number(h["content-length"] ?? 0) || null,
      from_cache: Boolean(res.fromServiceWorker?.()) || undefined,
    });
  } catch (e) {}
});

const cdp = await context.newCDPSession(page);
await cdp.send("Network.enable");
if (!WARM) {
  await cdp.send("Network.clearBrowserCache");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
}
const profile = PROFILES[THROTTLE];
if (profile) {
  await cdp.send("Network.emulateNetworkConditions", { offline: false, ...profile });
}

// A warm run needs the cache populated first, or it is just a slow cold run.
if (WARM) {
  await page.goto(URL, { waitUntil: "load", timeout: BUDGET_MS });
  await page.waitForTimeout(30_000);
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: false });
}

const t0 = Date.now();
await page.goto(URL, { waitUntil: "domcontentloaded", timeout: BUDGET_MS });
const domContentLoaded = Date.now() - t0;

/** First moment the canvas stops being a flat clear — the honest definition of
 *  "something is on screen", and the same test the render probe uses. */
async function timeToFirstFrame(deadlineMs) {
  const start = Date.now();
  while (Date.now() - start < deadlineMs) {
    const box = await page.evaluate(() => {
      const c = document.querySelector("canvas");
      if (!c) return null;
      const r = c.getBoundingClientRect();
      return { x: Math.max(0, Math.round(r.x)), y: Math.max(0, Math.round(r.y)), width: Math.round(r.width), height: Math.round(r.height) };
    });
    if (box && box.width && box.height) {
      const shot = await page.screenshot({ clip: box });
      const flat = await page.evaluate(async (b64) => {
        const blob = await (await fetch(`data:image/png;base64,${b64}`)).blob();
        const bmp = await createImageBitmap(blob);
        const off = document.createElement("canvas");
        off.width = bmp.width; off.height = bmp.height;
        const ctx = off.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(bmp, 0, 0);
        const { data } = ctx.getImageData(0, 0, bmp.width, bmp.height);
        const counts = new Map();
        let n = 0;
        for (let i = 0; i < data.length; i += 4 * 31) {
          const k = ((data[i] >> 3) << 10) | ((data[i + 1] >> 3) << 5) | (data[i + 2] >> 3);
          counts.set(k, (counts.get(k) ?? 0) + 1); n += 1;
        }
        let dom = 0;
        for (const v of counts.values()) if (v > dom) dom = v;
        return n ? dom / n >= 0.95 : true;
      }, shot.toString("base64"));
      if (!flat) return Date.now() - t0;
    }
    await page.waitForTimeout(250);
  }
  return null;
}

const firstFrameMs = await timeToFirstFrame(BUDGET_MS - (Date.now() - t0));

// Resource Timing gives the transferred size, which is the number that matters.
const timing = await page.evaluate(() => {
  const nav = performance.getEntriesByType("navigation")[0];
  const entries = performance.getEntriesByType("resource").map((e) => ({
    name: e.name.split("/").pop().slice(0, 60),
    type: e.initiatorType,
    transferred: e.transferSize,
    encoded: e.encodedBodySize,
    decoded: e.decodedBodySize,
    duration_ms: Math.round(e.duration),
    start_ms: Math.round(e.startTime),
  }));
  return {
    dom_content_loaded_ms: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
    load_event_ms: nav ? Math.round(nav.loadEventEnd) : null,
    entries,
  };
});

const sum = (f) => timing.entries.reduce((a, e) => a + (e[f] || 0), 0);
const biggest = [...timing.entries].sort((a, b) => (b.transferred || 0) - (a.transferred || 0)).slice(0, 6);

const report = {
  label: LABEL,
  url: URL,
  cache: WARM ? "warm" : "cold",
  throttle: THROTTLE,
  throttle_profile: profile
    ? { down_mbit: +((profile.downloadThroughput * 8) / 1e6).toFixed(1), latency_ms: profile.latency }
    : "unthrottled (localhost — download time is not meaningful)",
  timings_ms: {
    dom_content_loaded: domContentLoaded,
    load_event: timing.load_event_ms,
    // The headline: nothing is on screen before this.
    first_rendered_frame: firstFrameMs,
  },
  bytes: {
    transferred_total: sum("transferred"),
    encoded_total: sum("encoded"),
    decoded_total: sum("decoded"),
    compression_ratio: sum("decoded") ? +(sum("encoded") / sum("decoded")).toFixed(3) : null,
  },
  largest_transfers: biggest,
  resource_count: timing.entries.length,
};

writeFileSync(join(OUT, `${LABEL}.json`), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report, null, 2));

await browser.close();
process.exit(firstFrameMs === null ? 1 : 0);
