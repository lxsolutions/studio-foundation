//! Game server binary for asha_world. Reuses the studio dedicated
//! server foundation; game-specific simulation systems land here later —
//! the template ships connectivity only (no mechanics, by design).

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
    // PostgreSQL when a snapshot exists (ADR 0005); otherwise start fresh and
    // persist going forward. Database unreachable => in-memory dev mode with a
    // loud warning (authority must never silently vanish).
    let mut snapshotter = None;
    let world: Arc<Mutex<WorldSim>> = match std::env::var("DATABASE_URL") {
        Ok(url) => match sqlx::PgPool::connect(&url).await {
            Ok(pool) => {
                let sim = persistence::restore_world(&pool)
                    .await
                    .unwrap_or_else(WorldSim::default);
                let shared = Arc::new(Mutex::new(sim));
                snapshotter = Some(persistence::spawn_snapshotter(
                    pool,
                    shared.clone(),
                    std::time::Duration::from_secs(2),
                ));
                tracing::info!(game = "asha_world", "world persistence enabled (postgres)");
                shared
            }
            Err(err) => {
                tracing::warn!(error = %err, "DATABASE_URL set but postgres unreachable; running in-memory world");
                Arc::new(Mutex::new(WorldSim::default()))
            }
        },
        Err(_) => {
            tracing::info!(game = "asha_world", "DATABASE_URL unset; running in-memory world (dev mode)");
            Arc::new(Mutex::new(WorldSim::default()))
        }
    };

    tracing::info!(game = "asha_world", "starting game server (world-sim enabled)");
    let (_local, handle) = studio_dedicated_server::run_server_with(addr, Some(world)).await?;
    tokio::signal::ctrl_c().await?;
    handle.abort();
    if let Some(snap) = snapshotter {
        snap.abort();
    }
    Ok(())
}
