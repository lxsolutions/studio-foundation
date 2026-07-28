// Browser acquisition for the gauntlet harness.
//
// Two jobs:
//   1. Find a playwright-core install without adding a dependency to this repo.
//   2. Launch Chromium in a configuration that actually uses the GPU, and then
//      REPORT WHAT IT ACTUALLY GOT. A perf number measured on SwiftShader is
//      worse than no number at all, because it looks like a real number.

import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// Walk up from both the harness and the caller's working directory. Hardcoded
// relative candidates broke the moment this was vendored into a larger repo, so
// resolution is now positional rather than assumed.
function ancestorNodeModules(start) {
  const out = [];
  let dir = path.resolve(start);
  for (;;) {
    out.push(path.join(dir, 'node_modules'));
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return out;
}

const NODE_MODULES_CANDIDATES = [
  ...ancestorNodeModules(HERE),
  ...ancestorNodeModules(process.cwd()),
  // Long-standing install on this workstation, kept as a last resort so the
  // harness still runs in repos that have not installed anything themselves.
  path.resolve(HERE, '..', '..', '..', '..', 'studio-foundation', 'tests', 'browser', 'node_modules'),
];

export function loadPlaywright() {
  const tried = [];
  for (const dir of NODE_MODULES_CANDIDATES) {
    const pkg = path.join(dir, 'playwright-core');
    tried.push(pkg);
    if (!existsSync(pkg)) continue;
    const require = createRequire(path.join(dir, '_gauntlet_resolver.cjs'));
    return require('playwright-core');
  }
  throw new Error(
    'playwright-core not found. Looked in:\n  ' +
      tried.join('\n  ') +
      '\nInstall it with: npm i playwright-core',
  );
}

// Flags that push Chromium onto real hardware. --headless=new still uses the
// GPU process; the old --headless did not, which is the usual reason people
// silently benchmark a software rasterizer.
const GPU_FLAGS = [
  '--enable-unsafe-webgpu',
  '--enable-features=Vulkan',
  '--ignore-gpu-blocklist',
  '--enable-gpu-rasterization',
  '--use-angle=default',
];
// Deliberately NOT set: --disable-frame-rate-limit / --disable-gpu-vsync. They
// make a busy canvas starve the compositor, and CDP screenshots then time out
// on exactly the heavy scenes we most need to measure. Frame pacing is read
// from the page's own rAF callbacks instead, which is the number that matters.

// playwright-core ships no browsers, so we drive the system install. Chrome and
// Edge both expose real GPU adapters; the bundled-chromium fallback usually
// does not, which is why it is last and why probeGpu() exists.
const CHANNELS = ['chrome', 'msedge', null];

export async function launch({ headed = process.env.GAUNTLET_HEADED === '1' } = {}) {
  const { chromium } = loadPlaywright();
  const errors = [];
  for (const channel of CHANNELS) {
    try {
      return await chromium.launch({
        headless: !headed,
        args: GPU_FLAGS,
        ...(channel ? { channel } : {}),
      });
    } catch (e) {
      errors.push(`${channel ?? 'bundled chromium'}: ${e.message.split('\n')[0]}`);
    }
  }
  throw new Error('could not launch a browser.\n  ' + errors.join('\n  '));
}

/**
 * Ask the page what hardware it is on, AND which backend the application
 * actually renders through. These are different questions and conflating them
 * produces a claim the evidence does not support.
 *
 * `availableWebGPU` comes from a throwaway canvas this probe creates. It proves
 * the BROWSER can reach a hardware WebGPU adapter. It says nothing about the
 * page: a build using THREE.WebGLRenderer, or a Godot web-webgl export, will
 * report a healthy WebGPU adapter while rendering every pixel through WebGL.
 *
 * `applicationRenderer` inspects the page's own canvases. getContext() returns
 * an existing context only when the requested type matches the one already
 * created, so probing each type is a real detection rather than an inference.
 *
 * `software: true` means every fps number from this run is fiction. Callers
 * should surface that loudly rather than quietly publishing the numbers.
 */
export async function probeGpu(page) {
  const info = await page.evaluate(async () => {
    const out = {
      // Browser CAPABILITY -- what the environment could do, not what ran.
      availableWebGL: null,
      availableWebGLVendor: null,
      availableWebGPU: null,
      availableWebGPUArchitecture: null,
      hasWebGPU: typeof navigator !== 'undefined' && !!navigator.gpu,
      // What the APPLICATION actually rendered through.
      applicationRenderer: null,
      canvases: 0,
    };

    // Read what the page ASKED for, recorded by the init-script hook. Probing
    // with getContext() here would create a context on a bare canvas and report
    // it as the application's choice -- which is exactly the false positive
    // that made a web-webgl export claim it rendered through WebGPU.
    try {
      const rec = globalThis.__gauntletProbe?.contexts ?? [];
      const list = Array.from(document.querySelectorAll('canvas'));
      out.canvases = list.length;
      const real = rec.filter((t) => t !== '2d' || rec.length === 1);
      out.applicationRenderer = real.length
        ? real.join('+')
        : (list.length ? 'no-context-requested' : 'no-canvas');
    } catch (e) {
      out.applicationRenderer = `error: ${e.message}`;
    }

    try {
      const c = document.createElement('canvas');
      const gl = c.getContext('webgl2') || c.getContext('webgl');
      if (gl) {
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        out.availableWebGL = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
        out.availableWebGLVendor = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
      }
    } catch (e) {
      out.availableWebGL = `error: ${e.message}`;
    }

    try {
      if (navigator.gpu) {
        const adapter = await navigator.gpu.requestAdapter();
        if (adapter) {
          // adapter.info is the modern surface; requestAdapterInfo() was removed.
          const ai = adapter.info || (adapter.requestAdapterInfo ? await adapter.requestAdapterInfo() : null);
          if (ai) {
            out.availableWebGPU = [ai.vendor, ai.device, ai.description].filter(Boolean).join(' ') || '(adapter, no info)';
            out.availableWebGPUArchitecture = ai.architecture || null;
          } else {
            out.availableWebGPU = '(adapter, no info)';
          }
        }
      }
    } catch (e) {
      out.availableWebGPU = `error: ${e.message}`;
    }

    return out;
  });

  const haystack = `${info.availableWebGL || ''} ${info.availableWebGPU || ''}`.toLowerCase();
  info.software = /swiftshader|llvmpipe|software|microsoft basic|warp/.test(haystack);
  return info;
}

export default { loadPlaywright, launch, probeGpu };
