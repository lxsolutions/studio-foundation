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

function canonicalEvent(key = "00000000-0000-0000-0000-00000000000a") {
  return {
    ResourceExtracted: {
      faction: "00000000-0000-0000-0000-000000000001",
      sector: "00000000-0000-0000-0000-000000000002",
      resource: "RawOre",
      units: 100,
      idempotency_key: key,
    },
  };
}

function authorityContext() {
  return {
    userId: "user-42",
    env: {
      ASHA_AUTHORITY_URL: "http://authority:8082/internal/v1/world-events",
      ASHA_AUTHORITY_TOKEN: "test-token",
    },
  };
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

test("world-event RPC rejects unauthenticated and malformed submissions", () => {
  const { logger, rpcs } = loadRpcs();
  const submit = rpcs.get("asha_world_event");

  assert.deepEqual(JSON.parse(submit({}, logger, {}, JSON.stringify(canonicalEvent()))), {
    applied: false,
    summary: "authentication required",
  });
  assert.deepEqual(JSON.parse(submit(authorityContext(), logger, {}, "{")), {
    applied: false,
    summary: "invalid json",
  });
  assert.deepEqual(JSON.parse(submit(authorityContext(), logger, {}, JSON.stringify({}))), {
    applied: false,
    summary: "expected one canonical world event",
  });
});

test("world-event RPC forwards the actor and canonical event to Rust authority", () => {
  const { logger, rpcs } = loadRpcs();
  const submit = rpcs.get("asha_world_event");
  const event = canonicalEvent();
  let request;
  const nk = {
    httpRequest(...args) {
      request = args;
      return {
        code: 200,
        headers: {},
        body: JSON.stringify({ applied: true, summary: "faction banked 100 RawOre" }),
      };
    },
  };

  assert.deepEqual(JSON.parse(submit(authorityContext(), logger, nk, JSON.stringify(event))), {
    applied: true,
    summary: "faction banked 100 RawOre",
  });
  assert.equal(request[0], "http://authority:8082/internal/v1/world-events");
  assert.equal(request[1], "post");
  assert.equal(request[2].Authorization, "Bearer test-token");
  assert.deepEqual(JSON.parse(request[3]), { actor_user_id: "user-42", event });
  assert.equal(request[4], 5000);
  assert.equal(request[5], false);
});

test("world-event RPC fails closed when authority is unavailable or malformed", () => {
  const { logger, rpcs } = loadRpcs();
  const submit = rpcs.get("asha_world_event");
  const payload = JSON.stringify(canonicalEvent());

  assert.deepEqual(JSON.parse(submit({ userId: "user-42", env: {} }, logger, {}, payload)), {
    applied: false,
    summary: "authority unavailable",
  });
  assert.deepEqual(
    JSON.parse(
      submit(
        authorityContext(),
        logger,
        { httpRequest() { throw new Error("offline"); } },
        payload,
      ),
    ),
    { applied: false, summary: "authority unavailable" },
  );
  assert.deepEqual(
    JSON.parse(
      submit(
        authorityContext(),
        logger,
        { httpRequest() { return { code: 503, headers: {}, body: "" }; } },
        payload,
      ),
    ),
    { applied: false, summary: "authority rejected request" },
  );
  assert.deepEqual(
    JSON.parse(
      submit(
        authorityContext(),
        logger,
        { httpRequest() { return { code: 200, headers: {}, body: "{}" }; } },
        payload,
      ),
    ),
    { applied: false, summary: "malformed authority response" },
  );
});

test("compiled runtime remains ES5-compatible", () => {
  const bundle = fs.readFileSync(path.join(__dirname, "..", "build", "index.js"), "utf8");
  assert.doesNotMatch(bundle, /\?\?|=>|`/);
  assert.doesNotMatch(bundle, /\b(?:const|let)\b/);
});