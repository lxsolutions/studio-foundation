#!/usr/bin/env node
// One gauntlet round, end to end.
//
// Everything deterministic happens here. The two judgment steps -- deciding HOW
// to fix, and grading the blind deck -- are the agent's job, because those are
// the only parts that actually need a mind. The script's job is to make sure
// the agent is never guessing about what changed.
//
//   node harness/round.mjs --url http://127.0.0.1:8099/game/ --shots shots.json \
//     --references references/journey --remote smeagol
//
// Emits runs/history.json (append-only) and prints a verdict telling the agent
// exactly what to do next:
//
//   FIX      objective defects exist -- fix them, do not spend a judge round
//   JUDGE    mechanically clean -- a blind deck is ready
//   REGRESSED the last change made it worse; revert or rethink before continuing

import { spawn } from 'node:child_process';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
// Where the harness lives, used only to locate its own sibling scripts.
const HARNESS = HERE;
// Where the USER is. Every path they pass -- shots, references, runs -- is
// relative to this, never to the harness. The harness must not assume it sits
// at the root of the project it is measuring; it does not, once it is vendored
// into a larger repository.
const ROOT = process.cwd();

function parseArgs(argv) {
  const a = {};
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const next = () => argv[++i];
    if (k === '--url') a.url = next();
    else if (k === '--shots') a.shots = next();
    else if (k === '--references') a.references = next();
    else if (k === '--remote') a.remote = next();
    else if (k === '--gpu-profile') a.gpuProfile = next();
    else if (k === '--runs') a.runs = next();
    else if (k === '--note') a.note = next();
    else if (k === '--preflight') a.preflight = next(); // cheap gate before the expensive round
  }
  if (!a.url) throw new Error('--url is required');
  a.runs = a.runs ?? path.join(ROOT, 'runs');
  return a;
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { cwd: ROOT, ...opts });
    let out = '';
    p.stdout?.on('data', (d) => (out += d));
    p.stderr?.on('data', (d) => (out += d));
    p.on('close', (code) => resolve({ code, out }));
  });
}

// The metrics worth tracking round over round. Anything that moves the wrong
// way here is a regression even if the frame "looks fine".
function summarize(report) {
  const shots = report.shots ?? [];
  const avg = (f) => (shots.length ? +(shots.reduce((s, x) => s + (f(x) ?? 0), 0) / shots.length).toFixed(2) : null);
  return {
    fatal: report.summary?.fatal ?? 0,
    warn: report.summary?.warn ?? 0,
    pageErrors: report.summary?.pageErrors ?? 0,
    software: report.summary?.softwareRenderer === true,
    fpsP50: report.timing?.fpsP50 ?? null,
    fpsP99: report.timing?.fpsP99 ?? null,
    bootMs: report.bootMs ?? null,
    edgeEnergy: avg((s) => s.metrics.edgeEnergy),
    dynamicRange: avg((s) => s.metrics.dynamicRange),
    combGaps: avg((s) => s.metrics.combGaps),
    instability: avg((s) => s.staticDiff?.changedPct),
    adapter: report.gpu?.availableWebGL ?? null,
    renderedOn: report.remote ? `${report.remote.host}/${report.remote.gpuProfile}` : 'local',
    applicationRenderer: report.gpu?.applicationRenderer ?? null,
  };
}

function delta(now, prev) {
  if (!prev) return null;
  const d = {};
  for (const k of ['fatal', 'warn', 'pageErrors', 'fpsP50', 'edgeEnergy', 'dynamicRange', 'combGaps', 'instability']) {
    if (typeof now[k] === 'number' && typeof prev[k] === 'number') d[k] = +(now[k] - prev[k]).toFixed(2);
  }
  return d;
}

/**
 * Did this round make things worse? Deliberately strict: it is far cheaper to
 * question a real improvement than to spend three rounds building on a
 * regression you did not notice.
 */
