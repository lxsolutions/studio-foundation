const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadRpcs() {
  const bundle = fs.readFileSync(path.join(__dirname, "..", "build", "index.js"), "utf8");
  const context = vm.createContext({ JSON });
  vm.runInContext(bundle, context, { filename: "build/index.js" });

  const rpcs = new Map();
  const logger = { info() {}, warn() {}, error() {} };
  const initializer = {
    registerRpc(name, handler) {
      rpcs.set(name, handler);
    },
  };
  context.InitModule({}, logger, {}, initializer);
  return { logger, rpcs };
}

test("InitModule registers the public RPC seam", () => {
  const { rpcs } = loadRpcs();
  assert.deepEqual([...rpcs.keys()], ["asha_identify", "asha_world_event"]);
});

test("identify returns authenticated and anonymous identities", () => {
  const { logger, rpcs } = loadRpcs();
  const identify = rpcs.get("asha_identify");
  assert.deepEqual(JSON.parse(identify({ userId: "user-42" }, logger, {}, "")), {
    ok: true,
    userId: "user-42",
  });
  assert.deepEqual(JSON.parse(identify({}, logger, {}, "")), {
    ok: true,
    userId: "anonymous",
  });
});

test("world-event RPC rejects malformed payloads and accepts the required shape", () => {
  const { logger, rpcs } = loadRpcs();
  const submit = rpcs.get("asha_world_event");

  assert.deepEqual(JSON.parse(submit({}, logger, {}, "{")), {
    applied: false,
    summary: "invalid json",
  });
  assert.deepEqual(JSON.parse(submit({}, logger, {}, JSON.stringify({ type: "ResourceExtracted" }))), {
    applied: false,
    summary: "missing type or idempotency_key",
  });
  assert.deepEqual(
    JSON.parse(
      submit(
        {},
        logger,
        {},
        JSON.stringify({ type: "ResourceExtracted", idempotency_key: "event-1" }),
      ),
    ),
    { applied: true, summary: "accepted ResourceExtracted" },
  );
});
test("compiled runtime remains ES5-compatible", () => {
  const bundle = fs.readFileSync(path.join(__dirname, "..", "build", "index.js"), "utf8");
  assert.doesNotMatch(bundle, /\?\?|=>|`/);
  assert.doesNotMatch(bundle, /\b(?:const|let)\b/);
});