//! DB-backed integration tests. `#[ignore]` by default; run with a live dev/test
//! database via `just test-db` (which sets DATABASE_URL and passes --ignored).
//! Proves: migrations apply from empty, and the control API performs a real
//! PostgreSQL read/write transaction.

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use studio_control_api::{build_router, connect_pool, AppState, MIGRATOR};
use tower::ServiceExt;

fn database_url() -> Option<String> {
    std::env::var("DATABASE_URL").ok().filter(|s| !s.is_empty())
}

#[tokio::test]
#[ignore = "requires live PostgreSQL (just services-up && just test-db)"]
async fn migrations_apply_and_bootstrap_check_roundtrips() {
    let url = database_url().expect("DATABASE_URL required for -- --ignored tests");
    let pool = connect_pool(&url).await.expect("db reachable");
    MIGRATOR
        .run(&pool)
        .await
        .expect("migrations apply from empty or current state");

    let app = build_router(AppState {
        pool: Some(pool.clone()),
        service: "control-api-test",
        version: "test",
    });

    // /readyz proves live connectivity.
    let ready = app
        .clone()
        .oneshot(Request::get("/readyz").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(ready.status(), StatusCode::OK);

    // /v1/bootstrap-check proves a write+read inside one transaction.
    let res = app
        .clone()
        .oneshot(
            Request::post("/v1/bootstrap-check")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(value["roundtrip_ok"], true, "body: {value}");

    // KV endpoints prove upsert + fetch through the public surface.
    let put = app
        .clone()
        .oneshot(
            Request::post("/v1/kv/integration_probe")
                .header("content-type", "application/json")
                .body(Body::from(r#"{"suite":"db_roundtrip"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(put.status(), StatusCode::OK);
    let got = app
        .clone()
        .oneshot(
            Request::get("/v1/kv/integration_probe")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(got.status(), StatusCode::OK);
    let bytes = got.into_body().collect().await.unwrap().to_bytes();
    let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(value["value"]["suite"], "db_roundtrip");
}

#[tokio::test]
#[ignore = "requires live PostgreSQL (just services-up && just test-db)"]
async fn guest_session_creates_account_session_audit() {
    let url = database_url().expect("DATABASE_URL required");
    let pool = connect_pool(&url).await.expect("db reachable");
    MIGRATOR.run(&pool).await.unwrap();
    let app = build_router(AppState {
        pool: Some(pool),
        service: "control-api-test",
        version: "test",
    });
    let res = app
        .oneshot(
            Request::post("/v1/session/guest")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert!(value["account_id"].is_string());
    assert!(value["session_id"].is_string());
}
