/**
 * Find which bind group is invalid, and why — deterministically.
 *
 * "Binding type in the shader (texture) doesn't match the type in the layout
 * (sampler)" names neither the bind group, the binding index, nor the resource.
 * Correlating it with recent activity by timestamp is guesswork, and guesswork
 * has already produced one wrong diagnosis in this investigation.
 *
 * So this does not guess. Every createBindGroup / createBindGroupLayout /
 * createSampler / createTexture call is wrapped in its own
 * pushErrorScope('validation') ... popErrorScope() pair, which attributes the
 * error to that exact call and no other. The descriptor is captured at creation
 * time — WebGPU objects will not tell you afterwards what they were made from —
 * so a failure can be reported with the layout it violated and the resource that
 * violated it.
 *
 * Ordering matters as much as counting. WebGPU reports cascades: one invalid
 * bind group invalidates its command buffer, which invalidates everything after
 * it. The FIRST failure in command order is the one to fix; the largest repeated
 * count is usually its shadow.
 *
 * Usage:
 *   node binding-trace.mjs --url URL [--seconds N] [--json] [--max N]
 */

import { chromium } from "playwright";

const argv = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const URL = arg("url", "http://127.0.0.1:8099/index.html");
const SECONDS = Number(arg("seconds", "40"));
const MAX = Number(arg("max", "12"));
const AS_JSON = argv.includes("--json");

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
  headless: false,
  args: [
    "--no-sandbox",
    "--enable-unsafe-webgpu",
    "--enable-features=Vulkan",
    "--ignore-gpu-blocklist",
    "--disable-vulkan-fallback-to-gl-for-testing",
  ],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });

