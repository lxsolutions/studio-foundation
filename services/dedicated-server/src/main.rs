use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_env("STUDIO_LOG").unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    // 127.0.0.1 by default, deliberately: never bind wildcard in development.
    let addr = std::env::var("STUDIO_DEDICATED_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:8081".into())
        .parse()?;

    let (_local, handle) = studio_dedicated_server::run_server(addr).await?;
    tokio::signal::ctrl_c().await?;
    tracing::info!("shutdown signal received");
    handle.abort();
    Ok(())
}
