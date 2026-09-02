// The browser half of StudioSimKernel (ADR 0019).
//
// This is the file `sim_kernel.gd` injects with JavaScriptBridge.eval() inside a
// Godot web export, and the same file `tests/browser/sim-kernel-host.mjs` drives
// in a real browser — one implementation, so the half that cannot be exercised
// without Godot is a thin wrapper around a half that is checked every run.
//
// Two constraints shape it, and both are load-bearing:
//
//   1. It runs as a CLASSIC script. JavaScriptBridge.eval() evaluates code in the
//      page's global scope, where `import`/`export` is a syntax error. So: an IIFE
//      that hangs one namespace off globalThis, and nothing else.
//
//   2. It runs INSIDE a page whose WebAssembly main module is already Godot's
//      Emscripten build — which is the entire point. `sim_kernel.wasm` imports
//      nothing (enforced by tools/sim/host_abi.py), so instantiating it here adds
//      an ordinary second module beside Godot's. It does not contend for the
//      main-module slot, share Godot's linear memory, or touch Godot's runtime.
//      That is the difference between this and a .NET web export, which fails
//      precisely because it wants the slot Godot is standing in.
//
// Only loading is asynchronous. Once the module is instantiated, `run()` is a
// synchronous wasm call, so GDScript polls `status()` once and then calls
// `run()` inline — no callbacks, no frame-straddling state.
(function () {
  "use strict";

  var NS = "__studio_sim_kernel";
  // eval() may run more than once (scene reloads, a second host object). Loading
  // must not restart underneath a caller that is already polling it.
  if (globalThis[NS]) {
    return;
  }

  var host = {
    // Bumped when the GDScript/JS contract changes; sim_kernel.gd asserts it.
    contract: 1,
    _status: "idle", // idle | loading | ready | error
    _error: "",
    _url: "",
    _wasm: null,
  };

  function fail(message) {
    host._status = "error";
    host._error = String(message);
  }

  /** Begin instantiating the kernel. Idempotent; returns the current status. */
  host.load = function (url) {
    if (host._status === "loading" || host._status === "ready") {
      return host._status;
    }
    host._status = "loading";
    host._error = "";
    host._url = String(url);

    // instantiateStreaming needs application/wasm; a server that serves the file
    // as octet-stream would otherwise fail in a way that reads like a bad build.
    var instantiate = fetch(host._url).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status + " fetching " + host._url);
      }
      var type = response.headers.get("content-type") || "";
      if (typeof WebAssembly.instantiateStreaming === "function" && /wasm/.test(type)) {
        return WebAssembly.instantiateStreaming(response, {});
      }
      return response.arrayBuffer().then(function (bytes) {
        return WebAssembly.instantiate(bytes, {});
      });
    });

    instantiate.then(
      function (result) {
        var exports = result.instance.exports;
        var missing = ["memory", "sim_alloc", "sim_free", "sim_run"].filter(function (name) {
          return !exports[name];
        });
        if (missing.length) {
          fail("kernel is missing exports: " + missing.join(", "));
          return;
        }
        host._wasm = exports;
        host._status = "ready";
      },
      function (error) {
        fail(error && error.message ? error.message : error);
      }
    );
    return host._status;
  };

  host.status = function () {
    return host._status;
  };

  host.error = function () {
    return host._error;
  };

  /**
   * Run one replay. Always returns a JSON string — GDScript cannot catch a JS
   * exception across the bridge, so a thrown error becomes a result it can parse.
   * Host failures carry a `host_` code so they are never mistaken for the
   * kernel's own rejection codes (see docs/specs/sim-replay-v0.1.md).
   */
  host.run = function (replayText) {
    if (host._status !== "ready") {
      return JSON.stringify({
        code: "host_not_ready",
        error: "kernel status is '" + host._status + "'" + (host._error ? ": " + host._error : ""),
      });
    }
    try {
      var wasm = host._wasm;
      var input = new TextEncoder().encode(String(replayText));
      var inPtr = wasm.sim_alloc(input.length);
      if (inPtr === 0 && input.length > 0) {
        return JSON.stringify({ code: "host_alloc_failed", error: "sim_alloc returned null" });
      }
      // Every view is built AFTER the call that could have grown linear memory:
      // growth detaches the old ArrayBuffer, and a stale view reads zeroes.
      new Uint8Array(wasm.memory.buffer, inPtr, input.length).set(input);

      var packed = BigInt(wasm.sim_run(inPtr, input.length));
      wasm.sim_free(inPtr, input.length);

      var outPtr = Number(packed >> 32n);
      var outLen = Number(packed & 0xffffffffn);
      var out = new TextDecoder().decode(new Uint8Array(wasm.memory.buffer, outPtr, outLen));
      wasm.sim_free(outPtr, outLen);
      return out;
    } catch (error) {
      return JSON.stringify({
        code: "host_exception",
        error: error && error.message ? error.message : String(error),
      });
    }
  };

  globalThis[NS] = host;
})();
