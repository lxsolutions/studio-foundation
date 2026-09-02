// Prove the sim kernel runs in a real browser, through the exact path a Godot
// web export uses — the fourth host in the parity contract (ADR 0019).
//
//   node sim-kernel-host.mjs [--wasm <path>] [--browser chrome|msedge]
//
// `just sim-parity` already checks three hosts: the canonical Python kernel, the
// native Rust binary, and the wasm module under node. None of them is a browser,
// and the browser is the host the whole argument is about — a team told "put the
// compiled logic in a reactor module instead of fighting .NET for the main-module
// slot" is owed evidence from the place they would actually run it.
//
// So this loads `shared/godot-addons/studio_core/sim/sim_kernel_host.js` as a
// CLASSIC script, which is what JavaScriptBridge.eval() does inside a Godot
// export, and replays the frozen conformance corpus against its golden hashes.
// The GDScript half is then a thin wrapper over code this run has verified.
//
// It also instantiates the kernel a second time in the same page and interleaves
// the two. Independent instances with independent linear memories are the
// property that makes the whole approach work: a WebAssembly module loaded
// beside another does not contend with it. .NET on the web fails not because two
// modules cannot coexist, but because its runtime insists on being the one that
// boots the page.

import { readFileSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import process from "node:process";

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};

const REPO = path.resolve(new URL("../../", import.meta.url).pathname);
const WASM = path.resolve(
  opt("wasm", path.join(REPO, "services/target/wasm32-unknown-unknown/release/sim_kernel.wasm"))
);
const HOST_JS = path.join(REPO, "shared/godot-addons/studio_core/sim/sim_kernel_host.js");
const CORPUS = path.join(REPO, "tools/sim/conformance/v0.1");
const CHANNEL = opt("browser", "auto");

const failures = [];
const check = (ok, what) => {
  if (!ok) failures.push(what);
  return ok;
};

function fixtures(kind) {
  return readdirSync(path.join(CORPUS, kind))
    .filter((name) => name.endsWith(".json"))
    .sort()
    .map((name) => ({
      name,
      // RAW text, never re-serialized: some invalid fixtures are deliberately
      // unparseable (NaN), and they must reach the kernel exactly as written.
      text: readFileSync(path.join(CORPUS, kind, name), "utf8"),
    }));
}

/** The expected rejection code, dug out of text that may not be valid JSON. */
function expectedError(text) {
  try {
    return JSON.parse(text).expect_error ?? null;
  } catch {
    const marker = '"expect_error": "';
    const start = text.indexOf(marker);
    if (start < 0) return null;
    const from = start + marker.length;
    return text.slice(from, text.indexOf('"', from));
  }
}

/**
 * Structural equality, order-independent. The kernel emits object keys sorted;
 * the golden fixtures were written in declaration order. Comparing serialized
 * JSON reports every fixture as a mismatch while the hashes all agree — which
 * looks exactly like a kernel bug and is not one.
 */
function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((item, i) => deepEqual(item, b[i]))
    );
  }
  if (typeof a !== "object") return false;
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length &&
    keys.every((key) => Object.hasOwn(b, key) && deepEqual(a[key], b[key]))
  );
}

