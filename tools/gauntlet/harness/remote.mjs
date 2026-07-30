// Remote GPU execution.
//
// This box has no GPU. smeagol has a Tesla P40 and a V100. So: run the loop
// here, run the *browser* there, and tunnel both directions over one SSH
// connection. The dev server stays local; the pixels are rasterized on a Tesla.
//
//   local  :8099  --(ssh -R)-->  smeagol :8099   (game reaches the remote browser)
//   local  :9222  <--(ssh -L)--  smeagol :9222   (CDP reaches the local harness)
//
// MEASURED RECIPE (do not simplify -- each part was necessary):
//
//   VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
//     Without this ANGLE picks the llvmpipe ICD and you get a software device
//     that still calls itself Vulkan.
//   --use-gl=angle --use-angle=vulkan --enable-features=Vulkan
//     Routes WebGL through ANGLE's Vulkan backend onto the NVIDIA device.
//   xvfb-run (i.e. HEADED, not --headless)
//     Headless yields real WebGL but SOFTWARE WebGPU. Only headed gives a
//     hardware WebGPU adapter. Headless would have reported a working adapter
//     and quietly measured SwiftShader.
//   the page must be served over http://127.0.0.1 (a secure context)
//     navigator.gpu is simply absent on data: and file: origins.

import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { loadPlaywright } from './browser.mjs';

const BASE_ARGS = [
  '--ignore-gpu-blocklist',
  '--enable-gpu-rasterization',
  '--enable-unsafe-webgpu',
  '--enable-features=Vulkan',
  '--use-gl=angle',
  '--use-angle=vulkan',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-features=DialMediaRouteProvider',
];

// Two GPU profiles, and they are mutually exclusive. Measured, both ways:
//
//   webgpu : Tesla P40 (Pascal, cc 6.1) under xvfb with a real X surface.
//            The ONLY configuration that yields a HARDWARE WebGPU adapter
//            (webgpu=nvidia/pascal). Use this whenever WebGPU matters.
//
//   raster : Tesla V100 (Volta, cc 7.0, 32GB HBM2) via --ozone-platform=headless.
//            Chrome rejects the V100 under X because that display-less SXM2
//            board fails the Xlib presentation-support check; Ozone headless
//            removes the surface requirement and WebGL then runs on the V100.
//            But Dawn falls back to SwiftShader in this mode, so WebGPU is
//            SOFTWARE here. WebGL only.
//
// So: you cannot currently have hardware WebGPU *and* the V100. Pick per run.
export const GPU_PROFILES = {
  webgpu: {
    label: 'Tesla P40 (Pascal) — hardware WebGL and WebGPU AVAILABLE (what the app uses is reported separately)',
    args: [],
    env: {},
    headed: true,
  },
  raster: {
    label: 'Tesla V100 (Volta, 32GB) — hardware WebGL; WebGPU available only as SOFTWARE',
    args: ['--ozone-platform=headless'],
    env: { MESA_VK_DEVICE_SELECT: '10de:1df0' },
    headed: false,
  },
};

/**
 * Start Chrome on `host` under xvfb with the GPU recipe, tunnel CDP back here,
 * and forward the local dev server out so the remote page can load it.
 *
 * Returns { browser, close }.
 */
