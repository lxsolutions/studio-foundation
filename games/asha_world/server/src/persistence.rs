//! PostgreSQL persistence for the authoritative world (ADR 0005 + ADR 0007).
//!
//! `world_snapshot` is the fast recovery image. `world_event_ledger` is the
//! append-only history and database-level idempotency authority. Durable
//! settlement locks one world row and commits the ledger record plus snapshot in
//! the same transaction, so PostgreSQL remains the source of truth.

use std::sync::Arc;

use anyhow::{ensure, Context};
use sqlx::PgPool;
use studio_world_sim::{Settlement, WorldEvent, WorldSim};
use tokio::sync::Mutex;

pub static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");
/// Run this game's migration history in its owned schema. SQLx otherwise uses a
/// database-global `_sqlx_migrations` table, which makes unrelated game and
/// platform version numbers collide.
pub async fn run_migrations(pool: &PgPool) -> anyhow::Result<()> {
    sqlx::query("CREATE SCHEMA IF NOT EXISTS game_asha_world")
        .execute(pool)
        .await
        .context("ensure game migration schema")?;
    let mut connection = pool
        .acquire()
        .await
        .context("acquire migration connection")?;
    sqlx::query("SET search_path TO game_asha_world")
        .execute(&mut *connection)
        .await
        .context("isolate game migration history")?;
    MIGRATOR
        .run(&mut *connection)
        .await
        .context("run game migrations")?;
    Ok(())
}

#[derive(Clone)]
pub struct WorldStore {
    pool: PgPool,
    world_id: Arc<str>,
}

impl WorldStore {
    pub fn new(pool: PgPool, world_id: impl Into<Arc<str>>) -> Self {
        Self {
            pool,
            world_id: world_id.into(),
        }
    }

    /// Create the world's recovery row exactly once. Existing state is never
    /// overwritten during startup.
    pub async fn ensure_world(&self, initial: &WorldSim) -> anyhow::Result<()> {
        let state = snapshot_value(initial)?;
        sqlx::query(
            "INSERT INTO game_asha_world.world_snapshot (world_id, state)
             VALUES ($1, $2)
             ON CONFLICT (world_id) DO NOTHING",
        )
        .bind(&*self.world_id)
        .bind(state)
        .execute(&self.pool)
        .await
        .context("ensure world snapshot row")?;
        Ok(())
    }

    /// Restore the authoritative snapshot. Missing/corrupt/unreadable state is a
    /// boot error after `ensure_world`; it must never silently become a new world.
    pub async fn restore_world(&self) -> anyhow::Result<WorldSim> {
        let state: serde_json::Value = sqlx::query_scalar(
            "SELECT state FROM game_asha_world.world_snapshot WHERE world_id = $1",
        )
        .bind(&*self.world_id)
        .fetch_one(&self.pool)
        .await
        .context("load world snapshot")?;
        WorldSim::restore(&state.to_string()).context("decode world snapshot")
    }

    /// Atomically settle one canonical event into both ledger and snapshot.
    ///
    /// The row lock serializes distinct events across multiple server processes.
    /// The candidate simulation is reconstructed from the locked PostgreSQL row,
    /// not trusted from process memory. Memory changes only after commit succeeds.
    pub async fn settle(
        &self,
        world: &mut WorldSim,
        actor_user_id: &str,
        event: &WorldEvent,
    ) -> anyhow::Result<Settlement> {
        let actor_user_id = actor_user_id.trim();
        ensure!(!actor_user_id.is_empty(), "actor_user_id is required");
        ensure!(actor_user_id.len() <= 256, "actor_user_id is too long");

        let mut tx = self.pool.begin().await.context("begin settlement")?;
        let state: serde_json::Value = sqlx::query_scalar(
            "SELECT state
             FROM game_asha_world.world_snapshot
             WHERE world_id = $1
             FOR UPDATE",
        )
        .bind(&*self.world_id)
        .fetch_one(&mut *tx)
        .await
        .context("lock world snapshot")?;
        let mut candidate =
            WorldSim::restore(&state.to_string()).context("decode locked world snapshot")?;

        let key = event.idempotency_key();
        let exists: bool = sqlx::query_scalar(
            "SELECT EXISTS(
                 SELECT 1
                 FROM game_asha_world.world_event_ledger
                 WHERE world_id = $1
                   AND idempotency_key = $2
             )",
        )
        .bind(&*self.world_id)
        .bind(key)
        .fetch_one(&mut *tx)
        .await
        .context("check event idempotency")?;
        if exists {
            tx.commit().await.context("finish duplicate lookup")?;
            *world = candidate;
            return Ok(Settlement {
                applied: false,
                summary: format!("duplicate {} ignored (database idempotency)", event.kind()),
            });
        }

        let settlement = candidate.settle(event);
        let snapshot = snapshot_value(&candidate)?;
        let event_json = serde_json::to_value(event).context("encode world event")?;

        sqlx::query(
            "INSERT INTO game_asha_world.world_event_ledger
                 (idempotency_key, world_id, actor_user_id, event_type, event, applied, summary)
             VALUES ($1, $2, $3, $4, $5, $6, $7)",
        )
        .bind(key)
        .bind(&*self.world_id)
        .bind(actor_user_id)
        .bind(event.kind())
        .bind(event_json)
        .bind(settlement.applied)
        .bind(&settlement.summary)
        .execute(&mut *tx)
        .await
        .context("append world event ledger")?;

