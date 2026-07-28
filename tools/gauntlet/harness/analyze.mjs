// Pixel-level defect detection.
//
// The premise: a judge agent looking at a frame is expensive and inconsistent.
// Most of the things that make an AI-built game read as "amateur" are cheap to
// measure exactly -- crushed blacks, blown highlights, a flat 20-stop-less
// histogram, gradient banding, a frame that is 94% empty sky. Measure those
// first, fix them mechanically, and spend judge rounds only on frames that are
// already mechanically clean.
//
// There is no PNG decoder in Node's stdlib and this repo takes no new
// dependencies, so we decode inside the browser we already have open and read
// the pixels back out of a canvas.

const ANALYZER_HTML = 'data:text/html,<!doctype html><meta charset=utf-8><title>gauntlet-analyzer</title>';

/**
 * Open a scratch page used purely as an image decoder. Reuse it across many
 * frames -- creating a page per frame dominates the runtime.
 */
export async function openAnalyzer(browser) {
  const page = await browser.newPage();
  await page.goto(ANALYZER_HTML);
  return page;
}

/**
 * Analyze one PNG buffer. Returns a flat record of objective measurements.
 *
 * Everything here is deterministic: same bytes in, same numbers out. That
 * matters because these numbers gate a loop, and a gate that drifts is not a
 * gate.
 */
// Whole-frame statistics hide localised failure. A frame can have a perfect
// global histogram while the sky is right and the ground is muddy, or while the
// shadows have drifted warm when they should be cool. Claude-of-Duty samples six
// NAMED regions (sky, zenith, midsky, street, leftwall, rightwall) with a
// blue-red balance term for colour temperature; this is the generalised version.
//
// Rects are normalised [x0, y0, x1, y1], origin top-left.
export const DEFAULT_REGIONS = [
  { name: 'zenith', rect: [0.25, 0.0, 0.75, 0.15] },
  { name: 'sky', rect: [0.1, 0.05, 0.9, 0.35] },
  { name: 'center', rect: [0.3, 0.3, 0.7, 0.7] },
  { name: 'ground', rect: [0.1, 0.7, 0.9, 1.0] },
  { name: 'leftEdge', rect: [0.0, 0.25, 0.18, 0.85] },
  { name: 'rightEdge', rect: [0.82, 0.25, 1.0, 0.85] },
];

