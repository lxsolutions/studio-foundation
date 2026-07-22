"use strict";
// Nakama runtime module (TypeScript) — the authoritative RPC seam the world-sim
// graduates to (ADR 0007). For the vertical slice this proves the identity +
// world-event RPC path; production settles into PostgreSQL via the same ledger
// shape as services/world-sim's idempotent settlement.
//
// Build: tsc (see package.json). Output lands in infra/nakama/build/index.js,
// which Compose mounts at the local.yml runtime.js_entrypoint.
function rpcIdentify(ctx, logger, nk, payload) {
    var _a;
    var userId = (_a = ctx.userId) !== null && _a !== void 0 ? _a : "anonymous";
    logger.info("asha_identify: %s", userId);
    return JSON.stringify({ ok: true, userId: userId });
}
// World-event settlement seam. The slice's WorldEventSubmit travels here once
// Nakama is live; for now it validates shape and echoes an idempotent-style ack.
function rpcWorldEvent(ctx, logger, nk, payload) {
    var event;
    try {
        event = JSON.parse(payload || "{}");
    }
    catch (_a) {
        return JSON.stringify({ applied: false, summary: "invalid json" });
    }
    if (!event.type || !event.idempotency_key) {
        return JSON.stringify({ applied: false, summary: "missing type or idempotency_key" });
    }
    logger.info("asha_world_event: %s key=%s", event.type, event.idempotency_key);
    return JSON.stringify({ applied: true, summary: "accepted ".concat(event.type) });
}
function InitModule(ctx, logger, nk, initializer) {
    initializer.registerRpc("asha_identify", rpcIdentify);
    initializer.registerRpc("asha_world_event", rpcWorldEvent);
    logger.info("asha nakama module initialized (asha_identify, asha_world_event)");
}
