"use strict";
// Optional, mechanics-neutral Nakama bridge.
//
// Nakama owns public identity and RPC authentication. The application RPC
// forwards an opaque JSON value to a consumer-configured backend. Foundation
// does not interpret the payload or define its domain schema.
function rejected(summary) {
    return JSON.stringify({ accepted: false, summary: summary });
}
function rpcIdentify(ctx, logger, nk, payload) {
    var userId = ctx.userId || "anonymous";
    logger.info("studio_identify: %s", userId);
    return JSON.stringify({ ok: true, userId: userId });
}
function rpcApplicationRequest(ctx, logger, nk, rawPayload) {
    if (!ctx.userId) {
        return rejected("authentication required");
    }
    var payload;
    try {
        payload = JSON.parse(rawPayload || "");
    }
    catch (_a) {
        return rejected("invalid json");
    }
    var applicationUrl = ctx.env && ctx.env.STUDIO_APPLICATION_URL;
    var applicationToken = ctx.env && ctx.env.STUDIO_APPLICATION_TOKEN;
    if (!applicationUrl || !applicationToken) {
        logger.error("studio_application_request: backend is not configured");
        return rejected("application backend unavailable");
    }
    var body = JSON.stringify({ actor_user_id: ctx.userId, payload: payload });
    var response;
    try {
        response = nk.httpRequest(applicationUrl, "post", {
            "Content-Type": "application/json",
            Accept: "application/json",
            Authorization: "Bearer " + applicationToken,
        }, body, 5000, false);
    }
    catch (error) {
        logger.error("studio_application_request: backend request failed: %s", String(error));
        return rejected("application backend unavailable");
    }
    if (response.code < 200 || response.code >= 300) {
        logger.error("studio_application_request: backend rejected request with HTTP %d", response.code);
        return rejected("application backend rejected request");
    }
    try {
        var result = JSON.parse(response.body);
        if (typeof result.accepted !== "boolean" || typeof result.summary !== "string") {
            throw new Error("unexpected response shape");
        }
        logger.info("studio_application_request: user=%s accepted=%s", ctx.userId, result.accepted);
        return JSON.stringify({
            accepted: result.accepted,
            summary: result.summary,
        });
    }
    catch (error) {
        logger.error("studio_application_request: malformed backend response: %s", String(error));
        return rejected("malformed application backend response");
    }
}
function InitModule(ctx, logger, nk, initializer) {
    initializer.registerRpc("studio_identify", rpcIdentify);
    initializer.registerRpc("studio_application_request", rpcApplicationRequest);
    logger.info("studio foundation nakama module initialized (studio_identify, studio_application_request)");
}