function regressions(d, now, prev) {
  if (!d) return [];
  const bad = [];
  if (d.fatal > 0) bad.push(`fatal findings +${d.fatal}`);
  if (d.warn > 0) bad.push(`warnings +${d.warn} (${prev.warn} -> ${now.warn})`);
  if (d.pageErrors > 0) bad.push(`page errors +${d.pageErrors}`);
  if (d.edgeEnergy < -0.75) bad.push(`surface detail down ${d.edgeEnergy} (${prev.edgeEnergy} -> ${now.edgeEnergy})`);
  if (d.dynamicRange < -10) bad.push(`dynamic range down ${d.dynamicRange}`);
  if (d.instability > 0.5) bad.push(`pixel instability +${d.instability}%`);
  if (typeof d.fpsP50 === 'number' && prev.fpsP50 && d.fpsP50 < -prev.fpsP50 * 0.2) {
    bad.push(`fps p50 down ${d.fpsP50}`);
  }
  return bad;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  await mkdir(args.runs, { recursive: true });

  const historyPath = path.join(args.runs, 'history.json');
  const history = existsSync(historyPath) ? JSON.parse(await readFile(historyPath, 'utf8')) : [];
  const roundNo = history.length + 1;
  const outDir = path.join(args.runs, `r${String(roundNo).padStart(3, '0')}`);

  // --- capture -------------------------------------------------------------
  const shotArgs = [path.join(HARNESS, 'shotset.mjs'), '--url', args.url, '--out', outDir, '--label', `round ${roundNo}`];
  if (args.shots) shotArgs.push('--shots', args.shots);
  if (args.remote) shotArgs.push('--remote', args.remote);
  // Auto-use the bar's calibration when it exists.
  if (args.references) {
    const cal = path.join(args.references, 'CALIBRATION.json');
    if (existsSync(cal)) shotArgs.push('--calibration', cal);
    else console.log(`[round] no CALIBRATION.json in ${args.references} — thresholds will be guesses. Run: node harness/calibrate.mjs --references ${args.references}`);
  }
  if (args.gpuProfile) shotArgs.push('--gpu-profile', args.gpuProfile);

  // --- preflight -----------------------------------------------------------
  // A capture round costs ~4 minutes on the remote GPU. A type error costs 2
  // seconds to detect. Never spend the former to discover the latter -- this
  // is the entire practical argument for TypeScript in this workflow.
  //
  // This BUILDS rather than only typechecking. The browser loads the emitted
  // .js, so `tsc --noEmit` would let an edited .ts pass preflight while the
  // capture measured the previous compile -- four minutes spent on a stale
  // frame, with nothing in the report to reveal it. tsconfig sets
  // noEmitOnError so a broken build cannot leave usable output behind.
  const preflight =
    args.preflight ??
    (existsSync(path.join(ROOT, 'tsconfig.json')) ? 'npx tsc' : null);
  if (preflight) {
    console.log(`[round ${roundNo}] preflight: ${preflight}`);
    const [cmd, ...rest] = preflight.split(' ');
    const pf = await run(cmd, rest, { shell: true });
    if (pf.code !== 0) {
      const md = [
        `# Round ${roundNo} — PREFLIGHT FAILED`,
        '',
        `\`${preflight}\` exited ${pf.code}. No capture was attempted.`,
        '',
        '```',
        pf.out.trim().slice(-2500),
        '```',
        '',
        'Fix this first. It costs seconds; a capture round costs minutes.',
      ].join('\n');
      await mkdir(outDir, { recursive: true });
      await writeFile(path.join(outDir, 'ROUND.md'), md);
      console.log('\n' + md);
      process.exit(1);
    }
  }

  console.log(`[round ${roundNo}] capturing...`);
  const cap = await run(process.execPath, shotArgs);
  const reportPath = path.join(outDir, 'report.json');
  if (!existsSync(reportPath)) {
    console.log(cap.out.slice(-3000));
    console.log(`\n[round ${roundNo}] VERDICT: BLOCKED — capture produced no report.`);
    process.exit(2);
  }
  const report = JSON.parse(await readFile(reportPath, 'utf8'));
  const now = summarize(report);
  const prev = history.length ? history[history.length - 1].metrics : null;
  const d = delta(now, prev);
  const regressed = regressions(d, now, prev);

  // --- verdict -------------------------------------------------------------
  let verdict;
  const allFindings = (report.shots ?? []).flatMap((s) => s.findings.map((f) => ({ shot: s.name, ...f })));

  if (now.software) {
    verdict = 'VOID';
  } else if (regressed.length) {
    verdict = 'REGRESSED';
  } else if (now.fatal > 0 || now.pageErrors > 0 || now.warn > 0) {
    verdict = 'FIX';
  } else {
    verdict = 'JUDGE';
  }

  // --- blind deck, only when it is worth building --------------------------
  let judgeDir = null;
  if (verdict === 'JUDGE' && args.references) {
    judgeDir = path.join(outDir, 'judge');
    const jr = await run(process.execPath, [
      path.join(HARNESS, 'judge.mjs'), 'pair',
      '--candidates', path.join(outDir, 'frames'),
      '--references', args.references,
      '--out', judgeDir,
      '--seed', `round${roundNo}`,
    ]);
    if (jr.code !== 0) {
      console.log(jr.out.slice(-1500));
      judgeDir = null;
      verdict = 'FIX';
    }
  }

  history.push({ round: roundNo, out: path.relative(ROOT, outDir), note: args.note ?? null, metrics: now, delta: d, verdict });
  await writeFile(historyPath, JSON.stringify(history, null, 2));

  // --- report --------------------------------------------------------------
  const L = [];
  L.push(`# Round ${roundNo} — ${verdict}`);
  L.push('');
  L.push(`Rendered on: **${now.renderedOn}** · ${now.adapter ?? 'unknown adapter'}`);
  L.push(`Application rendered through: **${now.applicationRenderer ?? 'unknown'}**`);
  if (args.note) L.push(`Change under test: ${args.note}`);
  L.push('');
  L.push('| metric | now | prev | delta |');
  L.push('|---|---|---|---|');
  for (const k of ['fatal', 'warn', 'pageErrors', 'fpsP50', 'edgeEnergy', 'dynamicRange', 'combGaps', 'instability']) {
    const dv = d?.[k];
    L.push(`| ${k} | ${now[k] ?? '—'} | ${prev?.[k] ?? '—'} | ${dv == null ? '—' : (dv > 0 ? '+' : '') + dv} |`);
  }
  L.push('');

  if (verdict === 'VOID') {
    L.push('**SOFTWARE RENDERER — this round is void.** Re-run with `--remote smeagol`.');
    L.push('Do not act on these findings: software rendering degrades the image enough');
    L.push('to invent defects that do not exist on real hardware.');
  } else if (verdict === 'REGRESSED') {
    L.push('**The last change made things worse:**');
    for (const r of regressed) L.push(`- ${r}`);
    L.push('');
    L.push('Revert or rethink before building anything on top of this.');
  } else if (verdict === 'FIX') {
    L.push('**Objective defects — fix these before spending a judge round:**');
    for (const f of allFindings) L.push(`- \`${f.shot}\` **${f.severity}** ${f.code} — ${f.message}`);
    for (const e of report.pageErrors ?? []) L.push(`- **page error** — ${e}`);
  } else {
    L.push('**Mechanically clean.** Blind deck ready.');
    if (judgeDir) {
      L.push('');
      L.push(`Hand a FRESH sub-agent ONLY these, and nothing else:`);
      L.push(`- \`${path.relative(ROOT, path.join(judgeDir, 'deck'))}\``);
      L.push(`- \`${path.relative(ROOT, path.join(judgeDir, 'JUDGE_BRIEF.md'))}\``);
      L.push('');
      L.push('Then: `node ' + path.relative(ROOT, path.join(HARNESS, 'judge.mjs')).split(path.sep).join('/') + ' reveal --dir ' + path.relative(ROOT, judgeDir) + ' --answers verdict.json`');
    } else {
      L.push('');
      L.push('No `--references` supplied, so no deck was built. The bar must be real');
      L.push('frames on disk from the thing you intend to beat.');
    }
  }
  L.push('');
  L.push(`Frames: \`${path.relative(ROOT, path.join(outDir, 'frames'))}\` — **look at them.** Every`);
  L.push('real defect found so far was invisible in the numbers.');

  const md = L.join('\n');
  await writeFile(path.join(outDir, 'ROUND.md'), md);
  console.log('\n' + md);

  process.exit(verdict === 'VOID' || verdict === 'REGRESSED' ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