export async function analyzeFrame(analyzerPage, pngBuffer, regions = DEFAULT_REGIONS) {
  const b64 = Buffer.from(pngBuffer).toString('base64');
  return analyzerPage.evaluate(async ([dataB64, regionSpec]) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + dataB64;
    await img.decode();

    const w = img.width;
    const h = img.height;
    const canvas = new OffscreenCanvas(w, h);
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const { data } = ctx.getImageData(0, 0, w, h);

    const n = w * h;
    const luma = new Float32Array(n);
    const hist = new Uint32Array(256);
    let chromaSum = 0;

    for (let i = 0, p = 0; i < n; i++, p += 4) {
      const r = data[p], g = data[p + 1], b = data[p + 2];
      // Rec.709 luma on the stored (sRGB-encoded) values. We are measuring the
      // delivered image, not scene-linear radiance, so gamma space is correct.
      const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      luma[i] = y;
      hist[Math.min(255, Math.max(0, Math.round(y)))]++;
      const mx = Math.max(r, g, b);
      const mn = Math.min(r, g, b);
      chromaSum += mx === 0 ? 0 : (mx - mn) / mx;
    }

    // Percentiles straight off the histogram.
    const pct = (target) => {
      const want = target * n;
      let acc = 0;
      for (let v = 0; v < 256; v++) {
        acc += hist[v];
        if (acc >= want) return v;
      }
      return 255;
    };

    let mean = 0;
    for (let i = 0; i < n; i++) mean += luma[i];
    mean /= n;
    let variance = 0;
    for (let i = 0; i < n; i++) {
      const d = luma[i] - mean;
      variance += d * d;
    }
    variance /= n;

    let blackPx = 0, whitePx = 0, occupied = 0;
    for (let v = 0; v < 256; v++) if (hist[v] > 0) occupied++;
    for (let v = 0; v <= 4; v++) blackPx += hist[v];
    for (let v = 251; v <= 255; v++) whitePx += hist[v];

    // --- Sobel edge energy: a proxy for how much real detail is on screen. ---
    // A frame of untextured flat-shaded boxes scores low here no matter how
    // nice the lighting is. This is the single number that best separates
    // "procedural placeholder" from "authored surface".
    let edgeSum = 0;
    const smooth = []; // luma values sampled from low-gradient regions
    for (let y = 1; y < h - 1; y += 1) {
      for (let x = 1; x < w - 1; x += 1) {
        const i = y * w + x;
        const tl = luma[i - w - 1], t = luma[i - w], tr = luma[i - w + 1];
        const l = luma[i - 1], r = luma[i + 1];
        const bl = luma[i + w - 1], b = luma[i + w], br = luma[i + w + 1];
        const gx = -tl - 2 * l - bl + tr + 2 * r + br;
        const gy = -tl - 2 * t - tr + bl + 2 * b + br;
        const mag = Math.sqrt(gx * gx + gy * gy);
        edgeSum += mag;
        // Sample smooth areas for the banding test. Gradient below ~2/255 per
        // 3px window means we are inside a soft ramp (sky, fog, falloff).
        if (mag < 6 && (x & 3) === 0 && (y & 3) === 0) smooth.push(luma[i]);
      }
    }
    const edgeEnergy = edgeSum / ((w - 2) * (h - 2));

    // --- Banding: comb-shaped histogram inside smooth regions. ---
    // A clean gradient occupies (nearly) every integer level between its ends.
    // A banded one occupies a few levels with empty gaps between them. Count
    // the interior empty bins.
    let combGaps = 0;
    let smoothSpan = 0;
    let smoothLevels = 0;
    if (smooth.length > 256) {
      const sh = new Uint32Array(256);
      for (const v of smooth) sh[Math.min(255, Math.max(0, Math.round(v)))]++;
      let lo = -1, hi = -1;
      for (let v = 0; v < 256; v++) if (sh[v] > 0) { if (lo < 0) lo = v; hi = v; }
      if (lo >= 0 && hi > lo) {
        smoothSpan = hi - lo;
        for (let v = lo; v <= hi; v++) {
          if (sh[v] > 0) smoothLevels++;
          else combGaps++;
        }
      }
    }

    // --- named regions -----------------------------------------------------
    const regionStats = {};
    for (const r of regionSpec ?? []) {
      const x0 = Math.max(0, Math.floor(r.rect[0] * w));
      const y0 = Math.max(0, Math.floor(r.rect[1] * h));
      const x1 = Math.min(w, Math.ceil(r.rect[2] * w));
      const y1 = Math.min(h, Math.ceil(r.rect[3] * h));
      let cnt = 0, sr = 0, sg = 0, sb = 0, sy = 0, se = 0;
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const i = y * w + x;
          const p = i * 4;
          sr += data[p]; sg += data[p + 1]; sb += data[p + 2];
          sy += luma[i];
          // reuse the already-computed gradient cheaply: local 4-neighbour diff
          if (x > 0 && y > 0 && x < w - 1 && y < h - 1) {
            se += Math.abs(luma[i - 1] - luma[i + 1]) + Math.abs(luma[i - w] - luma[i + w]);
          }
          cnt++;
        }
      }
      if (!cnt) continue;
      regionStats[r.name] = {
        luma: +(sy / cnt).toFixed(2),
        r: +(sr / cnt).toFixed(1),
        g: +(sg / cnt).toFixed(1),
        b: +(sb / cnt).toFixed(1),
        // Blue minus red: positive = cool, negative = warm. This is the term
        // that catches a grade drifting without the global mean moving.
        colorTemp: +((sb - sr) / cnt).toFixed(2),
        detail: +(se / cnt).toFixed(2),
      };
    }

    const p01 = pct(0.01);
    const p50 = pct(0.5);
    const p99 = pct(0.99);

    return {
      width: w,
      height: h,
      lumaMean: +mean.toFixed(3),
      lumaStd: +Math.sqrt(variance).toFixed(3),
      lumaP01: p01,
      lumaP50: p50,
      lumaP99: p99,
      dynamicRange: p99 - p01,
      blackPct: +((blackPx / n) * 100).toFixed(2),
      whitePct: +((whitePx / n) * 100).toFixed(2),
      occupiedLevels: occupied,
      chromaMean: +(chromaSum / n).toFixed(4),
      edgeEnergy: +edgeEnergy.toFixed(2),
      smoothSpan,
      smoothLevels,
      combGaps,
      regions: regionStats,
    };
  }, [b64, regions]);
}

