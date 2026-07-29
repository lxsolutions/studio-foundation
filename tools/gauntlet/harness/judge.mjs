#!/usr/bin/env node
// The blind A/B judge protocol.
//
// The whole method rests on one idea: the thing that built the work must not
// be the thing that grades it, and the grader must not know which frame is
// ours. Everything else is decoration.
//
// Matt Shumer's own published numbers are the argument for taking this
// seriously. Across four rounds of Claude of Duty, eleven critics scored the
// build 3.59 -> 4.14 -> 4.05 -> 5.05 out of 10 against Call of Duty, and in
// blind A/B "every critic in every round picked the real Call of Duty frame."
// Note round three went DOWN. Without a blind grader you cannot see that; you
// only see an agent reporting progress.
//
//   node harness/judge.mjs pair --candidates runs/r007/frames --references references/starfield --out runs/r007/judge
//   node harness/judge.mjs reveal --dir runs/r007/judge --answers verdict.json
//
// `pair` writes a shuffled, anonymised deck plus a sealed answer key.
// `reveal` scores a judge's verdicts against the key.

import { mkdir, readdir, copyFile, writeFile, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';

const IMAGE_RE = /\.(png|jpe?g|webp)$/i;

async function images(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  return entries
    .filter((e) => e.isFile() && IMAGE_RE.test(e.name))
    .map((e) => path.join(dir, e.name))
    .sort();
}

/**
 * Deterministic shuffle. A fixed seed means the same deck can be rebuilt and
 * audited later -- which matters, because "the judge was biased" is otherwise
 * unfalsifiable.
 */
function shuffle(arr, seed) {
  let s = seed >>> 0 || 1;
  const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

async function cmdPair(opts) {
  const cand = await images(opts.candidates);
  const refs = await images(opts.references);
  if (!cand.length) throw new Error(`no candidate images in ${opts.candidates}`);
  if (!refs.length) {
    throw new Error(
      `no reference images in ${opts.references}\n` +
        'The bar must be something the judge can LOOK AT. Put real frames from the\n' +
        'game you are trying to beat in that directory -- screenshots you captured\n' +
        'yourself from a game you own, or official press-kit images. Adjectives are\n' +
        'not a bar; "AAA quality" is not a bar. A frame is a bar.',
    );
  }

  const outDir = path.resolve(opts.out);
  const deckDir = path.join(outDir, 'deck');
  await mkdir(deckDir, { recursive: true });

  const pairs = [];
  const n = Math.min(cand.length, Math.max(refs.length, cand.length));
  for (let i = 0; i < n; i++) {
    const c = cand[i % cand.length];
    const r = refs[i % refs.length];
    // Coin flip per pair decides which slot our frame occupies. The judge sees
    // only "A" and "B".
    const seed = parseInt(createHash('sha1').update(`${opts.seed}:${i}`).digest('hex').slice(0, 8), 16);
    const ourSlot = seed % 2 === 0 ? 'A' : 'B';
    const id = String(i + 1).padStart(3, '0');
    const aSrc = ourSlot === 'A' ? c : r;
    const bSrc = ourSlot === 'A' ? r : c;
    await copyFile(aSrc, path.join(deckDir, `pair${id}_A${path.extname(aSrc)}`));
    await copyFile(bSrc, path.join(deckDir, `pair${id}_B${path.extname(bSrc)}`));
    pairs.push({ id, ourSlot, candidate: path.basename(c), reference: path.basename(r) });
  }

  const shuffled = shuffle(pairs, 12345);

  // The key never goes to the judge.
  await writeFile(path.join(outDir, 'ANSWER_KEY.json'), JSON.stringify({ pairs: shuffled }, null, 2));

  const brief = JUDGE_BRIEF.replace('{{PAIRS}}', pairs.map((p) => `pair${p.id}`).join(', '));
  await writeFile(path.join(outDir, 'JUDGE_BRIEF.md'), brief);
  // Hash the brief so a later run can prove it was not softened between rounds.
  const hash = createHash('sha256').update(brief).digest('hex').slice(0, 16);
  await writeFile(path.join(outDir, 'BRIEF_SHA.txt'), hash + '\n');

  console.log(`[judge] ${pairs.length} pairs written to ${deckDir}`);
  console.log(`[judge] brief: ${path.join(outDir, 'JUDGE_BRIEF.md')}  (sha ${hash})`);
  console.log('[judge] Give the judge ONLY the deck and the brief. Never the answer key.');
}

async function cmdReveal(opts) {
  const key = JSON.parse(await readFile(path.join(opts.dir, 'ANSWER_KEY.json'), 'utf8'));
  const verdicts = JSON.parse(await readFile(opts.answers, 'utf8'));
  const byId = new Map(key.pairs.map((p) => [p.id, p]));

  let wins = 0, losses = 0, unscored = 0;
  const rows = [];
  const seen = new Set();
  for (const v of verdicts.verdicts ?? verdicts) {
    const id = String(v.pair).replace(/^pair/, '').padStart(3, '0');
    const k = byId.get(id);
    if (!k) { unscored++; continue; }

    // Accept the spellings judges actually write. A verdict that carries a
    // choice under a different key is a formatting difference, not a loss.
    const picked = v.better ?? v.winner ?? v.choice ?? v.pick ?? v.preferred;
    if (picked !== 'A' && picked !== 'B') {
      throw new Error(
        `pair${id}: no A/B choice found. Looked for better/winner/choice/pick/preferred, ` +
          `got ${JSON.stringify(v)}. Refusing to score — a missing choice is not a loss.`,
      );
    }
    seen.add(id);
    const won = picked === k.ourSlot;
    if (won) wins++; else losses++;
    rows.push({ pair: id, ourSlot: k.ourSlot, judgePicked: picked, won, why: v.why ?? v.reason ?? '' });
  }

  // A pair the judge never ruled on must NOT read as a loss.
  //
  // This scored a real round at a confident 0% BELOW_REFERENCE because the
  // verdicts carried the choice under `winner` instead of `better`: every pair
  // silently fell through to the default and the tool reported the opposite of
  // the truth (the same round was 50% once parsed correctly). A measurement
  // instrument that invents a defensible-looking number when it cannot read its
  // input is worse than one that fails.
  const missing = key.pairs.map((p) => p.id).filter((id) => !seen.has(id));
  if (missing.length) {
    throw new Error(
      `no verdict for pair(s) ${missing.map((m) => `pair${m}`).join(', ')}. ` +
        `Refusing to score a partial deck — an unjudged pair is not a loss.`,
    );
  }

  const total = wins + losses;
  const rate = total ? (wins / total) * 100 : 0;
  const out = {
    pairsScored: total,
    wins,
    losses,
    winRatePct: +rate.toFixed(1),
    // The honest bar. Below 50% the reference is simply better.
    verdict: rate >= 50 ? 'AT_OR_ABOVE_REFERENCE' : 'BELOW_REFERENCE',
    unscored,
    rows,
  };
  await writeFile(path.join(opts.dir, 'SCORE.json'), JSON.stringify(out, null, 2));

  console.log(`[judge] ${wins}W / ${losses}L — ${out.winRatePct}% — ${out.verdict}`);
  for (const r of rows.filter((r) => !r.won)) {
    console.log(`  LOST pair${r.pair}: ${r.why}`);
  }
  process.exit(out.verdict === 'AT_OR_ABOVE_REFERENCE' ? 0 : 1);
}

const JUDGE_BRIEF = `# Blind comparison brief

You are grading rendered frames. You do NOT know which frames come from which
source, and you must not try to guess based on anything except what you see.

For each pair ({{PAIRS}}) you will find two images: \`pairNNN_A\` and \`pairNNN_B\`.

For each pair, answer:

1. **better** — "A" or "B". Which frame would a player believe came from a
   shipped, commercially released game? You must pick one. Ties are not allowed.
2. **why** — the single largest visual difference that drove your choice. Be
   specific and physical: "A's shadows have no contact darkening where objects
   meet the ground", not "A looks less polished".
3. **gap** — if you had to close the distance between the weaker and stronger
   frame with one change, what is it?

Judge only what is in the frames. Consider, in roughly this order of impact:

- **Light transport** — bounce/indirect light, contact shadows, ambient
  occlusion, how light falls off. This is what separates real from flat more
  than any other factor.
- **Material response** — does metal read as metal, cloth as cloth? Roughness
  variation, specular breakup, fresnel at grazing angles.
- **Surface detail** — texture, normal and roughness variation at multiple
  scales. Untextured flat-shaded geometry is the single loudest tell.
- **Tonemapping and grade** — highlight roll-off, black point, colour harmony.
- **Composition and silhouette** — readable shapes, intentional framing.
- **Post** — bloom that respects intensity, no obvious aliasing, no banding.

Hard rules:

- Do not describe the images as "AI-generated" or speculate about provenance.
- Do not soften a verdict to be encouraging. An inflated score wastes the next
  round of work.
- If both frames are weak, still pick the less weak one, and say both are weak.

Return JSON:

\`\`\`json
{ "verdicts": [ { "pair": "001", "better": "A", "why": "...", "gap": "..." } ] }
\`\`\`
`;

// ---------------------------------------------------------------------------

function parse(argv) {
  const cmd = argv[0];
  const o = { seed: 'gauntlet' };
  for (let i = 1; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--candidates') o.candidates = argv[++i];
    else if (k === '--references') o.references = argv[++i];
    else if (k === '--out') o.out = argv[++i];
    else if (k === '--dir') o.dir = argv[++i];
    else if (k === '--answers') o.answers = argv[++i];
    else if (k === '--seed') o.seed = argv[++i];
  }
  return { cmd, o };
}

const { cmd, o } = parse(process.argv.slice(2));
try {
  if (cmd === 'pair') await cmdPair(o);
  else if (cmd === 'reveal') await cmdReveal(o);
  else {
    console.error('usage: judge.mjs pair --candidates DIR --references DIR --out DIR');
    console.error('       judge.mjs reveal --dir DIR --answers verdict.json');
    process.exit(2);
  }
} catch (e) {
  console.error(String(e.message ?? e));
  process.exit(2);
}
