// Minimal ambient declarations for the Nakama JavaScript runtime surface used
// by this module. Nakama injects these globals at runtime.
declare namespace nkruntime {
  type RequestMethod = "get" | "post" | "put" | "patch" | "delete" | "head";

  interface Context {
    userId?: string;
    username?: string;
    env?: { [key: string]: string };
    [key: string]: unknown;
  }

  interface Logger {
    info(format: string, ...args: unknown[]): void;
    warn(format: string, ...args: unknown[]): void;
    error(format: string, ...args: unknown[]): void;
  }

  interface HttpResponse {
    code: number;
    headers: { [key: string]: string[] };
    body: string;
  }

  interface Nakama {
    httpRequest(
      url: string,
      method: RequestMethod,
      headers: { [key: string]: string },
      body: string,
      timeout?: number,
      insecure?: boolean,
    ): HttpResponse;
    [key: string]: unknown;
  }

  interface Initializer {
    registerRpc(
      id: string,
      fn: (ctx: Context, logger: Logger, nk: Nakama, payload: string) => string,
    ): void;
  }
}
