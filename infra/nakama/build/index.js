"use strict";
// Nakama owns public identity and the RPC boundary. Canonical world events are
// forwarded to the private Asha authority adapter, which settles through the Rust
// WorldSim and persists to PostgreSQL before acknowledging an applied event.
function rpcIdentify(ctx, logger, nk, payload) {
    var _a;
    var userId = (_a = ctx.userId) !== null && _a !== void 0 ? _a : "anonymous";
    logger.info("asha_identify: %s", userId);
    return JSON.stringify({ ok: true, userId: userId });
}
function rpcWorldEvent(ctx, logger, nk, payload) {
    if (!ctx.userId) {
        return JSON.stringify({ applied: false, summary: "authentication required" });
    }
    var event;
    try {
        event = JSON.parse(payload || "");
    }
    catch (_a) {
        return JSON.stringify({ applied: false, summary: "invalid json" });
    }
    if (!event || typeof event !== "object" || Object.keys(event).length !== 1) {
        return JSON.stringify({ applied: false, summary: "expected one canonical world event" });
    }
    var authorityUrl = ctx.env && ctx.env.ASHA_AUTHORITY_URL;
    var authorityToken = ctx.env && ctx.env.ASHA_AUTHORITY_TOKEN;
    if (!authorityUrl || !authorityToken) {
        logger.error("asha_world_event: authority is not configured");
        return JSON.stringify({ applied: false, summary: "authority unavailable" });
    }
    var body = JSON.stringify({ actor_user_id: ctx.userId, event: event });
    var response;
    try {
        response = nk.httpRequest(authorityUrl, "post", {
            "Content-Type": "application/json",
            Accept: "application/json",
            Authorization: "Bearer ".concat(authorityToken),
        }, body, 5000, false);
    }
    catch (error) {
        logger.error("asha_world_event: authority request failed: %s", String(error));
        return JSON.stringify({ applied: false, summary: "authority unavailable" });
    }
    if (response.code < 200 || response.code >= 300) {
        logger.error("asha_world_event: authority rejected request with HTTP %d", response.code);
        return JSON.stringify({ applied: false, summary: "authority rejected request" });
    }
    try {
        var result = JSON.parse(response.body);
        if (typeof result.applied !== "boolean" || typeof result.summary !== "string") {
            throw new Error("unexpected response shape");
        }
        logger.info("asha_world_event: user=%s applied=%s", ctx.userId, result.applied);
        return JSON.stringify({ applied: result.applied, summary: result.summary });
    }
    catch (error) {
        logger.error("asha_world_event: malformed authority response: %s", String(error));
        return JSON.stringify({ applied: false, summary: "malformed authority response" });
    }
}
function InitModule(ctx, logger, nk, initializer) {
    initializer.registerRpc("asha_identify", rpcIdentify);
    initializer.registerRpc("asha_world_event", rpcWorldEvent);
    logger.info("asha nakama module initialized (asha_identify, asha_world_event)");
}
