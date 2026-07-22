// Browser smoke test: serve a Godot web export, open it in installed Chrome/Edge,
// fail on fatal console errors or a page that never reaches the Godot canvas.
//
//   node smoke.mjs [--url http://127.0.0.1:8060/] [--timeout 45000]
//
// Uses playwright-core + system browsers only (no downloaded browsers), per the
// repo's offline-first principle. Exits non-zero on failure.

import { spawn } from "node:child_process";
import process from "node:process";
import { chromium } from "playwright-core";

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
}

const TARGET_URL = opt("url", "http://127.0.0.1:8060/");
const TIMEOUT_MS = Number(opt("timeout", "45000"));
const GAME = opt("game", "templates/godot-game");
const PRESET = opt("preset", "web-webgl");
const REPO_ROOT = new URL("../../", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

const FATAL_PATTERNS = [
  /uncaught/i,
  /unhandled rejection/i,
  /wasm.*(fail|error)/i,
  /webgl.*(not supported|context creation failed|unavailable)/i,
  /webgpu.*(not supported|context creation failed|unavailable|fail|error)/i,
  /failed to (load|fetch)/i,
  /\babort\(/i,
  /RuntimeError/,
];

async function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { method: "HEAD" });
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`server did not respond at ${url} within ${timeoutMs}ms`);
}

async function main() {
  // 1. Start the repo's COOP/COEP-aware static server.
  const server = spawn(
    "python",
    ["tools/godot/serve_web.py", "--game", GAME, "--preset", PRESET, "--port", new URL(TARGET_URL).port || "8060"],
    { cwd: REPO_ROOT, stdio: ["ignore", "pipe", "pipe"] }
  );
  server.stderr.on("data", () => {}); // server logs are noise unless it dies
  const serverExited = new Promise((_, reject) =>
    server.on("exit", (code) => reject(new Error(`serve_web.py exited early (code ${code})`)))
  );

  try {
    await Promise.race([waitForServer(TARGET_URL, 20000), serverExited]);

    // 2. Drive installed Chrome or Edge.
    const browserArgs = PRESET === "web-webgpu"
      ? ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"]
      : [];
    const browser = await chromium
      .launch({ channel: "chrome", args: browserArgs })
      .catch(() => chromium.launch({ channel: "msedge", args: browserArgs }));
    const page = await browser.newPage();

    if (PRESET === "web-webgpu") {
      // Start the adapter probe before Godot requests its device. On Windows,
      // a second request after the engine starts can return null because Chrome
      // does not support multiple GPU adapters simultaneously.
      await page.addInitScript(() => {
        const gpu = navigator.gpu;
        globalThis.__studioWebgpuAdapterProbe = gpu
          ? gpu.requestAdapter().then((adapter) => Boolean(adapter)).catch(() => false)
          : Promise.resolve(false);
      });
    }

    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));

    await page.goto(TARGET_URL, { waitUntil: "domcontentloaded", timeout: TIMEOUT_MS });

    // Godot renders into a <canvas>; wait for it to exist and have a real backing size.
    await page.waitForSelector("canvas", { timeout: TIMEOUT_MS });
    await page.waitForFunction(
      () => {
        const c = document.querySelector("canvas");
        return c && c.width > 0 && c.height > 0;
      },
      { timeout: TIMEOUT_MS }
    );

    let webgpuEvidence = null;
    if (PRESET === "web-webgpu") {
      webgpuEvidence = await page.evaluate(async () => {
        const gpu = navigator.gpu;
        const adapter = await globalThis.__studioWebgpuAdapterProbe;
        const canvas = document.querySelector("canvas");
        let canvasContext = null;
        try {
          canvasContext = canvas?.getContext("webgpu") ?? null;
        } catch {
          // A canvas already bound to another renderer cannot return WebGPU.
        }
        return {
          navigatorGpu: Boolean(gpu),
          adapter,
          canvasContext: Boolean(canvasContext),
        };
      });
    }

    // Let the main loop tick a few frames so lazy errors surface.
    await page.waitForTimeout(3000);

    await browser.close();

    if (webgpuEvidence && !Object.values(webgpuEvidence).every(Boolean)) {
      console.error(`smoke FAILED — incomplete WebGPU proof: ${JSON.stringify(webgpuEvidence)}`);
      return 1;
    }

    const fatal = consoleErrors.filter((line) => FATAL_PATTERNS.some((p) => p.test(line)));
    if (fatal.length > 0) {
      console.error("smoke FAILED — fatal console errors:");
      for (const line of fatal) console.error(`  ${line}`);
      return 1;
    }
    if (consoleErrors.length > 0) {
      console.log(`smoke passed with ${consoleErrors.length} non-fatal console error(s):`);
      for (const line of consoleErrors.slice(0, 10)) console.log(`  ${line}`);
    }
    if (webgpuEvidence) {
      console.log("WebGPU proof OK — navigator.gpu, GPU adapter, and active canvas context verified");
    }
    const renderProof = webgpuEvidence
      ? "rendered a live Godot canvas with an active WebGPU context"
      : "rendered a live Godot canvas";
    console.log(`smoke OK — ${TARGET_URL} ${renderProof} (${GAME}, ${PRESET})`);
    return 0;
  } finally {
    server.kill();
  }
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(`smoke FAILED — ${err.message}`);
    process.exit(1);
  }
);
