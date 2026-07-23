# ADR 0014: Keep Studio Foundation product-neutral

- Status: Accepted
- Date: 2026-07-22
- Constrains: repository scope, shared protocol, service interfaces, templates, documentation

## Context

Earlier revisions mixed a particular game's domain model, content, deployment,
and identity bridge into the public foundation. That made the reusable boundary
unclear and made generic engine and tooling work appear coupled to one game's
assumptions.

A public foundation is more useful when a generated project can represent an
action game, puzzle game, simulation, visualization, or multiplayer title
without deleting someone else's mechanics first.

## Decision

1. Product projects, content, business rules, schemas, identity policy, and
   deployments live in consuming repositories. Foundation may ship an optional
   provider adapter only when its contract remains mechanics-neutral.
2. Studio Foundation contains only reusable Godot integration, addons,
   mechanics-neutral templates, asset/export/release tooling, generic service
   scaffolding, optional provider adapters, and their tests.
3. The dedicated-server extension accepts an opaque application payload through
   a handler supplied by the consumer. Foundation assigns no domain meaning to
   that payload.
4. The shared wire contract moves to version 2. Product-specific version 1
   messages are replaced by `application_request` and `application_result`.
5. Examples prove infrastructure behavior only. They do not establish required
   game entities, progression, persistence, authority, or simulation models.

## Consequences

- The public repository can be evaluated and adopted without product context.
- A game's server can reuse the connection/session layer while owning its full
  schema and behavior.
- Version 1 clients must update message names and negotiate protocol version 2.
- Removed product material remains available in Git history for migration to a
  product-owned repository; it is not part of the Foundation release surface.
- OSWT is documented only as an external consuming repository and deployment
  proof. Its gameplay stays outside Studio Foundation.
