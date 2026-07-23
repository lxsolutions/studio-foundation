# Studio wire protocol v2

This is a mechanics-neutral baseline for Foundation's optional WebSocket
session service. Implementations:

- Rust: `services/shared-protocol`
- GDScript: `shared/godot-addons/studio_core/net/protocol.gd`

Both implementations must pass the golden fixtures in `fixtures/`.

## Envelope

Messages are UTF-8 JSON objects. Binary or delta encodings require a future
version bump backed by measured need.

| Field | Type | Rule |
|---|---|---|
| `v` | u16 | protocol version; receivers reject mismatches |
| `seq` | u64 | per-sender, monotonically increasing from 1 |
| `type` | string | snake_case message discriminator |
| body fields | message-specific | flattened into the envelope |

Foundation envelopes omit timestamps so the transport does not impose a clock
model. An application can carry its own timing or revision data inside its
opaque payload.

## Messages

| Type | Direction | Fields | Semantics |
|---|---|---|---|
| `hello` | client → server | `client`, `build`, `protocol` | first message |
| `hello_ack` | server → client | `server`, `protocol`, `session` | connection accepted |
| `ping` / `pong` | both | `nonce` | liveness and RTT |
| `echo` / `echo_ack` | both | `text` | bootstrap round-trip only |
| `application_request` | client → server | `payload_json` | optional opaque JSON |
| `application_result` | server → client | `accepted`, `summary` | neutral handler outcome |
| `bye` | both | none | graceful close intent |
| `error` | both | `code`, `message` | protocol or session failure |

## Handshake

1. Client connects.
2. Client sends `hello`; any other first message receives
   `error(unexpected)` and closes.
3. A matching version receives `hello_ack`; a mismatch receives
   `error(version_mismatch)` and closes.

## Application boundary

`application_request.payload_json` is an opaque string to Foundation. A
consuming game may register a handler, use only the connection messages, or
replace this protocol entirely. Foundation does not validate, store, settle, or
interpret the application payload.

## Versioning

- Additive optional fields may remain within a version.
- Renames, removals, or semantic changes require a version bump, updated
  fixtures, and an ADR migration note.
- Files named `invalid_*.json` must be rejected by both implementations.
