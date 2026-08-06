// Wasm parity harness: pass a replay file's RAW TEXT through the wasm build
// of sim-kernel and print the result JSON (or {"error","code"}). Contracts
// are inline in v0.1 replays, so the wasm module needs no document I/O — and
// raw text means even deliberately unparseable fixtures (NaN) reach the
// kernel untouched.
//
//   node tools/sim/parity_wasm.mjs <sim_kernel.wasm> <replay.json>
import { readFileSync } from "node:fs";

const [wasmPath, replayPath] = process.argv.slice(2);
const replayText = readFileSync(replayPath, "utf8");

const { instance } = await WebAssembly.instantiate(readFileSync(wasmPath), {});
const { sim_alloc, sim_run, sim_free, memory } = instance.exports;

const input = new TextEncoder().encode(replayText);
const inPtr = sim_alloc(input.length);
new Uint8Array(memory.buffer, inPtr, input.length).set(input);

const packed = sim_run(inPtr, input.length);
sim_free(inPtr, input.length);
const outPtr = Number(packed >> 32n);
const outLen = Number(packed & 0xffffffffn);
const out = new TextDecoder().decode(new Uint8Array(memory.buffer, outPtr, outLen));
sim_free(outPtr, outLen);
process.stdout.write(out + "\n");
