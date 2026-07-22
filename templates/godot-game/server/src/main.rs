//! Game server binary for studio_game_template. Reuses the studio dedicated
//! server foundation; game-specific simulation systems land here later —
//! the template ships connectivity only (no mechanics, by design).

use tracing_subscriber::EnvFilter;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

async fn migrate_game_schema(database_url: &str) -> anyhow::Result<()> {
    let pool = sqlx::PgPool::connect(database_url).await?;
    // Keep each generated game's SQLx history inside its owned schema. The
    // platform and other games may all use migration version 0001 independently.
    sqlx::query("CREATE SCHEMA IF NOT EXISTS game_studio_game_template")
        .execute(&pool)
        .await?;
    let mut connection = pool.acquire().await?;
    sqlx::query("SET search_path TO game_studio_game_template")
        .execute(&mut *connection)
        .await?;
    MIGRATOR.run(&mut *connection).await?;
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_env("STUDIO_LOG").unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    if let Ok(database_url) = std::env::var("DATABASE_URL") {
        migrate_game_schema(&database_url).await?;
        tracing::info!(game = "studio_game_template", "game migrations up to date");
    }
    let addr = std::env::var("STUDIO_DEDICATED_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:8081".into())
        .parse()?;
    tracing::info!(game = "studio_game_template", "starting game server");
    let (_local, handle) = studio_dedicated_server::run_server(addr).await?;
    tokio::signal::ctrl_c().await?;
    handle.abort();
    Ok(())
}
