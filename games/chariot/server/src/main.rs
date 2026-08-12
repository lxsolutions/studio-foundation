//! Game server binary for chariot. Reuses the studio dedicated
//! server foundation; the game-owned faction surface (membership, race
//! points, season standings) hangs off the application-payload hook.

use std::sync::Arc;

use chariot_server::application::ChariotApplication;
use tracing_subscriber::EnvFilter;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

async fn migrate_game_schema(database_url: &str) -> anyhow::Result<sqlx::PgPool> {
    let pool = sqlx::PgPool::connect(database_url).await?;
    // Keep each generated game's SQLx history inside its owned schema. The
    // platform and other games may all use migration version 0001 independently.
    sqlx::query("CREATE SCHEMA IF NOT EXISTS game_chariot")
        .execute(&pool)
        .await?;
    let mut connection = pool.acquire().await?;
    sqlx::query("SET search_path TO game_chariot")
        .execute(&mut *connection)
        .await?;
    MIGRATOR.run(&mut *connection).await?;
    Ok(pool)
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_env("STUDIO_LOG").unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    // Faction state persists in PostgreSQL when the platform database is
    // wired; without it the server still answers from memory (dev, tests).
    let application = match std::env::var("DATABASE_URL") {
        Ok(database_url) => {
            let pool = migrate_game_schema(&database_url).await?;
            tracing::info!(game = "chariot", "game migrations up to date");
            ChariotApplication::postgres(pool)
        }
        Err(_) => ChariotApplication::in_memory(),
    };
    let addr = std::env::var("STUDIO_DEDICATED_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:8081".into())
        .parse()?;
    tracing::info!(game = "chariot", "starting game server");
    let (_local, handle) =
        studio_dedicated_server::run_server_with(addr, Some(Arc::new(application))).await?;
    tokio::signal::ctrl_c().await?;
    handle.abort();
    Ok(())
}
