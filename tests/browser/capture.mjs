// Capture a real-GPU screenshot of a Godot web export via Playwright + system
// Chrome/Edge. This is the CI-friendly screenshot path: unlike headless Godot,
// a browser rasterizes the actual WebGL/WebGPU canvas.
//
//   node capture.mjs [--game templates/godot-game] [--preset web-webgl] \
//     [--out captures/web-main.png] [--wait 6000] [--size 1280x720]

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
const WAIT_MS = Number(opt("wait", "6000"));
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
    const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch({ channel: "msedge" }));
    const page = await browser.newPage({ viewport: { width: W, height: H } });
    await page.goto(URL_, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("canvas", { timeout: 45000 });
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
