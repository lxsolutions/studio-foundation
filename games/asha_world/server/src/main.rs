//! Game server binary for asha_world. Reuses the studio dedicated
//! server foundation; game-specific simulation systems land here later —
//! the template ships connectivity only (no mechanics, by design).

mod authority;
mod persistence;

use std::sync::Arc;
use studio_world_sim::WorldSim;
use tokio::sync::Mutex;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_env("STUDIO_LOG").unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let addr = std::env::var("STUDIO_DEDICATED_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:8081".into())
        .parse()?;

    // One authoritative world per server process (ADR 0007). Restore it from
    // PostgreSQL when configured (ADR 0005); otherwise use explicit in-memory dev
    // mode. Configured persistence fails boot rather than silently losing authority.
    let mut snapshotter = None;
    let mut world_store = None;
    let world: Arc<Mutex<WorldSim>> = match std::env::var("DATABASE_URL") {
        Ok(url) => {
            // An explicitly configured database is mandatory authority. Connection,
            // migration, or restore failure aborts boot instead of inventing a new world.
            let pool = sqlx::PgPool::connect(&url).await?;
            persistence::run_migrations(&pool).await?;
            let store = persistence::WorldStore::new(pool, Arc::<str>::from("default"));
            store.ensure_world(&WorldSim::default()).await?;
            let sim = store.restore_world().await?;
            let shared = Arc::new(Mutex::new(sim));
            snapshotter = Some(persistence::spawn_snapshotter(
                store.clone(),
                shared.clone(),
                std::time::Duration::from_secs(2),
            ));
            world_store = Some(store);
            tracing::info!(game = "asha_world", "world persistence enabled (postgres)");
            shared
        }
        Err(_) => {
            tracing::info!(
                game = "asha_world",
                "DATABASE_URL unset; running in-memory world (dev mode)"
            );
            Arc::new(Mutex::new(WorldSim::default()))
        }
    };

    tracing::info!(
        game = "asha_world",
        "starting game server (world-sim enabled)"
    );
    let (_local, handle) =
        studio_dedicated_server::run_server_with(addr, Some(world.clone())).await?;

    // The authority adapter is deliberately fail-closed: it only starts when a
    // database is connected and a non-empty bearer token is supplied. Nakama's
    // public RPC reports authority unavailable until both are configured.
    let authority_handle = match (
        world_store,
        std::env::var("ASHA_AUTHORITY_TOKEN")
            .ok()
            .filter(|value| !value.is_empty()),
    ) {
        (Some(store), Some(token)) => {
            let authority_addr =
                std::env::var("ASHA_AUTHORITY_ADDR").unwrap_or_else(|_| "127.0.0.1:8082".into());
            let listener = tokio::net::TcpListener::bind(&authority_addr).await?;
            tracing::info!(addr = %listener.local_addr()?, "Nakama authority adapter listening (http)");
            let app = authority::build_router(world, Some(store), token);
            Some(tokio::spawn(async move {
                if let Err(error) = axum::serve(listener, app).await {
                    tracing::error!(error = %error, "authority adapter stopped");
                }
            }))
        }
        _ => {
            tracing::warn!(
                "Nakama authority adapter disabled; DATABASE_URL and ASHA_AUTHORITY_TOKEN are required"
            );
            None
        }
    };

    tokio::signal::ctrl_c().await?;
    handle.abort();
    if let Some(snap) = snapshotter {
        snap.abort();
    }
    if let Some(authority) = authority_handle {
        authority.abort();
    }
    Ok(())
}
