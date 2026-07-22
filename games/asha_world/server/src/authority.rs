//! Private HTTP adapter used by Nakama to submit canonical world events.
//!
//! Nakama owns player identity and the public RPC. This adapter remains private:
//! it authenticates the Nakama runtime with a bearer token, settles through the
//! same `WorldSim` used by WebSocket sessions, and persists before acknowledging
//! an applied event.

use std::sync::Arc;

use axum::extract::State;
use axum::http::{header::AUTHORIZATION, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use studio_world_sim::{WorldEvent, WorldSim};
use tokio::sync::Mutex;

use crate::persistence;

pub type SharedWorld = Arc<Mutex<WorldSim>>;

#[derive(Clone)]
struct AuthorityState {
    world: SharedWorld,
    store: Option<persistence::WorldStore>,
    bearer_token: Arc<str>,
}

#[derive(Debug, Deserialize)]
struct WorldEventSubmission {
    actor_user_id: String,
    event: WorldEvent,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct WorldEventResult {
    pub applied: bool,
    pub summary: String,
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

fn authorized(headers: &HeaderMap, expected: &str) -> bool {
    let Some(value) = headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
    else {
        return false;
    };
    let Some(token) = value.strip_prefix("Bearer ") else {
        return false;
    };
    !expected.is_empty() && constant_time_eq(token.as_bytes(), expected.as_bytes())
}

async fn healthz() -> &'static str {
    "ok"
}

async fn submit_world_event(
    State(state): State<AuthorityState>,
    headers: HeaderMap,
    Json(submission): Json<WorldEventSubmission>,
) -> Response {
    if !authorized(&headers, &state.bearer_token) {
        return (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"error": "unauthorized"})),
        )
            .into_response();
    }
    if submission.actor_user_id.trim().is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "actor_user_id is required"})),
        )
            .into_response();
    }

    let mut world = state.world.lock().await;
    let settlement = match &state.store {
        Some(store) => match store
            .settle(&mut world, &submission.actor_user_id, &submission.event)
            .await
        {
            Ok(settlement) => settlement,
            Err(error) => {
                tracing::error!(error = %error, actor = %submission.actor_user_id, "durable world settlement failed");
                return (
                    StatusCode::SERVICE_UNAVAILABLE,
                    Json(serde_json::json!({"error": "world persistence unavailable"})),
                )
                    .into_response();
            }
        },
        None => world.settle(&submission.event),
    };

    tracing::info!(
        actor = %submission.actor_user_id,
        applied = settlement.applied,
        summary = %settlement.summary,
        "world event settled through Nakama authority adapter"
    );
    Json(WorldEventResult {
        applied: settlement.applied,
        summary: settlement.summary,
    })
    .into_response()
}

/// Build the private authority router. `store=None` is reserved for hermetic tests;
/// production only starts this listener after PostgreSQL connects successfully.
pub fn build_router(
    world: SharedWorld,
    store: Option<persistence::WorldStore>,
    bearer_token: String,
) -> Router {
    Router::new()
        .route("/healthz", get(healthz))
        .route("/internal/v1/world-events", post(submit_world_event))
        .with_state(AuthorityState {
            world,
            store,
            bearer_token: Arc::from(bearer_token),
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request;
    use http_body_util::BodyExt;
    use serde_json::json;
    use tower::ServiceExt;
    use uuid::Uuid;

    const TOKEN: &str = "unit-test-authority-token";

    fn app(world: SharedWorld) -> Router {
        build_router(world, None, TOKEN.into())
    }

    fn submission(key: Uuid) -> serde_json::Value {
        json!({
            "actor_user_id": "nakama-user-42",
            "event": {
                "ResourceExtracted": {
                    "faction": Uuid::from_u128(1),
                    "sector": Uuid::from_u128(2),
                    "resource": "RawOre",
                    "units": 100,
                    "idempotency_key": key
                }
            }
        })
    }

    async fn post(app: Router, body: serde_json::Value, token: Option<&str>) -> Response {
        let mut request =
            Request::post("/internal/v1/world-events").header("content-type", "application/json");
        if let Some(token) = token {
            request = request.header(AUTHORIZATION, format!("Bearer {token}"));
        }
        app.oneshot(request.body(Body::from(body.to_string())).unwrap())
            .await
            .unwrap()
    }

    async fn result(response: Response) -> WorldEventResult {
        let body = response.into_body().collect().await.unwrap().to_bytes();
        serde_json::from_slice(&body).unwrap()
    }

    #[tokio::test]
    async fn rejects_missing_or_wrong_bearer_token() {
        let world = Arc::new(Mutex::new(WorldSim::default()));
        assert_eq!(
            post(app(world.clone()), submission(Uuid::from_u128(10)), None)
                .await
                .status(),
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            post(
                app(world),
                submission(Uuid::from_u128(10)),
                Some("wrong-token")
            )
            .await
            .status(),
            StatusCode::UNAUTHORIZED
        );
    }

    #[tokio::test]
    async fn settles_once_and_rejects_replay_idempotently() {
        let world = Arc::new(Mutex::new(WorldSim::default()));
        let first = post(
            app(world.clone()),
            submission(Uuid::from_u128(10)),
            Some(TOKEN),
        )
        .await;
        assert_eq!(first.status(), StatusCode::OK);
        assert!(result(first).await.applied);

        let replay = post(
            app(world.clone()),
            submission(Uuid::from_u128(10)),
            Some(TOKEN),
        )
        .await;
        assert_eq!(replay.status(), StatusCode::OK);
        let replay = result(replay).await;
        assert!(!replay.applied);
        assert!(replay.summary.contains("duplicate"));

        let world = world.lock().await;
        assert_eq!(
            world.state.stockpile(
                studio_world_sim::FactionId(Uuid::from_u128(1)),
                studio_world_sim::state::Resource::RawOre,
            ),
            100
        );
    }
}
