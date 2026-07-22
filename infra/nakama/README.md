# Nakama authority bridge

Nakama owns the public identity/RPC boundary. `asha_world_event` does not settle
game state in TypeScript: it forwards one canonical event to the private HTTP
adapter in `games/asha_world/server`. The Rust server settles with `WorldSim` and
writes the canonical event ledger row and PostgreSQL snapshot atomically before
returning a result.

The bridge fails closed. World-event RPCs return `applied: false` when the caller
is unauthenticated, the bridge URL/token is absent, the authority cannot be
reached, persistence fails, or the response contract is malformed.

## Local live proof

Copy `.env.example` to the ignored `.env`, set
`ASHA_AUTHORITY_TOKEN` to a random development value, then run:

```text
just services-up
just asha-server
```

Keep the Asha server running. In another terminal:

```text
just nakama-up
just nakama-probe
```

The probe creates a unique device account, verifies `asha_identify`, submits a
unique `ResourceExtracted` event, and submits the same event again. It passes only
when the first settlement is applied and Rust reports the replay as a duplicate.

`ASHA_AUTHORITY_URL` is evaluated inside the Nakama container. The example uses
`host.docker.internal`, which Compose maps to the Docker host. On a remote or
native-Linux deployment, set both `ASHA_AUTHORITY_ADDR` and
`ASHA_AUTHORITY_URL` to a firewall-protected private interface reachable from
Nakama; never publish this adapter to the public internet.

## Tests

`just nakama-test` compiles the runtime to ES5, exercises forwarding and
fail-closed behavior with a fake Nakama runtime, and tests the live-probe response
contract. The Asha server's Rust suite separately verifies bearer authentication,
real settlement, atomic ledger/snapshot persistence, stale-memory recovery, and
idempotent replay.

Runtime configuration follows Nakama's documented `runtime.env` context, and the
bridge uses the synchronous TypeScript `nk.httpRequest` API:

- <https://heroiclabs.com/docs/nakama/server-framework/introduction/runtime-context/>
- <https://heroiclabs.com/docs/nakama/server-framework/typescript-runtime/function-reference/#httprequest>