async function main() {
  let wasmBytes;
  try {
    wasmBytes = readFileSync(WASM);
  } catch {
    console.error(
      `sim_kernel.wasm not found at ${WASM}\n` +
        "Build it: cd services && cargo build -p sim-kernel --release --target wasm32-unknown-unknown"
    );
    return 2;
  }
  const hostSource = readFileSync(HOST_JS, "utf8");

  // A minimal origin: the kernel must arrive over HTTP as application/wasm so the
  // instantiateStreaming path is the one under test, not the arrayBuffer fallback.
  const server = createServer((req, res) => {
    if (req.url.startsWith("/sim_kernel.wasm")) {
      res.writeHead(200, { "content-type": "application/wasm" });
      res.end(wasmBytes);
      return;
    }
    res.writeHead(200, { "content-type": "text/html" });
    res.end("<!doctype html><title>studio sim kernel host</title>");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;

  let chromium;
  try {
    ({ chromium } = await import("playwright-core"));
  } catch {
    server.close();
    console.error("playwright-core not installed — run: cd tests/browser && npm ci");
    return 2;
  }
  const launch = (channel) => chromium.launch({ channel });
  let browser;
  try {
    browser =
      CHANNEL === "auto" ? await launch("chrome").catch(() => launch("msedge")) : await launch(CHANNEL);
  } catch (error) {
    server.close();
    console.error(`could not launch a system browser: ${error.message}`);
    return 2;
  }

  try {
    const page = await browser.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    page.on("console", (msg) => {
      if (msg.type() === "error") pageErrors.push(msg.text());
    });
    await page.goto(origin, { waitUntil: "domcontentloaded" });

    // Exactly what JavaScriptBridge.eval() does: a classic script, page scope.
    await page.addScriptTag({ content: hostSource });

    check(
      await page.evaluate(() => typeof globalThis.__studio_sim_kernel === "object"),
      "the host script must expose __studio_sim_kernel"
    );
    check(
      (await page.evaluate(() => globalThis.__studio_sim_kernel.contract)) === 1,
      "host contract version must be 1 (sim_kernel.gd asserts it)"
    );

    // Calling before the module is ready must be answerable, not throw: GDScript
    // cannot catch a JS exception across the bridge.
    const early = JSON.parse(
      await page.evaluate(() => globalThis.__studio_sim_kernel.run("{}"))
    );
    check(early.code === "host_not_ready", `early run must report host_not_ready, got ${early.code}`);

    await page.evaluate((url) => globalThis.__studio_sim_kernel.load(url), `${origin}/sim_kernel.wasm`);
    await page.waitForFunction(() => globalThis.__studio_sim_kernel.status() !== "loading", {
      timeout: 30000,
    });
    const status = await page.evaluate(() => globalThis.__studio_sim_kernel.status());
    if (!check(status === "ready", `kernel must reach 'ready', got '${status}'`)) {
      console.error(await page.evaluate(() => globalThis.__studio_sim_kernel.error()));
      return 1;
    }

    // load() is idempotent — a second scene, a second eval, must not restart it.
    await page.evaluate((url) => globalThis.__studio_sim_kernel.load(url), `${origin}/nonexistent.wasm`);
    check(
      (await page.evaluate(() => globalThis.__studio_sim_kernel.status())) === "ready",
      "a second load() must not disturb a ready kernel"
    );

    const valid = fixtures("valid");
    check(valid.length >= 5, `expected at least 5 valid fixtures, found ${valid.length}`);
    for (const fixture of valid) {
      const raw = await page.evaluate(
        (text) => globalThis.__studio_sim_kernel.run(text),
        fixture.text
      );
      const actual = JSON.parse(raw);
      const expect = JSON.parse(fixture.text).expect;
      if (!check(!actual.error, `${fixture.name}: kernel rejected a valid replay (${actual.code})`)) {
        continue;
      }
      for (const key of ["final_state", "state_hash", "hash_log", "navigation"]) {
        check(
          deepEqual(actual[key], expect[key]),
          `${fixture.name}: browser ${key} differs from the golden value`
        );
      }
    }

    const invalid = fixtures("invalid");
    check(invalid.length >= 8, `expected at least 8 invalid fixtures, found ${invalid.length}`);
    for (const fixture of invalid) {
      const actual = JSON.parse(
        await page.evaluate((text) => globalThis.__studio_sim_kernel.run(text), fixture.text)
      );
      check(
        actual.code === expectedError(fixture.text),
        `${fixture.name}: browser rejection code ${actual.code}, expected ${expectedError(fixture.text)}`
      );
    }

    // Two instances, one page, interleaved: the coexistence property itself.
    const interleaved = await page.evaluate(async ([url, text]) => {
      const load = async () => {
        const { instance } = await WebAssembly.instantiateStreaming(await fetch(url), {});
        return instance.exports;
      };
      const run = (wasm, replay) => {
        const input = new TextEncoder().encode(replay);
        const ptr = wasm.sim_alloc(input.length);
        new Uint8Array(wasm.memory.buffer, ptr, input.length).set(input);
        const packed = BigInt(wasm.sim_run(ptr, input.length));
        wasm.sim_free(ptr, input.length);
        const outPtr = Number(packed >> 32n);
        const outLen = Number(packed & 0xffffffffn);
        const out = new TextDecoder().decode(new Uint8Array(wasm.memory.buffer, outPtr, outLen));
        wasm.sim_free(outPtr, outLen);
        return JSON.parse(out).state_hash;
      };
      const [a, b] = [await load(), await load()];
      const sameMemory = a.memory === b.memory;
      // Interleave so a shared or clobbered heap would show up as a wrong hash.
      const first = run(a, text);
      const second = run(b, text);
      const again = run(a, text);
      return { sameMemory, first, second, again, viaHost: JSON.parse(globalThis.__studio_sim_kernel.run(text)).state_hash };
    }, [`${origin}/sim_kernel.wasm`, valid[0].text]);

    const golden = JSON.parse(valid[0].text).expect.state_hash;
    check(!interleaved.sameMemory, "two instances must not share linear memory");
    check(interleaved.first === golden, "instance A must match the golden hash");
    check(interleaved.second === golden, "instance B must match the golden hash");
    check(interleaved.again === golden, "instance A must be unaffected by instance B");
    check(interleaved.viaHost === golden, "the host module must match the golden hash");

    check(pageErrors.length === 0, `page reported errors: ${pageErrors.slice(0, 3).join(" | ")}`);

    if (failures.length) {
      console.error(`\nsim-kernel browser host FAILED (${failures.length}):`);
      for (const failure of failures) console.error(`  - ${failure}`);
      return 1;
    }
    console.log(
      `sim-kernel browser host OK — ${valid.length} valid + ${invalid.length} invalid fixtures ` +
        `replayed in ${await browser.version()}, all matching the golden hashes; ` +
        "two instances coexisted in one page with separate memories."
    );
    return 0;
  } finally {
    await browser.close();
    server.close();
  }
}

process.exit(await main());
