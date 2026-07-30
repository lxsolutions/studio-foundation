#!/usr/bin/env node
// Does the game actually WORK?
//
// The visual gate answers "does it look right" and the timing gate answers "is
// it fast". Neither notices that pressing W does nothing, that firing is a
// no-op, or that a transform went NaN twelve seconds ago and quietly deleted
// half the scene. A beautiful build with dead controls passes every visual
// check ever written.
//
// This is lifted from the one genuinely novel idea in Claude-of-Duty's
// tools/playtest.mjs -- hold a key, then assert the player actually moved a
// measured distance -- and generalised against the runtime contract.
//
//   node harness/playtest.mjs --url http://127.0.0.1:8099/game/ \
//     --checks playtest.json --remote smeagol
//
// checks file:
//   { "checks": [
//       { "name": "W moves the player", "probe": "playerPos",
//         "input": { "hold": { "keys": ["KeyW"], "ms": 900 } },
//         "expect": { "distanceMin": 2 } },
//       { "name": "fire registers", "probe": "shotsFired",
//         "input": { "keys": ["Space"] }, "expect": { "increaseMin": 1 } },
//       { "name": "no NaN transforms", "nanScan": true }
//   ] }

import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { launch } from './browser.mjs';
import { connectRemote } from './remote.mjs';

function parseArgs(argv) {
  const a = {};
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const next = () => argv[++i];
    if (k === '--url') a.url = next();
    else if (k === '--checks') a.checks = next();
    else if (k === '--remote') a.remote = next();
    else if (k === '--gpu-profile') a.gpuProfile = next();
    else if (k === '--serve-port') a.servePort = Number(next());
    else if (k === '--out') a.out = next();
  }
  if (!a.url) throw new Error('--url is required');
  if (!a.checks) throw new Error('--checks <file> is required');
  return a;
}

function distance(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return null;
  let s = 0;
  for (let i = 0; i < a.length; i++) s += (a[i] - b[i]) ** 2;
  return Math.sqrt(s);
}

async function applyInput(page, input = {}) {
  if (input.script) await page.evaluate(input.script);
  if (input.click) await page.mouse.click(input.click[0], input.click[1]);
  if (input.keys) for (const k of input.keys) await page.keyboard.press(k);
  if (input.hold) {
    for (const k of input.hold.keys) await page.keyboard.down(k);
    await page.waitForTimeout(input.hold.ms ?? 800);
    for (const k of input.hold.keys) await page.keyboard.up(k);
  }
  if (input.mouseMove) await page.mouse.move(input.mouseMove[0], input.mouseMove[1]);
  await page.waitForTimeout(input.settleMs ?? 250);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const spec = JSON.parse(await readFile(args.checks, 'utf8'));

  let browser;
  let context;
  let closeRemote = null;
  if (args.remote) {
    const r = await connectRemote({
      host: args.remote,
      servePort: args.servePort ?? 8099,
      gpuProfile: args.gpuProfile ?? 'webgpu',
    });
    browser = r.browser;
    closeRemote = r.close;
    context = browser.contexts()[0] ?? (await browser.newContext());
  } else {
    browser = await launch();
    context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  }

  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 300)));

  await page.goto(args.url, { waitUntil: 'domcontentloaded', timeout: 60000 });

  // Wait for the contract, then for the game to say it is ready.
  const hasContract = await page
    .waitForFunction(() => !!globalThis.__gauntlet, { timeout: 30000 })
    .then(() => true)
    .catch(() => false);

  if (!hasContract) {
    console.log('PLAYTEST BLOCKED — the build does not implement runtime/gauntlet-hooks.js.');
    console.log('Playability cannot be asserted without a state probe. Import the hooks and');
    console.log('register { scene, probe } before running this.');
    if (closeRemote) await closeRemote(); else await browser.close();
    process.exit(2);
  }

  await page.evaluate(() => globalThis.__gauntlet.ready).catch(() => {});
  await page.waitForTimeout(spec.settleMs ?? 2500);

  const results = [];
  for (const check of spec.checks ?? []) {
    if (check.nanScan) {
      const scan = await page.evaluate(() => globalThis.__gauntlet.nanScan());
      if (scan == null) {
        results.push({ name: check.name, pass: null, detail: 'no scene registered — cannot scan' });
      } else {
        results.push({
          name: check.name,
          pass: scan.nonFinite === 0,
          detail: `${scan.nonFinite} non-finite transforms across ${scan.objects} objects` +
            (scan.offenders.length ? ` — ${scan.offenders.join(', ')}` : ''),
        });
      }
      continue;
    }

    const before = await page.evaluate((k) => globalThis.__gauntlet.probe()[k], check.probe);
    await applyInput(page, check.input);
    const after = await page.evaluate((k) => globalThis.__gauntlet.probe()[k], check.probe);

    const e = check.expect ?? {};
    let pass = true;
    let detail = '';

    if (e.distanceMin != null) {
      const d = distance(before, after);
      detail = `moved ${d == null ? 'n/a' : d.toFixed(3)} (min ${e.distanceMin})`;
      pass = d != null && d >= e.distanceMin;
    } else if (e.increaseMin != null) {
      const d = (after ?? 0) - (before ?? 0);
      detail = `${before} -> ${after} (delta ${d}, min +${e.increaseMin})`;
      pass = d >= e.increaseMin;
    } else if (e.changed === true) {
      detail = `${JSON.stringify(before)} -> ${JSON.stringify(after)}`;
      pass = JSON.stringify(before) !== JSON.stringify(after);
    } else if (e.unchanged === true) {
      detail = `${JSON.stringify(before)} -> ${JSON.stringify(after)}`;
      pass = JSON.stringify(before) === JSON.stringify(after);
    } else {
      detail = 'no expectation declared';
      pass = null;
    }
    results.push({ name: check.name, pass, detail });
  }

  if (closeRemote) await closeRemote();
  else await browser.close();

  const failed = results.filter((r) => r.pass === false);
  const skipped = results.filter((r) => r.pass === null);

  const L = ['# Playtest', ''];
  for (const r of results) {
    const mark = r.pass === true ? 'PASS' : r.pass === false ? '**FAIL**' : 'SKIP';
    L.push(`- ${mark} — ${r.name}: ${r.detail}`);
  }
  if (pageErrors.length) {
    L.push('');
    L.push('## Uncaught page errors');
    for (const e of pageErrors) L.push(`- ${e}`);
  }
  L.push('');
  L.push(`**${results.length - failed.length - skipped.length} passed · ${failed.length} failed · ${skipped.length} skipped**`);
  const md = L.join('\n');

  if (args.out) {
    await mkdir(path.dirname(args.out), { recursive: true });
    await writeFile(args.out, md);
  }
  console.log(md);
  process.exit(failed.length || pageErrors.length ? 1 : 0);
}

main().catch((e) => {
  console.error(String(e.message ?? e));
  process.exit(2);
});
