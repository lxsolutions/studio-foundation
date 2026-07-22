//! Control API library: router + state, reusable from main.rs and integration tests.

use std::sync::Arc;

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

pub static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone)]
pub struct AppState {
    /// `None` = no DATABASE_URL configured; service still serves /healthz.
    pub pool: Option<PgPool>,
    pub service: &'static str,
    pub version: &'static str,
}

pub struct Config {
    pub addr: String,
    pub database_url: Option<String>,
}

impl Config {
    pub fn from_env() -> Self {
        Self {
            addr: std::env::var("STUDIO_CONTROL_API_ADDR")
                .unwrap_or_else(|_| "127.0.0.1:8080".into()),
            database_url: std::env::var("DATABASE_URL").ok().filter(|s| !s.is_empty()),
        }
    }
}

pub async fn connect_pool(database_url: &str) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(8)
        .connect(database_url)
        .await
}

enum AppError {
    NoDatabase,
    NotFound,
    Db(sqlx::Error),
}

impl From<sqlx::Error> for AppError {
    fn from(err: sqlx::Error) -> Self {
        match err {
            sqlx::Error::RowNotFound => AppError::NotFound,
            other => AppError::Db(other),
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        match self {
            AppError::NoDatabase => (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({"error": "no database configured (set DATABASE_URL)"})),
            )
                .into_response(),
            AppError::NotFound => {
                (StatusCode::NOT_FOUND, Json(json!({"error": "not found"}))).into_response()
            }
            AppError::Db(err) => {
                tracing::error!(error = %err, "database error");
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(json!({"error": "database error"})),
                )
                    .into_response()
            }
        }
    }
}

fn pool_of(state: &AppState) -> Result<&PgPool, AppError> {
    state.pool.as_ref().ok_or(AppError::NoDatabase)
}

async fn healthz() -> &'static str {
    "ok"
}

async fn readyz(State(state): State<Arc<AppState>>) -> Response {
    match &state.pool {
        Some(pool) => match sqlx::query_scalar::<_, i32>("SELECT 1")
            .fetch_one(pool)
            .await
        {
            Ok(_) => (StatusCode::OK, "ready").into_response(),
            Err(err) => {
                tracing::warn!(error = %err, "readyz: database unreachable");
                (StatusCode::SERVICE_UNAVAILABLE, "database unreachable").into_response()
            }
        },
        None => (StatusCode::SERVICE_UNAVAILABLE, "no database configured").into_response(),
    }
}

async fn status(State(state): State<Arc<AppState>>) -> Json<Value> {
    let db = match &state.pool {
        None => "unconfigured",
        Some(pool) => match sqlx::query_scalar::<_, i32>("SELECT 1")
            .fetch_one(pool)
            .await
        {
            Ok(_) => "ok",
            Err(_) => "unavailable",
        },
    };
    Json(json!({
        "service": state.service,
        "version": state.version,
        "protocol": studio_protocol::PROTOCOL_VERSION,
        "db": db,
    }))
}

async fn kv_get(
    State(state): State<Arc<AppState>>,
    Path(key): Path<String>,
) -> Result<Json<Value>, AppError> {
    let pool = pool_of(&state)?;
    let value: Value = sqlx::query_scalar("SELECT v FROM platform.kv_demo WHERE k = $1")
        .bind(&key)
        .fetch_one(pool)
        .await?;
    Ok(Json(json!({ "key": key, "value": value })))
}

async fn kv_put(
    State(state): State<Arc<AppState>>,
    Path(key): Path<String>,
    Json(body): Json<Value>,
) -> Result<Json<Value>, AppError> {
    let pool = pool_of(&state)?;
    sqlx::query(
        "INSERT INTO platform.kv_demo (k, v) VALUES ($1, $2)
         ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, updated_at = now()",
    )
    .bind(&key)
    .bind(&body)
    .execute(pool)
    .await?;
    Ok(Json(json!({ "key": key, "stored": true })))
}

/// Acceptance probe: one transaction that writes and reads back a row,
/// proving live PostgreSQL read/write behavior end to end.
async fn bootstrap_check(State(state): State<Arc<AppState>>) -> Result<Json<Value>, AppError> {
    let pool = pool_of(&state)?;
    let mut tx = pool.begin().await?;
    let wrote = json!({ "probe": "bootstrap", "nonce": rand::random::<u64>() });
    sqlx::query(
        "INSERT INTO platform.kv_demo (k, v) VALUES ('bootstrap_check', $1)
         ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, updated_at = now()",
    )
    .bind(&wrote)
    .execute(&mut *tx)
    .await?;
    let read: Value =
        sqlx::query_scalar("SELECT v FROM platform.kv_demo WHERE k = 'bootstrap_check'")
            .fetch_one(&mut *tx)
            .await?;
    tx.commit().await?;
    let ok = wrote == read;
    Ok(Json(
        json!({ "roundtrip_ok": ok, "wrote": wrote, "read": read }),
    ))
}

/// Minimal account/session stub: creates a guest account + session row.
async fn guest_session(State(state): State<Arc<AppState>>) -> Result<Json<Value>, AppError> {
    let pool = pool_of(&state)?;
    let suffix: u32 = rand::random::<u32>() % 1_000_000;
    let name = format!("guest_{suffix:06}");
    let mut tx = pool.begin().await?;
    let account_id: uuid::Uuid =
        sqlx::query_scalar("INSERT INTO platform.account (display_name) VALUES ($1) RETURNING id")
            .bind(&name)
            .fetch_one(&mut *tx)
            .await?;
    let session_id: uuid::Uuid =
        sqlx::query_scalar("INSERT INTO platform.session (account_id) VALUES ($1) RETURNING id")
            .bind(account_id)
            .fetch_one(&mut *tx)
            .await?;
    sqlx::query(
        "INSERT INTO platform.audit_log (actor, action, detail)
         VALUES ($1, 'guest_session_created', $2)",
    )
    .bind(&name)
    .bind(json!({ "session": session_id }))
    .execute(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(Json(json!({
        "account_id": account_id,
        "session_id": session_id,
        "display_name": name,
    })))
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get(healthz))
        .route("/readyz", get(readyz))
        .route("/v1/status", get(status))
        .route("/v1/kv/{key}", get(kv_get).post(kv_put))
        .route("/v1/bootstrap-check", post(bootstrap_check))
        .route("/v1/session/guest", post(guest_session))
        .with_state(Arc::new(state))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request;
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    fn app() -> Router {
        build_router(AppState {
            pool: None,
            service: "control-api",
            version: "test",
        })
    }

    #[tokio::test]
    async fn healthz_ok_without_db() {
        let res = app()
            .oneshot(Request::get("/healthz").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn readyz_503_without_db() {
        let res = app()
            .oneshot(Request::get("/readyz").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn status_reports_protocol_and_db_state() {
        let res = app()
            .oneshot(Request::get("/v1/status").body(Body::empty()).unwrap())
            .await
            .unwrap();
        let bytes = res.into_body().collect().await.unwrap().to_bytes();
        let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(value["db"], "unconfigured");
        assert_eq!(value["protocol"], studio_protocol::PROTOCOL_VERSION);
    }

    #[tokio::test]
    async fn kv_503_without_db() {
        let res = app()
            .oneshot(
                Request::post("/v1/kv/demo")
                    .header("content-type", "application/json")
                    .body(Body::from("{\"a\":1}"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::SERVICE_UNAVAILABLE);
    }
}
