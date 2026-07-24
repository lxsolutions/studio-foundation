/*
 * Studio Foundation — WebGPU boot overlay.
 *
 * Godot's web shell hides its loading UI as soon as startGame() resolves, but on
 * WebGPU that happens *before* the engine translates SPIR-V to WGSL and Dawn builds
 * the render pipelines. For a scene the size of Chariot that is ~20 seconds during
 * which the canvas is simply black — which reads as "the demo is broken" rather than
 * "it is still loading".
 *
 * Detecting when it is genuinely rendering is the tricky part. Watching
 * requestAnimationFrame for smooth frames does NOT work: while the engine is merely
 * downloading, the page is idle and rAF already runs at a clean 60fps, so the overlay
 * dismisses itself immediately (measured: gone by t=5s on a load whose first frame
 * arrives at ~20s).
 *
 * Pipeline construction is not a reliable signal either: Godot builds a few canvas
 * pipelines early, then goes quiet for many seconds while Tint translates the scene
 * shaders (translation creates no pipelines), so "pipelines went quiet" fires ~12s
 * before anything is drawn — measured on the live demo.
 *
 * The decisive signal is the render loop itself. A running engine submits a command
 * buffer every frame, so sustained GPUQueue.submit traffic means frames are genuinely
 * being produced. We wrap that, and wrap pipeline creation too so the overlay can show
 * real progress ("N pipelines built") while the viewer waits.
 *
 * Drop-in: include AFTER the shell's own script. Standalone, so a future re-export only
 * needs the single <script> tag re-added.
 */
