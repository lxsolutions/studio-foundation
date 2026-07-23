// Optional, mechanics-neutral Nakama bridge.
//
// Nakama owns public identity and RPC authentication. The application RPC
// forwards an opaque JSON value to a consumer-configured backend. Foundation
// does not interpret the payload or define its domain schema.

type ApplicationResult = {
  accepted: boolean;
  summary: string;
};

function rejected(summary: string): string {
  return JSON.stringify({ accepted: false, summary });
}

function rpcIdentify(
  ctx: nkruntime.Context,
  logger: nkruntime.Logger,
  nk: nkruntime.Nakama,
  payload: string,
): string {
  const userId = ctx.userId || "anonymous";
  logger.info("studio_identify: %s", userId);
  return JSON.stringify({ ok: true, userId });
}

function rpcApplicationRequest(
  ctx: nkruntime.Context,
  logger: nkruntime.Logger,
  nk: nkruntime.Nakama,
  rawPayload: string,
): string {
  if (!ctx.userId) {
    return rejected("authentication required");
  }

  let payload: unknown;
  try {
    payload = JSON.parse(rawPayload || "");
  } catch {
    return rejected("invalid json");
  }

  const applicationUrl = ctx.env && ctx.env.STUDIO_APPLICATION_URL;
  const applicationToken = ctx.env && ctx.env.STUDIO_APPLICATION_TOKEN;
  if (!applicationUrl || !applicationToken) {
    logger.error("studio_application_request: backend is not configured");
    return rejected("application backend unavailable");
  }

  const body = JSON.stringify({ actor_user_id: ctx.userId, payload });
  let response: nkruntime.HttpResponse;
  try {
    response = nk.httpRequest(
      applicationUrl,
      "post",
      {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: "Bearer " + applicationToken,
      },
      body,
      5000,
      false,
    );
  } catch (error) {
    logger.error("studio_application_request: backend request failed: %s", String(error));
    return rejected("application backend unavailable");
  }

  if (response.code < 200 || response.code >= 300) {
    logger.error(
      "studio_application_request: backend rejected request with HTTP %d",
      response.code,
    );
    return rejected("application backend rejected request");
  }

  try {
    const result = JSON.parse(response.body) as Partial<ApplicationResult>;
    if (typeof result.accepted !== "boolean" || typeof result.summary !== "string") {
      throw new Error("unexpected response shape");
    }
    logger.info(
      "studio_application_request: user=%s accepted=%s",
      ctx.userId,
      result.accepted,
    );
    return JSON.stringify({
      accepted: result.accepted,
      summary: result.summary,
    });
  } catch (error) {
    logger.error(
      "studio_application_request: malformed backend response: %s",
      String(error),
    );
    return rejected("malformed application backend response");
  }
}

function InitModule(
  ctx: nkruntime.Context,
  logger: nkruntime.Logger,
  nk: nkruntime.Nakama,
  initializer: nkruntime.Initializer,
): void {
  initializer.registerRpc("studio_identify", rpcIdentify);
  initializer.registerRpc("studio_application_request", rpcApplicationRequest);
  logger.info(
    "studio foundation nakama module initialized (studio_identify, studio_application_request)",
  );
}
