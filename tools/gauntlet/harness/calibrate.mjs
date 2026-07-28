#!/usr/bin/env node
// Derive the objective thresholds FROM the bar, instead of inventing them.
//
// This exists because of a mistake worth remembering. The first version of
// analyze.mjs used fixed constants, and when pointed at the best-looking build
// in the whole July 2026 wave -- The Long Silence -- it reported four defects on
// a frame that is beautiful:
//
//   flat-histogram, banding, no-surface-detail, unstable-pixels
//
// The frame was a deliberately dark, moody ship interior. The constants encoded
// one aesthetic (a bright outdoor scene) and called everything else broken.
//
// The same constants were simultaneously far too LENIENT in the other
// direction: `no-surface-detail` fires below edgeEnergy 8, our starter scored
// 10.45 and passed -- while the actual bar measures 28-30 on identical
// hardware. The gate was congratulating us for being 3x short.
//
// So: absolute thresholds are wrong in both directions at once. The whole point
// of having reference frames is that they define what good looks like,
// including its histogram. Measure the bar, then judge against the bar.
//
//   node harness/calibrate.mjs --references references/longsilence
//
// Analysis is pure PNG decode + arithmetic, so it needs no GPU and runs locally.

import { readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { launch } from './browser.mjs';
import { openAnalyzer, analyzeFrame } from './analyze.mjs';
import { readFile } from 'node:fs/promises';

const IMAGE_RE = /\.(png|jpe?g|webp)$/i;

// Metrics where a reference band is meaningful. Everything else stays absolute.
const BANDED = [
  'edgeEnergy',
  'dynamicRange',
  'lumaMean',
  'lumaStd',
  'blackPct',
  'whitePct',
  'occupiedLevels',
  'chromaMean',
  'combGaps',
];

function stats(values) {
  const s = [...values].sort((a, b) => a - b);
  const at = (p) => s[Math.min(s.length - 1, Math.max(0, Math.round((p / 100) * (s.length - 1))))];
  return {
    n: s.length,
    min: +s[0].toFixed(3),
    p25: +at(25).toFixed(3),
    median: +at(50).toFixed(3),
    p75: +at(75).toFixed(3),
    max: +s[s.length - 1].toFixed(3),
  };
}

async function main() {
  const argv = process.argv.slice(2);
  const refDir = argv[argv.indexOf('--references') + 1];
  if (!refDir || refDir.startsWith('--')) throw new Error('--references <dir> is required');
  const outPath = argv.includes('--out')
    ? argv[argv.indexOf('--out') + 1]
    : path.join(refDir, 'CALIBRATION.json');

  const files = (await readdir(refDir)).filter((f) => IMAGE_RE.test(f)).sort();
  if (!files.length) throw new Error(`no reference images in ${refDir}`);

  const browser = await launch();
  const analyzer = await openAnalyzer(browser);

  const perFrame = [];
  for (const f of files) {
    const buf = await readFile(path.join(refDir, f));
    const m = await analyzeFrame(analyzer, buf);
    perFrame.push({ file: f, metrics: m });
    console.log(`[calibrate] ${f}  edgeEnergy=${m.edgeEnergy} dynamicRange=${m.dynamicRange} black=${m.blackPct}%`);
  }
  await browser.close();

  const bands = {};
  for (const k of BANDED) {
    const vals = perFrame.map((p) => p.metrics[k]).filter((v) => typeof v === 'number');
    if (vals.length) bands[k] = stats(vals);
  }

  const calibration = {
    reference: path.basename(refDir),
    frames: files,
    bands,
    // A candidate is "materially below the bar" at this fraction of the
    // reference p25. Not the median: we are asking "is this in the same league",
    // not "is this the best frame they have".
    tolerance: 0.7,
  };

  await writeFile(outPath, JSON.stringify(calibration, null, 2));
  console.log(`\n[calibrate] wrote ${outPath}`);
  console.log(`[calibrate] the bar, from ${files.length} frames:`);
  for (const [k, b] of Object.entries(bands)) {
    console.log(`  ${k.padEnd(16)} min ${String(b.min).padStart(8)}  p25 ${String(b.p25).padStart(8)}  median ${String(b.median).padStart(8)}  max ${String(b.max).padStart(8)}`);
  }
}

main().catch((e) => {
  console.error(String(e.message ?? e));
  process.exit(2);
});
