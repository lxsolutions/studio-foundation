# Studio wire protocol v1

One protocol for every game and transport. Implementations:
Rust `services/shared-protocol` · GDScript `studio_core/net/protocol.gd`.
Both must pass the golden fixtures in `fixtures/` (CI-enforced).

## Envelope

JSON object (UTF-8). Binary/delta encodings will version through this same envelope
(`v` bump) when profiling demands it — not before.

| Field | Type | Rule |
|---|---|---|
| `v` | u16 | protocol version; receivers reject mismatches with `error(version_mismatch)` |
| `seq` | u64 | per-sender, monotonically increasing from 1 |
| `type` | string | message discriminator (snake_case) |
| ...body | — | flattened, per-type fields |

No timestamps in the envelope: simulation time is server-authoritative state, and
deterministic replay must not depend on wall clocks.

## Messages

| type | direction | fields | semantics |
|---|---|---|---|
| `hello` | client→server | `client`, `build`, `protocol` | first message on any transport |
| `hello_ack` | server→client | `server`, `protocol`, `session` (uuid) | connection accepted |
| `ping` / `pong` | both | `nonce` | liveness/RTT |
| `echo` / `echo_ack` | both | `text` | bootstrap round-trip demo only |
| `bye` | both | — | graceful close intent |
| `error` | both | `code`, `message` | codes: `version_mismatch`, `malformed`, `unexpected`, `internal` |

## Handshake

1. Client connects (WebSocket baseline; WebTransport/QUIC later — same envelope).
2. Client sends `hello`. Anything else → `error(unexpected)` + close.
3. Version match → `hello_ack` with a server-generated session id; mismatch →
   `error(version_mismatch)` + close.

## Versioning rules

- Additive optional fields: allowed within a version (receivers ignore unknowns).
- Renames/removals/semantic changes: bump `PROTOCOL_VERSION`, add fixtures for both
  versions, note the migration in an ADR. Never silently change a serialized format.
- Fixtures named `invalid_*.json` must be **rejected** by both implementations.

## Future (interfaces reserved, not implemented — see docs/networking/)

Server-authoritative simulation, client prediction + reconciliation, snapshot
interpolation, interest management, delta compression, deterministic replay. These
build on `Envelope` + per-game message enums; do not invent parallel protocols.