        sqlx::query(
            "UPDATE game_asha_world.world_snapshot
             SET state = $2,
                 version = version + 1,
                 updated_at = now()
             WHERE world_id = $1",
        )
        .bind(&*self.world_id)
        .bind(snapshot)
        .execute(&mut *tx)
        .await
        .context("update world snapshot")?;

        tx.commit().await.context("commit world settlement")?;
        *world = candidate;
        Ok(settlement)
    }

    /// Persist in-memory state only when it differs. This is a development
    /// safety net for the legacy direct-WebSocket settlement path; production
    /// Nakama submissions always use [`Self::settle`].
    pub async fn persist_snapshot(&self, world: &WorldSim) -> anyhow::Result<()> {
        let state = snapshot_value(world)?;
        sqlx::query(
            "UPDATE game_asha_world.world_snapshot
             SET state = $2,
                 version = version + 1,
                 updated_at = now()
             WHERE world_id = $1
               AND state IS DISTINCT FROM $2",
        )
        .bind(&*self.world_id)
        .bind(state)
        .execute(&self.pool)
        .await
        .context("persist periodic world snapshot")?;
        Ok(())
    }
}

fn snapshot_value(world: &WorldSim) -> anyhow::Result<serde_json::Value> {
    let json = world.snapshot().context("encode world snapshot")?;
    serde_json::from_str(&json).context("materialize world snapshot JSON")
}

pub fn spawn_snapshotter(
    store: WorldStore,
    world: Arc<Mutex<WorldSim>>,
    interval: std::time::Duration,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(interval);
        loop {
            tick.tick().await;
            let result = {
                let sim = world.lock().await;
                store.persist_snapshot(&sim).await
            };
            if let Err(error) = result {
                tracing::warn!(error = %error, "world snapshot write failed");
            } else {
                tracing::debug!(world = %store.world_id, "world snapshot checked");
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use studio_world_sim::state::Resource;
    use studio_world_sim::{FactionId, SectorId};
    use uuid::Uuid;

    #[test]
    fn snapshot_value_roundtrips() {
        let world = WorldSim::default();
        let value = snapshot_value(&world).unwrap();
        assert!(WorldSim::restore(&value.to_string()).is_ok());
    }

    #[tokio::test]
    #[ignore = "requires live PostgreSQL (just services-up && just test-db)"]
    async fn ledger_and_snapshot_commit_atomically_and_replay_from_database() {
        let url = std::env::var("DATABASE_URL").expect("DATABASE_URL required");
        let pool = PgPool::connect(&url).await.expect("connect database");
        run_migrations(&pool).await.expect("run game migrations");
        let migration_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM game_asha_world._sqlx_migrations WHERE success",
        )
        .fetch_one(&pool)
        .await
        .expect("count schema-local game migrations");
        assert_eq!(migration_count, 4);

        let world_id = format!("authority-test-{}", Uuid::new_v4());
        let store = WorldStore::new(pool.clone(), Arc::<str>::from(world_id.clone()));
        store
            .ensure_world(&WorldSim::default())
            .await
            .expect("create isolated test world");
        let mut world = store.restore_world().await.expect("restore test world");

        let faction = FactionId(Uuid::new_v4());
        let sector = SectorId(Uuid::new_v4());
        let extract = WorldEvent::ResourceExtracted {
            faction,
            sector,
            resource: Resource::RawOre,
            units: 100,
            idempotency_key: Uuid::new_v4(),
        };
        let first = store
            .settle(&mut world, "nakama-user-42", &extract)
            .await
            .expect("settle extraction");
        assert!(first.applied);

        // A stale process mirror is repaired from PostgreSQL before duplicate
        // detection; the database, not memory, decides the replay outcome.
        let mut stale = WorldSim::default();
        let replay = store
            .settle(&mut stale, "nakama-user-42", &extract)
            .await
            .expect("settle replay");
        assert!(!replay.applied);
        assert!(replay.summary.contains("database idempotency"));
        assert_eq!(stale.state.stockpile(faction, Resource::RawOre), 100);

        // Business rejection still consumes and persists its idempotency key.
        let rejected = WorldEvent::FactoryCompleted {
            faction,
            sector,
            item: "armored_vehicle".into(),
            refined_units: 10,
            idempotency_key: Uuid::new_v4(),
        };
        let outcome = store
            .settle(&mut stale, "nakama-user-42", &rejected)
            .await
            .expect("record rejected event");
        assert!(!outcome.applied);
        assert!(outcome.summary.contains("lacked"));

        let mut restored = store.restore_world().await.expect("restore settled world");
        let replay = restored.settle(&rejected);
        assert!(!replay.applied);
        assert!(replay.summary.contains("duplicate"));

        let ledger_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM game_asha_world.world_event_ledger WHERE world_id = $1",
        )
        .bind(&world_id)
        .fetch_one(&pool)
        .await
        .expect("count ledger rows");
        assert_eq!(ledger_count, 2);

        sqlx::query("DELETE FROM game_asha_world.world_snapshot WHERE world_id = $1")
            .bind(&world_id)
            .execute(&pool)
            .await
            .expect("remove isolated test world");
        let remaining: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM game_asha_world.world_event_ledger WHERE world_id = $1",
        )
        .bind(&world_id)
        .fetch_one(&pool)
        .await
        .expect("verify ledger cascade cleanup");
        assert_eq!(remaining, 0);
    }
}
