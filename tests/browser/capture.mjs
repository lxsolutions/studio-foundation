// Capture a real-GPU screenshot of a Godot web export via Playwright + system
// Chrome/Edge. This is the CI-friendly screenshot path: unlike headless Godot,
// a browser rasterizes the actual WebGL/WebGPU canvas.
//
//   node capture.mjs [--game templates/godot-game] [--preset web-webgl] \
//     [--out captures/web-main.png] [--wait 25000] [--size 1280x720]
//
// --wait must outlast the export's cold start, or the screenshot is a blank
// canvas that reads as "nothing rendered". A real 3D scene spends most of that
// time compiling WGSL: measured on an NVIDIA Tesla P40, boot completed at ~8.7s,
// shader compilation ran to ~18s, and the first drawn frame landed at ~20.9s.
// The old 6s default screenshotted every real 3D scene before it drew a single
// frame. Small 2D scenes are ready far sooner; pass a lower --wait for those.
// See docs/architecture/webgpu-performance.md.

import { spawn } from "node:child_process";
import { access, mkdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
}

const GAME = opt("game", "templates/godot-game");
const PRESET = opt("preset", "web-webgl");
const OUT = opt("out", `captures/${PRESET}.png`);
// 25s clears the measured ~20.9s cold start (boot + WGSL compilation) of a real
// 3D scene. Erring slow costs seconds; erring fast yields a blank capture that
// looks like a rendering failure.
const WAIT_MS = Number(opt("wait", "25000"));
const [W, H] = opt("size", "1280x720").split("x").map(Number);
const PORT = Number(opt("port", "8061"));
const REPO_ROOT = new URL("../../", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const URL_ = `http://127.0.0.1:${PORT}/`;

async function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { method: "HEAD" });
      if (res.ok) return;
    } catch { /* retry */ }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`server did not respond at ${url}`);
}

async function main() {
  const server = spawn(
    "python",
    ["tools/godot/serve_web.py", "--game", GAME, "--preset", PRESET, "--port", String(PORT)],
    { cwd: REPO_ROOT, stdio: ["ignore", "pipe", "pipe"] }
  );
  try {
    await waitForServer(URL_, 20000);
    const browserArgs = PRESET === "web-webgpu"
      ? ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"]
      : [];
    const browser = await chromium
      .launch({ channel: "chrome", args: browserArgs })
      .catch(() => chromium.launch({ channel: "msedge", args: browserArgs }));
    const page = await browser.newPage({ viewport: { width: W, height: H } });
    if (PRESET === "web-webgpu") {
      await page.addInitScript(() => {
        const gpu = navigator.gpu;
        globalThis.__studioWebgpuAdapterProbe = gpu
          ? gpu.requestAdapter().then((adapter) => Boolean(adapter)).catch(() => false)
          : Promise.resolve(false);
      });
    }
    await page.goto(URL_, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("canvas", { timeout: 45000 });
    if (PRESET === "web-webgpu") {
      const evidence = await page.evaluate(async () => {
        const canvas = document.querySelector("canvas");
        let canvasContext = null;
        try {
          canvasContext = canvas?.getContext("webgpu") ?? null;
        } catch {
          // A canvas bound to another renderer cannot return WebGPU.
        }
        return {
          navigatorGpu: Boolean(navigator.gpu),
          adapter: await globalThis.__studioWebgpuAdapterProbe,
          canvasContext: Boolean(canvasContext),
        };
      });
      if (!Object.values(evidence).every(Boolean)) {
        throw new Error("incomplete WebGPU proof: " + JSON.stringify(evidence));
      }
    }
    await page.waitForTimeout(WAIT_MS); // let Godot boot + render frames
    const gameRoot = path.resolve(REPO_ROOT, GAME);
    const nestedProject = path.join(gameRoot, "project", "project.godot");
    const projectRoot = await access(nestedProject).then(
      () => path.join(gameRoot, "project"),
      () => gameRoot,
    );
    const outAbs = path.resolve(projectRoot, OUT);
    await mkdir(path.dirname(outAbs), { recursive: true });
    await page.screenshot({ path: outAbs });
    await browser.close();
    console.log(`[capture-web] wrote ${outAbs} (${W}x${H}, ${GAME}/${PRESET})`);
    return 0;
  } finally {
    server.kill();
  }
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(`[capture-web] FAILED — ${err.message}`);
    process.exit(1);
  }
);