/**
 * Diff two frames captured from an identical camera with no input between them.
 *
 * On a static camera this should be ~0. Anything above a fraction of a percent
 * is z-fighting, shadow-acne shimmer, an unstable TAA/jitter, or undersampled
 * specular -- all of which read as "cheap" in motion and are invisible in a
 * single screenshot. This is the defect class that survives every eyeball
 * review and every single-frame judge.
 */
export async function diffFrames(analyzerPage, pngA, pngB) {
  const a = Buffer.from(pngA).toString('base64');
  const b = Buffer.from(pngB).toString('base64');
  return analyzerPage.evaluate(
    async ([aB64, bB64]) => {
      const load = async (s) => {
        const im = new Image();
        im.src = 'data:image/png;base64,' + s;
        await im.decode();
        const c = new OffscreenCanvas(im.width, im.height);
        const cx = c.getContext('2d', { willReadFrequently: true });
        cx.drawImage(im, 0, 0);
        return cx.getImageData(0, 0, im.width, im.height);
      };
      const A = await load(aB64);
      const B = await load(bB64);
      if (A.width !== B.width || A.height !== B.height) {
        return { error: 'size mismatch', changedPct: null, maxDelta: null };
      }
      const n = A.width * A.height;
      let changed = 0;
      let maxDelta = 0;
      let sumDelta = 0;
      for (let i = 0, p = 0; i < n; i++, p += 4) {
        const d = Math.max(
          Math.abs(A.data[p] - B.data[p]),
          Math.abs(A.data[p + 1] - B.data[p + 1]),
          Math.abs(A.data[p + 2] - B.data[p + 2]),
        );
        sumDelta += d;
        if (d > maxDelta) maxDelta = d;
        if (d > 8) changed++;
      }
      return {
        changedPct: +((changed / n) * 100).toFixed(3),
        maxDelta,
        meanDelta: +(sumDelta / n).toFixed(3),
      };
    },
    [a, b],
  );
}

/**
 * Turn measurements into pass/fail findings.
 *
 * Thresholds are deliberately conservative -- they flag things that are almost
 * certainly wrong, not things that are merely a matter of taste. Taste is the
 * judge's job. This function's job is to never let the judge waste a round on
 * a frame that is objectively broken.
 */
