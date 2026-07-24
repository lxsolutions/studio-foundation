/*
 * Studio Foundation — WebGPU boot overlay.
 *
 * Godot's web shell hides its loading UI as soon as startGame() resolves, but on
 * WebGPU that happens *before* the engine translates SPIR-V to WGSL and Dawn builds
 * the pipelines. For a large scene that is ~20 seconds of blocked main thread during
 * which the canvas is simply black — which reads as "the demo is broken" rather than
 * "it is still loading".
 *
 * This overlay stays up through that gap and reports what is actually happening.
 * It detects real rendering by watching requestAnimationFrame: while shaders compile
 * the main thread is blocked and rAF does not fire, so a run of consecutive smooth
 * frames means the engine is genuinely drawing.
 *
 * Drop-in: include this AFTER the shell's own script. It is standalone — if a future
 * re-export overwrites index.html, only the single <script> tag needs re-adding.
 */
(function () {
	'use strict';

	var SMOOTH_FRAMES_REQUIRED = 24;   // consecutive good frames before we believe it
	var SMOOTH_FRAME_MAX_MS = 34;      // ~30fps or better counts as "rendering"
	var HARD_TIMEOUT_MS = 180000;      // never trap the user behind the overlay

	var started = Date.now();
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

	var msg = function (t) { var n = document.getElementById('sf-msg'); if (n) { n.textContent = t; } };
	var sub = function (t) { var n = document.getElementById('sf-sub'); if (n) { n.textContent = t; } };

	// Phase 1: download. Godot's own progress element is the source of truth.
	var progressEl = document.querySelector('#status-progress');
	var downloadDone = false;
	var downloadDoneAt = 0;
	var phaseTimer = setInterval(function () {
		var secs = Math.round((Date.now() - started) / 1000);
		if (!downloadDone && progressEl && progressEl.max > 0) {
			var pct = Math.min(100, Math.round((progressEl.value / progressEl.max) * 100));
			msg('Downloading engine — ' + pct + '%');
			if (pct >= 100) { downloadDone = true; downloadDoneAt = Date.now(); }
		} else if (!downloadDone && secs > 4) {
			downloadDone = true;
			downloadDoneAt = Date.now();
		}
		if (downloadDone) {
			msg('Compiling shaders for your GPU');
			sub('First load only — about 20 seconds. ' + secs + 's elapsed.');
		} else {
			sub(secs + 's elapsed');
		}
	}, 250);

	// Phase 2: detect actual rendering.
	//
	// Smooth frames alone are NOT sufficient: while the engine is merely downloading,
	// the page is idle and rAF already runs at a clean 60fps, which would dismiss the
	// overlay within a second — exactly the black-canvas problem this exists to solve.
	// So we wait for evidence that the engine took over the main thread (a stall from
	// wasm instantiation / SPIR-V translation / pipeline building) and only then treat
	// a run of smooth frames as "drawing has begun". If no stall is ever observed —
	// small scene, warm cache, very fast machine — fall back to dismissing a short
	// while after the download finishes.
	var STALL_MS = 250;              // a blocked main thread looks like this
	var NO_STALL_GRACE_MS = 6000;    // fallback when nothing ever blocks
	var MIN_VISIBLE_MS = 1200;       // avoid a jarring flash on instant loads

	var smooth = 0;
	var sawStall = false;
	var last = performance.now();

	function tick(now) {
		var delta = now - last;
		last = now;

		if (delta >= STALL_MS) {
			sawStall = true;
			smooth = 0;
		} else if (delta > 0 && delta < SMOOTH_FRAME_MAX_MS) {
			smooth++;
		} else {
			smooth = 0;
		}

		var age = Date.now() - started;
		var settled = smooth >= SMOOTH_FRAMES_REQUIRED;
		var readyAfterStall = sawStall && settled;
		var readyWithoutStall = !sawStall && settled && downloadDone &&
			downloadDoneAt > 0 && (Date.now() - downloadDoneAt) > NO_STALL_GRACE_MS;

		if ((age > MIN_VISIBLE_MS && (readyAfterStall || readyWithoutStall)) || age > HARD_TIMEOUT_MS) {
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
})();