await page.addInitScript(() => {
  globalThis.__bind = { failures: [], seq: 0, counts: {} };

  const samplers = new WeakMap(); // GPUSampler -> descriptor
  const textures = new WeakMap(); // GPUTexture -> descriptor
  const views = new WeakMap(); // GPUTextureView -> {parent, view}
  const layouts = new WeakMap(); // GPUBindGroupLayout -> entries

  const describeResource = (r) => {
    if (!r) return { kind: "null" };
    if (samplers.has(r)) return { kind: "sampler", ...samplers.get(r) };
    if (views.has(r)) {
      const v = views.get(r);
      return {
        kind: "textureView",
        viewFormat: v.view?.format ?? null,
        // The distinction the R16Float/R32Float failure turns on: what the
        // texture physically is, versus what the view claims it is.
        textureFormat: v.parent?.format ?? null,
        dimension: v.view?.dimension ?? null,
        sampleCount: v.parent?.sampleCount ?? 1,
        usage: v.parent?.usage ?? null,
      };
    }
    if (r.buffer) return { kind: "buffer", size: r.size ?? null, offset: r.offset ?? null };
    return { kind: "unknown" };
  };

  // Summarise what a layout entry expects, since that is the other half of every
  // "shader says X, layout says Y" message.
  const describeLayoutEntry = (e) => {
    if (!e) return null;
    const out = { binding: e.binding, visibility: e.visibility };
    if (e.sampler) out.sampler = { type: e.sampler.type ?? "filtering" };
    if (e.texture)
      out.texture = {
        sampleType: e.texture.sampleType ?? "float",
        viewDimension: e.texture.viewDimension ?? "2d",
        multisampled: Boolean(e.texture.multisampled),
      };
    if (e.storageTexture)
      out.storageTexture = {
        access: e.storageTexture.access ?? "write-only",
        format: e.storageTexture.format ?? null,
        viewDimension: e.storageTexture.viewDimension ?? "2d",
      };
    if (e.buffer) out.buffer = { type: e.buffer.type ?? "uniform" };
    return out;
  };

  const once = (obj, name, wrap) => {
    const orig = obj[name];
    if (!orig || orig.__studioHooked) return;
    const fn = wrap(orig);
    fn.__studioHooked = true;
    obj[name] = fn;
  };

  if (!globalThis.GPUDevice) return;
  const D = GPUDevice.prototype;

  once(D, "createSampler", (orig) =>
    function (d) {
      const s = orig.call(this, d);
      try {
        samplers.set(s, {
          label: d?.label ?? null,
          compare: d?.compare ?? null,
          minFilter: d?.minFilter ?? "nearest",
          magFilter: d?.magFilter ?? "nearest",
        });
      } catch (e) {}
      return s;
    });

  once(D, "createTexture", (orig) =>
    function (d) {
      const t = orig.call(this, d);
      try {
        textures.set(t, {
          label: d?.label ?? null,
          format: d?.format ?? null,
          sampleCount: d?.sampleCount ?? 1,
          usage: d?.usage ?? null,
        });
      } catch (e) {}
      return t;
    });

  once(GPUTexture.prototype, "createView", (orig) =>
    function (d) {
      const v = orig.call(this, d);
      try {
        views.set(v, { parent: textures.get(this) ?? null, view: d ?? {} });
      } catch (e) {}
      return v;
    });

  once(D, "createBindGroupLayout", (orig) =>
    function (d) {
      const l = orig.call(this, d);
      try {
        layouts.set(l, {
          label: d?.label ?? null,
          entries: (d?.entries ?? []).map(describeLayoutEntry),
        });
      } catch (e) {}
      return l;
    });

  // The heart of it: attribute a validation error to the exact createBindGroup
  // that produced it, rather than to whatever happened to be nearby in time.
  once(D, "createBindGroup", (orig) =>
    function (d) {
      const seq = ++globalThis.__bind.seq;
      let scoped = false;
      try {
        this.pushErrorScope("validation");
        scoped = true;
      } catch (e) {}
      const bg = orig.call(this, d);
      if (!scoped) return bg;

      const layout = layouts.get(d?.layout) ?? null;
      const entries = (d?.entries ?? []).map((e) => ({
        binding: e.binding,
        resource: describeResource(e.resource),
      }));

      this.popErrorScope()
        .then((err) => {
          if (!err) return;
          const message = err.message ?? String(err);
          const key = message.slice(0, 120);
          globalThis.__bind.counts[key] = (globalThis.__bind.counts[key] ?? 0) + 1;
          // Keep only the first few instances of each distinct message: the rest
          // are the same defect repeating every frame.
          if (globalThis.__bind.counts[key] > 3) return;
          globalThis.__bind.failures.push({
            seq,
            message,
            layoutLabel: layout?.label ?? null,
            bindGroupLabel: d?.label ?? null,
            // Pair each supplied resource with what its layout entry expected,
            // which is the comparison the error message omits.
            bindings: entries.map((e) => ({
              binding: e.binding,
              supplied: e.resource,
              expected: layout?.entries?.find((x) => x && x.binding === e.binding) ?? null,
            })),
          });
        })
        .catch(() => {});
      return bg;
    });
});

await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60_000 });
await page.waitForTimeout(SECONDS * 1000);

const result = await page.evaluate(() => ({
  failures: globalThis.__bind?.failures ?? [],
  counts: globalThis.__bind?.counts ?? {},
  total: globalThis.__bind?.seq ?? 0,
}));
await browser.close();

// Command order, so the first genuine failure leads rather than the loudest one.
const failures = result.failures.sort((a, b) => a.seq - b.seq).slice(0, MAX);

if (AS_JSON) {
  console.log(JSON.stringify({ ...result, failures }, null, 2));
} else {
  console.log(`createBindGroup calls: ${result.total}`);
  console.log(`distinct failure messages: ${Object.keys(result.counts).length}`);
  for (const [msg, n] of Object.entries(result.counts)) console.log(`  x${n}  ${msg}`);
  console.log();
  for (const f of failures) {
    console.log(`--- failure at createBindGroup #${f.seq}`);
    console.log(`    layout : ${f.layoutLabel ?? "(unlabelled)"}`);
    console.log(`    error  : ${f.message.slice(0, 200)}`);
    for (const b of f.bindings) {
      const sup = JSON.stringify(b.supplied);
      const exp = JSON.stringify(b.expected);
      console.log(`    binding ${b.binding}`);
      console.log(`      supplied ${sup}`);
      console.log(`      expected ${exp}`);
    }
  }
}

// 0 no bind group failed, 1 at least one did, 3 nothing was captured.
process.exit(!result.total ? 3 : failures.length ? 1 : 0);
