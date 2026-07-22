// Minimal ambient declarations for the Nakama JS runtime surface this module
// uses. The real runtime injects these globals at load; we declare them so the
// module typechecks standalone (no external nakama-runtime package needed).
declare namespace nkruntime {
  interface Context {
    userId?: string;
    username?: string;
    [key: string]: unknown;
  }
  interface Logger {
    info(format: string, ...args: unknown[]): void;
    warn(format: string, ...args: unknown[]): void;
    error(format: string, ...args: unknown[]): void;
  }
  interface Nakama {
    [key: string]: unknown;
  }
  interface Initializer {
    registerRpc(id: string, fn: (ctx: Context, logger: Logger, nk: Nakama, payload: string) => string): void;
  }
}
