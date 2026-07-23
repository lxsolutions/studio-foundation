# Optional Nakama bridge

This module provides reusable identity and authenticated RPC plumbing without
defining a game's domain model.

It registers two RPCs:

- `studio_identify` returns the authenticated Nakama user id.
- `studio_application_request` forwards an opaque JSON payload to a
  consumer-configured HTTP endpoint.

The bridge adds `actor_user_id` to the forwarded request:

```json
{
  "actor_user_id": "nakama-user-id",
  "payload": { "consumer": "owns this schema" }
}
```

The backend returns the neutral contract:

```json
{ "accepted": true, "summary": "consumer-defined explanation" }
```

Foundation validates only that `accepted` is boolean and `summary` is a
string. It does not inspect the payload or assign gameplay meaning to either
field.

## Local use

Copy `.env.example` to the ignored `.env`, then:

```sh
just services-up
just nakama-up
just nakama-probe
```

The default probe verifies device authentication and `studio_identify`.
To exercise application forwarding, configure `STUDIO_APPLICATION_URL` and
`STUDIO_APPLICATION_TOKEN`, run a consumer-owned backend that implements the
contract above, and pass an arbitrary JSON value:

```sh
just nakama-probe --application-json '{"kind":"consumer.example"}'
```

`STUDIO_APPLICATION_URL` is evaluated inside the Nakama container. The local
example uses `host.docker.internal`; production network policy, TLS, secrets,
and endpoint ownership belong to the consuming deployment.

## Failure behavior

The application RPC fails closed when the caller is unauthenticated, JSON is
invalid, configuration is absent, the backend is unavailable, HTTP status is
not successful, or the response contract is malformed.

`just nakama-test` compiles the runtime to ES5 and exercises registration,
identity, opaque forwarding, authentication, failure handling, and the probe
contract.
