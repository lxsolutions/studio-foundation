#!/usr/bin/env node
// Does a metric actually separate known-good from known-bad?
//
// A metric that cannot tell labelled cases apart is worse than no metric: it
// gates a loop with noise, and it will eventually be optimised directly. This
// happened here -- `edgeEnergy` was gamed to 38 by tiling one texture over
// everything while the frame got visibly worse. Before trusting a new measure,
// point it at frames whose verdict you already know.
//
//   node harness/discriminate.mjs \
//     --set good=references/longsilence \
//     --set tiled=runs/r004/frames \
//     --set empty=runs/r009/frames
//
// Analysis is pure PNG decode plus arithmetic, so this needs no GPU.

import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { launch } from './browser.mjs';
import { openAnalyzer, analyzeFrame } from './analyze.mjs';

const IMAGE_RE = /\.(png|jpe?g|webp)$/i;

// The metrics worth comparing across labelled sets. Add to this as the harness
// grows; the point is to see at a glance which ones actually discriminate.
const COLUMNS = [
  ['edgeEnergy', (m) => m.edgeEnergy],
  ['dynRange', (m) => m.dynamicRange],
  ['emptyBlk%', (m) => m.composition?.emptyBlockPct],
  ['detailBlk%', (m) => m.composition?.detailedBlockPct],
  ['repeatBlk%', (m) => m.composition?.repeatBlockPct],
  ['blkEdgeP10', (m) => m.composition?.blockEdgeP10],
  ['blkEdgeP50', (m) => m.composition?.blockEdgeP50],
  ['blkEdgeP90', (m) => m.composition?.blockEdgeP90],
];

function parseSets(argv) {
  const sets = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--set') {
      const raw = argv[++i] ?? '';
      const eq = raw.indexOf('=');
      if (eq < 0) throw new Error(`--set expects label=dir, got "${raw}"`);
      sets.push({ label: raw.slice(0, eq), dir: raw.slice(eq + 1) });
    }
  }
  if (sets.length < 2) throw new Error('need at least two --set label=dir arguments to compare');
  return sets;
}

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

async function main() {
  const sets = parseSets(process.argv.slice(2));
  const browser = await launch();
  const analyzer = await openAnalyzer(browser);

  const results = [];
  for (const set of sets) {
    const files = (await readdir(set.dir)).filter((f) => IMAGE_RE.test(f)).sort();
    if (!files.length) throw new Error(`no images in ${set.dir}`);
    const rows = [];
    for (const f of files) {
      const buf = await readFile(path.join(set.dir, f));
      rows.push(await analyzeFrame(analyzer, buf));
    }
    results.push({ ...set, n: rows.length, rows });
    console.error(`[discriminate] ${set.label}: ${rows.length} frames from ${set.dir}`);
  }
  await browser.close();

  const pad = (s, n) => String(s ?? '—').padStart(n);
  const head = ['set'.padEnd(10), ...COLUMNS.map(([n]) => pad(n, 11))].join(' ');
  console.log('\n' + head);
  console.log('-'.repeat(head.length));
  for (const r of results) {
    const cells = COLUMNS.map(([, get]) => {
      const vals = r.rows.map(get).filter((v) => typeof v === 'number');
      const m = mean(vals);
      return pad(m === null ? '—' : m.toFixed(2), 11);
    });
    console.log([r.label.padEnd(10), ...cells].join(' '));
  }

  // A column only earns its place if the labelled sets do not overlap on it.
  console.log('\nseparation (max spread between set means, higher = more discriminating):');
  for (const [name, get] of COLUMNS) {
    const means = results
      .map((r) => mean(r.rows.map(get).filter((v) => typeof v === 'number')))
      .filter((v) => v !== null);
    if (means.length < 2) continue;
    const lo = Math.min(...means);
    const hi = Math.max(...means);
    const spread = hi - lo;
    const rel = lo !== 0 ? spread / Math.abs(lo) : Infinity;
    console.log(`  ${name.padEnd(12)} ${spread.toFixed(2).padStart(8)}  (${(rel * 100).toFixed(0)}% of min)`);
  }
}

main().catch((e) => {
  console.error(String(e.message ?? e));
  process.exit(2);
});
