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
const SETTLE_MS = Number(opt("settle", "3000"));
const SAMPLE_EARLY = args.includes("--sample-early");
const PAUSE_STACK = args.includes("--pause-stack");
const BROWSER_CHANNEL = opt("browser", "auto");
const GAME = opt("game", "templates/godot-game");
const PRESET = opt("preset", "web-webgl");
const REPO_ROOT = new URL("../../", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const MAX_CONSOLE_MESSAGES = 2000;
const MAX_DIAGNOSTIC_LINES = 200;
const MAX_DIAGNOSTIC_LINE_LENGTH = 1200;

const FATAL_PATTERNS = [
  /uncaught/i,
  /unhandled rejection/i,
  /wasm.*(fail|error)/i,
  /webgl.*(not supported|context creation failed|unavailable)/i,
  /webgpu.*(not supported|context creation failed|unavailable|fail|error)/i,
  /failed to (load|fetch)/i,
  /\babort\(/i,
  /RuntimeError/,
  /AddressSanitizer|heap-buffer-overflow|use-after-free|double-free/i,
  /SAFE_HEAP|segmentation fault|invalid (load|store)|out of bounds|alignment fault/i,
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

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function clipDiagnostic(line) {
  return line.length > MAX_DIAGNOSTIC_LINE_LENGTH
    ? `${line.slice(0, MAX_DIAGNOSTIC_LINE_LENGTH)}... [truncated]`
    : line;
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

  let browser = null;
  try {
    await Promise.race([waitForServer(TARGET_URL, 20000), serverExited]);

    // 2. Drive installed Chrome or Edge.
    const browserArgs = PRESET === "web-webgpu"
      ? ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"]
      : [];
    const launchBrowser = (channel) => chromium.launch({ channel, args: browserArgs });
    browser = await withTimeout(
      BROWSER_CHANNEL === "auto"
        ? launchBrowser("chrome").catch(() => launchBrowser("msedge"))
        : launchBrowser(BROWSER_CHANNEL),
      20000,
      `browser launch (${BROWSER_CHANNEL})`
    );
    const page = await browser.newPage();
    const cdp = PAUSE_STACK ? await page.context().newCDPSession(page) : null;
    if (cdp) await cdp.send("Debugger.enable");

    if (PRESET === "web-webgpu") {
      await page.addInitScript(() => {
        const evidence = {
          adapterRequests: 0,
          deviceRequests: 0,
          requestedContexts: [],
          webgpuCanvasContexts: 0,
          wasmMemoryBytes: 0,
        };
        globalThis.__studioWebgpuEvidence = evidence;
        setInterval(() => {
          if (typeof engine !== "undefined" && engine.rtenv?.HEAP8?.buffer) {
            evidence.wasmMemoryBytes = Math.max(
              evidence.wasmMemoryBytes,
              engine.rtenv.HEAP8.buffer.byteLength
            );
          }
        }, 10);

        if (typeof WebAssembly.instantiateStreaming === "function") {
          const originalInstantiateStreaming = WebAssembly.instantiateStreaming.bind(WebAssembly);
          WebAssembly.instantiateStreaming = async function (...instantiateArgs) {
            const result = await originalInstantiateStreaming(...instantiateArgs);
            globalThis.__studioWasmMemory = result?.instance?.exports?.memory || null;
            return result;
          };
        }

        const instrumentContexts = (prototype) => {
          if (!prototype?.getContext) return;
          const originalGetContext = prototype.getContext;
          prototype.getContext = function (type, ...contextArgs) {
            evidence.requestedContexts.push(String(type));
            const context = originalGetContext.call(this, type, ...contextArgs);
            if (type === "webgpu" && context) evidence.webgpuCanvasContexts += 1;
            return context;
          };
        };
        instrumentContexts(HTMLCanvasElement.prototype);
        if (typeof OffscreenCanvas !== "undefined") {
          instrumentContexts(OffscreenCanvas.prototype);
        }

        if (navigator.gpu) {
          const originalRequestAdapter = navigator.gpu.requestAdapter.bind(navigator.gpu);
          navigator.gpu.requestAdapter = async function (...adapterArgs) {
            evidence.adapterRequests += 1;
            const adapter = await originalRequestAdapter(...adapterArgs);
            if (adapter) {
              const originalRequestDevice = adapter.requestDevice.bind(adapter);
              adapter.requestDevice = async function (...deviceArgs) {
                evidence.deviceRequests += 1;
                return originalRequestDevice(...deviceArgs);
              };
            }
            return adapter;
          };
        }
      });
    }

    const consoleMessages = [];
    const consoleErrors = [];
    const rememberConsoleMessage = (line) => {
      consoleMessages.push(line);
      if (consoleMessages.length > MAX_CONSOLE_MESSAGES) consoleMessages.shift();
    };
    page.on("console", (msg) => {
      const line = `[${msg.type()}] ${msg.text()}`;
      rememberConsoleMessage(line);
      if (msg.type() === "error") consoleErrors.push(line);
    });
    page.on("pageerror", (err) => {
      const line = `[pageerror] ${String(err)}`;
      rememberConsoleMessage(line);
      consoleErrors.push(line);
    });

    await page.goto(TARGET_URL, { waitUntil: "domcontentloaded", timeout: TIMEOUT_MS });

    // Godot renders into a <canvas>; wait for it to exist and have a real backing size.
    await page.waitForSelector("canvas", { timeout: TIMEOUT_MS });
    await page.waitForFunction(
      () => {
        const c = document.querySelector("canvas");
        return c && c.width > 0 && c.height > 0;
      },
      undefined,
      { timeout: TIMEOUT_MS }
    );

    let webgpuEvidence = null;
    if (PRESET === "web-webgpu") {
      if (SAMPLE_EARLY) {
        await page.waitForTimeout(1000);
        webgpuEvidence = await withTimeout(
          page.evaluate(() => ({
            navigatorGpu: Boolean(navigator.gpu),
            wasmMemoryBytes: globalThis.__studioWasmMemory?.buffer?.byteLength || (typeof engine !== "undefined" ? engine.rtenv?.HEAP8?.buffer?.byteLength : 0) || 0,
            mallocTrace: globalThis.__studioMallocTrace || null,
            ...globalThis.__studioWebgpuEvidence,
          })),
          5000,
          "early WebGPU evidence sample"
        );
      } else {
        await page.waitForFunction(
          () => globalThis.__studioWebgpuEvidence?.deviceRequests > 0,
          undefined,
          { timeout: TIMEOUT_MS }
        );
      }
    }

    // Let the main loop tick so lazy errors surface. Normal proof samples after
    // this window; diagnostic mode can sample early if a frozen runtime would
    // prevent a second page evaluation.
    await page.waitForTimeout(SETTLE_MS);
    if (cdp) {
      const paused = new Promise((resolve) => cdp.once("Debugger.paused", resolve));
      await cdp.send("Debugger.pause");
      const pauseEvent = await withTimeout(paused, 5000, "debugger pause");
      console.error("blocked Wasm stack:");
      for (const frame of pauseEvent.callFrames.slice(0, 30)) {
        console.error(`  ${frame.functionName || "<anonymous>"} @ ${frame.url || frame.location.scriptId}:${frame.location.lineNumber}:${frame.location.columnNumber}`);
      }
      await cdp.send("Debugger.resume");
    }
    if (PRESET === "web-webgpu" && !PAUSE_STACK) {
      const settledEvidence = await withTimeout(
        page.evaluate(() => ({
          navigatorGpu: Boolean(navigator.gpu),
          wasmMemoryBytes: globalThis.__studioWasmMemory?.buffer?.byteLength || (typeof engine !== "undefined" ? engine.rtenv?.HEAP8?.buffer?.byteLength : 0) || 0,
          mallocTrace: globalThis.__studioMallocTrace || null,
          ...globalThis.__studioWebgpuEvidence,
        })),
        5000,
        "settled WebGPU evidence sample"
      ).catch(() => null);
      if (settledEvidence) {
        webgpuEvidence = settledEvidence;
      }
    }

    const fatal = consoleMessages.filter((line) => FATAL_PATTERNS.some((p) => p.test(line)));
    let failed = false;
    if (PAUSE_STACK) failed = true;
    if (PRESET === "web-webgpu" && !webgpuEvidence) {
      console.error("smoke FAILED: WebGPU evidence sampling timed out");
      failed = true;
    }
    if (webgpuEvidence) {
      const requestedGl = webgpuEvidence.requestedContexts.some(
        (type) => type === "webgl" || type === "webgl2"
      );
      const complete = webgpuEvidence.navigatorGpu
        && webgpuEvidence.adapterRequests > 0
        && webgpuEvidence.deviceRequests > 0
        && webgpuEvidence.webgpuCanvasContexts > 0
        && !requestedGl;
      if (!complete) {
        console.error(`smoke FAILED: incomplete WebGPU proof: ${JSON.stringify(webgpuEvidence)}`);
        failed = true;
      }
    }
    if (fatal.length > 0) {
      console.error("smoke FAILED - fatal console errors:");
      for (const line of fatal.slice(-MAX_DIAGNOSTIC_LINES)) {
        console.error(`  ${clipDiagnostic(line)}`);
      }
      failed = true;
    }
    if (failed) {
      const relevant = consoleMessages.filter(
        (line) =>
          PAUSE_STACK || /\[error\]|\[tint-trace\]|\[rd-init-trace\]|\[heap-trace\]|\[shader\]|\[diag|\[js-p|precompiled|forward mobile|pipeline|shader|Godot Engine|WebGPU/i.test(line)
          || FATAL_PATTERNS.some((pattern) => pattern.test(line))
      );
      if (webgpuEvidence?.mallocTrace) {
        const trace = webgpuEvidence.mallocTrace;
        console.error(`malloc trace tail (count=${trace.count}): ${JSON.stringify(trace.events.slice(-24))}`);
      }
      console.error(`smoke diagnostics (last ${MAX_DIAGNOSTIC_LINES} relevant browser messages):`);
      for (const line of relevant.slice(-MAX_DIAGNOSTIC_LINES)) {
        console.error(`  ${clipDiagnostic(line)}`);
      }
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
    if (browser) {
      await withTimeout(browser.close(), 5000, "browser close").catch((err) => {
        console.error(`smoke cleanup warning: ${err.message}`);
      });
    }
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