export function findings(m, { staticDiff = null, calibration = null } = {}) {
  const out = [];
  const add = (severity, code, message) => out.push({ severity, code, message });

  // --- always absolute: these mean "nothing rendered", never a style choice ---
  if (m.lumaMean < 2 && m.lumaStd < 2) {
    add('fatal', 'blank-frame', `Frame is effectively empty (mean luma ${m.lumaMean}, std ${m.lumaStd}). Nothing rendered.`);
    return out; // everything downstream is meaningless on an empty frame
  }
  if (staticDiff && staticDiff.changedPct != null && staticDiff.changedPct > 1.5) {
    add('warn', 'unstable-pixels', `${staticDiff.changedPct}% of pixels changed between two frames with a static camera (max delta ${staticDiff.maxDelta}) — z-fighting, shadow acne, or unresolved temporal noise.`);
  }

  if (calibration?.bands) {
    // --- reference-relative: the bar defines what "good" looks like ---------
    const b = calibration.bands;
    const tol = calibration.tolerance ?? 0.7;
    const ref = calibration.reference ?? 'reference';
    const ratio = (a, x) => (x > 0 ? (a / x).toFixed(2) : '∞');

    if (b.edgeEnergy && m.edgeEnergy < b.edgeEnergy.p25 * tol) {
      const short = (b.edgeEnergy.median / Math.max(m.edgeEnergy, 0.01)).toFixed(1);
      add(
        'warn',
        'below-bar-surface-detail',
        `Surface detail ${m.edgeEnergy} vs ${ref} band ${b.edgeEnergy.min}–${b.edgeEnergy.max} (median ${b.edgeEnergy.median}) — **${short}x short of the bar**. This is texture, panel lines, wear and normal variation at multiple scales, not lighting.`,
      );
    }
    if (b.dynamicRange && m.dynamicRange < b.dynamicRange.p25 * tol) {
      add('warn', 'below-bar-dynamic-range', `Dynamic range ${m.dynamicRange} vs ${ref} band ${b.dynamicRange.min}–${b.dynamicRange.max} (median ${b.dynamicRange.median}).`);
    }
    if (b.blackPct && m.blackPct > Math.max(b.blackPct.max * 1.5, b.blackPct.max + 8)) {
      add('warn', 'crushed-vs-bar', `${m.blackPct}% crushed to black; ${ref} peaks at ${b.blackPct.max}%.`);
    }
    if (b.whitePct && m.whitePct > Math.max(b.whitePct.max * 1.5, b.whitePct.max + 3)) {
      add('warn', 'blown-vs-bar', `${m.whitePct}% clipped to white; ${ref} peaks at ${b.whitePct.max}%.`);
    }
    if (b.combGaps && m.smoothSpan > 24 && m.combGaps > Math.max(b.combGaps.max * 1.4, b.combGaps.max + 20)) {
      add('warn', 'banding-vs-bar', `Gradient banding: ${m.combGaps} skipped levels vs ${ref} max ${b.combGaps.max}. Dither before the tonemap.`);
    }
    if (b.chromaMean && m.chromaMean < b.chromaMean.min * 0.5) {
      add('info', 'desaturated-vs-bar', `Chroma ${m.chromaMean} vs ${ref} min ${b.chromaMean.min} — much less colour than the bar. Intentional?`);
    }
    return out;
  }

  // --- no calibration: absolute fallbacks --------------------------------
  // These are deliberately loose. They catch "obviously broken", not "not as
  // good as the bar" -- that judgement REQUIRES a bar. Supply --references and
  // run calibrate.mjs to get thresholds that mean something.
  if (m.blackPct > 92) {
    add('fatal', 'mostly-black', `${m.blackPct}% of pixels are crushed to black. The shot is empty or the exposure collapsed.`);
  }
  if (m.whitePct > 25) {
    add('warn', 'blown-highlights', `${m.whitePct}% of pixels are clipped to white — highlights have no roll-off.`);
  }
  if (m.dynamicRange < 25) {
    add('warn', 'flat-histogram', `p01..p99 luma spans only ${m.dynamicRange}/255 — the image is very flat.`);
  }
  if (m.occupiedLevels < 24) {
    add('warn', 'posterized', `Only ${m.occupiedLevels} distinct luma levels present — the frame is posterized.`);
  }
  if (m.edgeEnergy < 4) {
    add('warn', 'no-surface-detail', `Sobel edge energy ${m.edgeEnergy} is very low — surfaces are flat-shaded. NOTE: without a calibrated bar this threshold is a guess; a real reference measured 28-30.`);
  }
  return out;
}

export default { openAnalyzer, analyzeFrame, diffFrames, findings };
