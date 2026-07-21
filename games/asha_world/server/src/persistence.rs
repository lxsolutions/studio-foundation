//! PostgreSQL persistence for the authoritative world (ADR 0005 + ADR 0007).
//!
//! The world-sim is a deterministic in-memory core (services/world-sim) with a
//! serde `snapshot()`/`restore()` boundary. This module owns the database side:
//! restore the shared world on boot, and upsert a snapshot after each settlement
//! window so the one world survives restarts. Game-owned table:
//! `game_asha_world.world_snapshot` (migration 0002).

use sqlx::PgPool;
use std::sync::Arc;
use studio_world_sim::WorldSim;
use tokio::sync::Mutex;

const WORLD_ID: &str = "default";

/// Restore the world from PostgreSQL, or start fresh when no snapshot exists.
/// Returns `None` when the database is unreachable (caller decides: in-memory dev
/// mode is allowed, but it is logged loudly — authority must not silently vanish).
pub async fn restore_world(pool: &PgPool) -> Option<WorldSim> {
    let row: Option<(serde_json::Value,)> =
        sqlx::query_as("SELECT state FROM game_asha_world.world_snapshot WHERE world_id = $1")
            .bind(WORLD_ID)
            .fetch_optional(pool)
            .await
            .ok()?;
    let (state,) = row?;
    match WorldSim::restore(&state.to_string()) {
        Ok(sim) => {
            tracing::info!(world = WORLD_ID, "world restored from postgres");
            Some(sim)
        }
        Err(err) => {
            tracing::error!(error = %err, "world snapshot corrupt; starting fresh");
            None
        }
    }
}

/// Spawn a periodic snapshotter: every `interval` it writes the current world to
/// PostgreSQL. Settlement is cheap and the slice's event rate is low, so a short
/// periodic upsert is simpler and safer than per-event writes (no partial writes).
pub fn spawn_snapshotter(
    pool: PgPool,
    world: Arc<Mutex<WorldSim>>,
    interval: std::time::Duration,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(interval);
        loop {
            tick.tick().await;
            let json = {
                let sim = world.lock().await;
                match sim.snapshot() {
                    Ok(j) => j,
                    Err(err) => {
                        tracing::warn!(error = %err, "snapshot serialize failed");
                        continue;
                    }
                }
            };
            let result = sqlx::query(
                "INSERT INTO game_asha_world.world_snapshot (world_id, state)
                 VALUES ($1, $2::jsonb)
                 ON CONFLICT (world_id)
                 DO UPDATE SET state = EXCLUDED.state,
                               version = game_asha_world.world_snapshot.version + 1,
                               updated_at = now()",
            )
            .bind(WORLD_ID)
            .bind(&json)
            .execute(&pool)
            .await;
            if let Err(err) = result {
                tracing::warn!(error = %err, "world snapshot write failed");
            } else {
                tracing::debug!(world = WORLD_ID, "world snapshot written");
            }
        }
    })
}