export async function connectRemote({
  host = 'smeagol',
  cdpPort = 9222,
  servePort = 8099,
  chromePath = '/usr/bin/google-chrome',
  vkIcd = '/usr/share/vulkan/icd.d/nvidia_icd.json',
  readyTimeoutMs = 60000,
  gpuProfile = 'webgpu',
} = {}) {
  const prof = GPU_PROFILES[gpuProfile];
  if (!prof) {
    throw new Error(`unknown gpu profile "${gpuProfile}" — expected one of: ${Object.keys(GPU_PROFILES).join(', ')}`);
  }
  const profile = `/tmp/gauntlet-chrome-${cdpPort}`;
  const chromeArgs = [...BASE_ARGS, ...prof.args];
  const envPrefix = Object.entries(prof.env)
    .map(([k, v]) => `export ${k}=${v}`)
    .join('\n');
  // The V100 path needs no X server at all; the P40/WebGPU path requires one.
  const runner = prof.headed ? 'xvfb-run -a ' : '';

  // Launch the remote browser. setsid detaches it from this ssh session so it
  // survives the command returning; we kill it explicitly on close.
  const pidFile = `/tmp/gauntlet-chrome-${cdpPort}.pid`;

  // NOTE: never `pkill -f` a pattern that also appears in this command string.
  // ssh runs it via `bash -c "<string>"`, so the pattern matches the shell
  // running it and the session kills itself. Free the port by its listener
  // instead, and shut down later via the recorded process group.
  const remoteCmd = [
    `fuser -k ${cdpPort}/tcp >/dev/null 2>&1 || true`,
    // Also free the REVERSE-forward port. A previous run's tunnel can leave it
    // bound on the remote; with ExitOnForwardFailure that kills the whole new
    // tunnel, and the only symptom is ECONNREFUSED on the CDP port.
    `fuser -k ${servePort}/tcp >/dev/null 2>&1 || true`,
    `rm -rf ${profile}`,
    `export VK_ICD_FILENAMES=${vkIcd}`,
    envPrefix,
    `setsid nohup ${runner}${chromePath} ${chromeArgs.join(' ')} ` +
      `--remote-debugging-port=${cdpPort} --user-data-dir=${profile} about:blank ` +
      `> /tmp/gauntlet-chrome-${cdpPort}.log 2>&1 < /dev/null &`,
    `echo $! > ${pidFile}`,
    'sleep 5',
    `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:${cdpPort}/json/version`,
    // Newlines, not '; ' -- the backgrounded launch line ends in '&' and '&;'
    // is a bash syntax error.
  ].join('\n');

  const boot = spawn('ssh', ['-o', 'BatchMode=yes', host, remoteCmd], { stdio: ['ignore', 'pipe', 'pipe'] });
  let bootOut = '';
  boot.stdout.on('data', (d) => (bootOut += d));
  boot.stderr.on('data', (d) => (bootOut += d));
  await new Promise((res) => boot.on('close', res));
  if (!/200/.test(bootOut)) {
    throw new Error(`remote Chrome did not come up on ${host}:${cdpPort}\n${bootOut.slice(0, 800)}`);
  }

  // One tunnel, both directions.
  const tunnel = spawn(
    'ssh',
    [
      '-o', 'BatchMode=yes',
      '-o', 'ExitOnForwardFailure=yes',
      '-N',
      '-L', `${cdpPort}:127.0.0.1:${cdpPort}`,
      '-R', `${servePort}:127.0.0.1:${servePort}`,
      host,
    ],
    { stdio: ['ignore', 'pipe', 'pipe'] },
  );

  // Capture the tunnel's own diagnostics. Without this a dead tunnel surfaces
  // only as ECONNREFUSED on the CDP port, which points at the browser -- the
  // one place the problem is not. Tailscale re-auth prompts land here.
  let tunnelErr = '';
  tunnel.stderr?.on('data', (d) => (tunnelErr += d));
  tunnel.stdout?.on('data', (d) => (tunnelErr += d));
  let tunnelExited = null;
  tunnel.on('exit', (code) => (tunnelExited = code));

  const { chromium } = loadPlaywright();
  const deadline = Date.now() + readyTimeoutMs;
  let browser = null;
  let lastErr = null;
  while (Date.now() < deadline) {
    await sleep(1000);
    try {
      browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (!browser) {
    tunnel.kill();
    const why = tunnelExited !== null ? `ssh tunnel exited with code ${tunnelExited}` : 'ssh tunnel is up but CDP never answered';
    throw new Error(
      `could not reach tunnelled CDP — ${why}\n` +
        (tunnelErr.trim() ? `ssh said:\n  ${tunnelErr.trim().split('\n').join('\n  ')}\n` : '') +
        `playwright said: ${lastErr?.message?.split('\n')[0] ?? 'unknown'}`,
    );
  }

  const close = async () => {
    try { await browser.close(); } catch { /* already gone */ }
    tunnel.kill();
    // setsid made the launcher a session leader, so its PID is the process
    // group id -- killing the group takes Chrome and Xvfb with it.
    spawn(
      'ssh',
      ['-o', 'BatchMode=yes', host, `kill -- -$(cat ${pidFile}) 2>/dev/null || fuser -k ${cdpPort}/tcp 2>/dev/null || true`],
      { stdio: 'ignore' },
    ).unref();
  };

  return { browser, close, host, cdpPort, servePort, gpuProfile, gpuProfileLabel: prof.label };
}

export default { connectRemote };