(function () {
	'use strict';

	var SMOOTH_FRAMES_REQUIRED = 20;   // consecutive good frames before we believe it
	var SMOOTH_FRAME_MAX_MS = 34;      // ~30fps or better counts as rendering
	var PIPELINE_QUIET_MS = 2500;      // no new pipelines for this long => build finished
	var NO_PIPELINE_GRACE_MS = 8000;   // fallback if nothing is ever instrumented
	var MIN_VISIBLE_MS = 1200;         // avoid a jarring flash on instant loads
	var HARD_TIMEOUT_MS = 180000;      // never trap the viewer behind the overlay
	var SUSTAINED_SUBMITS = 20;        // command buffers in 1.5s => render loop is live

	var started = Date.now();

	// --- instrument pipeline construction (the thing that actually costs the time) ---
	var pipelineCount = 0;
	var lastPipelineAt = 0;
	var hooked = [];
	(function instrument() {
		if (typeof GPUDevice === 'undefined' || !GPUDevice.prototype) { return; }
		['createRenderPipeline', 'createComputePipeline',
			'createRenderPipelineAsync', 'createComputePipelineAsync'].forEach(function (name) {
			var orig = GPUDevice.prototype[name];
			if (typeof orig !== 'function') { return; }
			GPUDevice.prototype[name] = function () {
				pipelineCount++;
				lastPipelineAt = Date.now();
				return orig.apply(this, arguments);
			};
			hooked.push(name);
		});
	}());

	// The decisive signal: a running render loop submits a command buffer every frame.
	// Pipeline construction alone is not enough — Godot builds a few canvas pipelines
	// early, then goes quiet for many seconds while Tint translates the scene shaders
	// (translation creates no pipelines), which makes "pipelines have gone quiet" fire
	// long before anything is drawn. Sustained queue submissions only happen once the
	// engine is genuinely producing frames.
	var submitTimes = [];
	(function instrumentQueue() {
		if (typeof GPUQueue === 'undefined' || !GPUQueue.prototype) { return; }
		var orig = GPUQueue.prototype.submit;
		if (typeof orig !== 'function') { return; }
		GPUQueue.prototype.submit = function () {
			var now = Date.now();
			submitTimes.push(now);
			if (submitTimes.length > 200) { submitTimes.shift(); }
			return orig.apply(this, arguments);
		};
		hooked.push('submit');
	}());

	function submitsInLast(ms) {
		var cutoff = Date.now() - ms;
		var n = 0;
		for (var i = submitTimes.length - 1; i >= 0; i--) {
			if (submitTimes[i] >= cutoff) { n++; } else { break; }
		}
		return n;
	}

	// Exposed so the render harness can verify the overlay's own logic.
	window.__sfBoot = function () {
		return {
			hooked: hooked,
			pipelines: pipelineCount,
			sinceLastPipeline: lastPipelineAt ? Date.now() - lastPipelineAt : null,
			downloadDone: downloadDone,
			smooth: smooth,
			submits1_5s: submitsInLast(1500),
			totalSubmits: submitTimes.length,
			age: Date.now() - started
		};
	};

	// --- overlay ---
	var el = document.createElement('div');
	el.id = 'sf-boot-overlay';
	el.innerHTML =
		'<div class="sf-box">' +
		'  <div class="sf-spin" aria-hidden="true"></div>' +
		'  <div class="sf-title">Starting the engine</div>' +
		'  <div class="sf-msg" id="sf-msg">Loading…</div>' +
		'  <div class="sf-sub" id="sf-sub"></div>' +
		'</div>';

	var css = document.createElement('style');
	css.textContent =
		'#sf-boot-overlay{position:fixed;inset:0;z-index:2147483000;display:flex;' +
		'align-items:center;justify-content:center;background:#0b0e14;color:#e6ebf5;' +
		'font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;' +
		'transition:opacity .5s ease}' +
		'#sf-boot-overlay.sf-done{opacity:0;pointer-events:none}' +
		'#sf-boot-overlay .sf-box{text-align:center;padding:24px;max-width:440px}' +
		'#sf-boot-overlay .sf-title{font-size:1.25rem;font-weight:700;margin-bottom:6px}' +
		'#sf-boot-overlay .sf-msg{color:#97a3bb}' +
		'#sf-boot-overlay .sf-sub{color:#6d7a92;font-size:.85rem;margin-top:10px}' +
		'#sf-boot-overlay .sf-spin{width:34px;height:34px;margin:0 auto 16px;border-radius:50%;' +
		'border:3px solid #232a3a;border-top-color:#f5903a;animation:sf-rot 1s linear infinite}' +
		'@keyframes sf-rot{to{transform:rotate(360deg)}}' +
		'@media (prefers-reduced-motion:reduce){#sf-boot-overlay .sf-spin{animation:none}}';

	document.head.appendChild(css);
	function attach() { (document.body || document.documentElement).appendChild(el); }
	if (document.body) { attach(); } else { document.addEventListener('DOMContentLoaded', attach); }

	function msg(t) { var n = document.getElementById('sf-msg'); if (n) { n.textContent = t; } }
	function sub(t) { var n = document.getElementById('sf-sub'); if (n) { n.textContent = t; } }

	// --- phase reporting ---
	var progressEl = document.querySelector('#status-progress');
	var downloadDone = false;
	var downloadDoneAt = 0;

	var phaseTimer = setInterval(function () {
		var secs = Math.round((Date.now() - started) / 1000);

		if (!downloadDone && progressEl && progressEl.max > 0) {
			var pct = Math.min(100, Math.round((progressEl.value / progressEl.max) * 100));
			msg('Downloading engine — ' + pct + '%');
			sub(secs + 's elapsed');
			if (pct >= 100) { downloadDone = true; downloadDoneAt = Date.now(); }
			return;
		}
		if (!downloadDone && secs > 4) { downloadDone = true; downloadDoneAt = Date.now(); }

		if (pipelineCount > 0) {
			msg('Compiling shaders for your GPU');
			sub(pipelineCount + ' pipelines built — first load only, about 20 seconds. ' +
				secs + 's elapsed.');
		} else {
			msg('Preparing the engine');
			sub('First load only. ' + secs + 's elapsed.');
		}
	}, 250);

	// --- completion detection ---
	var smooth = 0;
	var last = performance.now();

	function tick(now) {
		var delta = now - last;
		last = now;
		if (delta > 0 && delta < SMOOTH_FRAME_MAX_MS) { smooth++; } else { smooth = 0; }

		var age = Date.now() - started;
		var settled = smooth >= SMOOTH_FRAMES_REQUIRED;

		// Primary: the render loop is submitting work every frame.
		var rendering = submitsInLast(1500) >= SUSTAINED_SUBMITS;

		// Fallback only if queue instrumentation never took (non-WebGPU build, or a
		// browser where GPUQueue is not patchable): fall back to the older signal.
		var instrumented = hooked.indexOf('submit') !== -1;
		var fallback = !instrumented && settled &&
			((pipelineCount > 0 && (Date.now() - lastPipelineAt) > PIPELINE_QUIET_MS) ||
			 (pipelineCount === 0 && downloadDone && (Date.now() - downloadDoneAt) > NO_PIPELINE_GRACE_MS));

		if ((age > MIN_VISIBLE_MS && (rendering || fallback)) || age > HARD_TIMEOUT_MS) {
			finish();
			return;
		}
		requestAnimationFrame(tick);
	}
	requestAnimationFrame(tick);

	var finished = false;
	function finish() {
		if (finished) { return; }
		finished = true;
		clearInterval(phaseTimer);
		el.classList.add('sf-done');
		setTimeout(function () { if (el.parentNode) { el.parentNode.removeChild(el); } }, 700);
	}
}());
