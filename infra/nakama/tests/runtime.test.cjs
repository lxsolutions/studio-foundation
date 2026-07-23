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

function applicationContext() {
  return {
    userId: "user-42",
    env: {
      STUDIO_APPLICATION_URL: "http://application:8082/requests",
      STUDIO_APPLICATION_TOKEN: "test-token",
    },
  };
}

test("InitModule registers only the neutral public RPC seam", () => {
  const { rpcs } = loadRpcs();
  assert.deepEqual([...rpcs.keys()], [
    "studio_identify",
    "studio_application_request",
  ]);
});

test("identify returns authenticated and anonymous identities", () => {
  const { logger, rpcs } = loadRpcs();
  const identify = rpcs.get("studio_identify");
  assert.deepEqual(JSON.parse(identify({ userId: "user-42" }, logger, {}, "")), {
    ok: true,
    userId: "user-42",
  });
  assert.deepEqual(JSON.parse(identify({}, logger, {}, "")), {
    ok: true,
    userId: "anonymous",
  });
});

test("application RPC rejects unauthenticated or malformed submissions", () => {
  const { logger, rpcs } = loadRpcs();
  const submit = rpcs.get("studio_application_request");

  assert.deepEqual(JSON.parse(submit({}, logger, {}, "{}")), {
    accepted: false,
    summary: "authentication required",
  });
  assert.deepEqual(JSON.parse(submit(applicationContext(), logger, {}, "{")), {
    accepted: false,
    summary: "invalid json",
  });
});

test("application RPC forwards an opaque payload with authenticated actor", () => {
  const { logger, rpcs } = loadRpcs();
  const submit = rpcs.get("studio_application_request");
  const payload = { kind: "example.increment", value: 1 };
  let request;
  const nk = {
    httpRequest(...args) {
      request = args;
      return {
        code: 200,
        headers: {},
        body: JSON.stringify({ accepted: true, summary: "accepted" }),
      };
    },
  };

  assert.deepEqual(
    JSON.parse(submit(applicationContext(), logger, nk, JSON.stringify(payload))),
    { accepted: true, summary: "accepted" },
  );
  assert.equal(request[0], "http://application:8082/requests");
  assert.equal(request[1], "post");
  assert.equal(request[2].Authorization, "Bearer test-token");
  assert.deepEqual(JSON.parse(request[3]), {
    actor_user_id: "user-42",
    payload,
  });
  assert.equal(request[4], 5000);
  assert.equal(request[5], false);
});

test("application RPC fails closed for configuration, transport, status, or shape", () => {
  const { logger, rpcs } = loadRpcs();
  const submit = rpcs.get("studio_application_request");
  const payload = JSON.stringify({ example: true });

  assert.deepEqual(
    JSON.parse(submit({ userId: "user-42", env: {} }, logger, {}, payload)),
    { accepted: false, summary: "application backend unavailable" },
  );
  assert.deepEqual(
    JSON.parse(
      submit(
        applicationContext(),
        logger,
        { httpRequest() { throw new Error("offline"); } },
        payload,
      ),
    ),
    { accepted: false, summary: "application backend unavailable" },
  );
  assert.deepEqual(
    JSON.parse(
      submit(
        applicationContext(),
        logger,
        { httpRequest() { return { code: 503, headers: {}, body: "" }; } },
        payload,
      ),
    ),
    { accepted: false, summary: "application backend rejected request" },
  );
  assert.deepEqual(
    JSON.parse(
      submit(
        applicationContext(),
        logger,
        { httpRequest() { return { code: 200, headers: {}, body: "{}" }; } },
        payload,
      ),
    ),
    { accepted: false, summary: "malformed application backend response" },
  );
});

test("compiled runtime remains ES5-compatible", () => {
  const bundle = fs.readFileSync(path.join(__dirname, "..", "build", "index.js"), "utf8");
  assert.doesNotMatch(bundle, /\?\?|=>|\x60/);
  assert.doesNotMatch(bundle, /\b(?:const|let)\b/);
});
