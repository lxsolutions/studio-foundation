//! Game server binary for studio_game_template. Reuses the studio dedicated
//! server foundation; game-specific simulation systems land here later —
//! the template ships connectivity only (no mechanics, by design).

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
    tracing::info!(game = "studio_game_template", "starting game server");
    let (_local, handle) = studio_dedicated_server::run_server(addr).await?;
    tokio::signal::ctrl_c().await?;
    handle.abort();
    Ok(())
}
