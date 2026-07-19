use studio_control_api::{build_router, connect_pool, AppState, Config, MIGRATOR};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_env("STUDIO_LOG").unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let config = Config::from_env();
    let pool = match &config.database_url {
        Some(url) => match connect_pool(url).await {
            Ok(pool) => {
                if let Err(err) = MIGRATOR.run(&pool).await {
                    tracing::error!(error = %err, "migrations failed; continuing (readyz will report)");
                } else {
                    tracing::info!("migrations up to date");
                }
                Some(pool)
            }
            Err(err) => {
                tracing::warn!(error = %err, "database unreachable at boot; running degraded");
                None
            }
        },
        None => {
            tracing::warn!("DATABASE_URL not set; running without persistence");
            None
        }
    };

    let app = build_router(AppState {
        pool,
        service: "studio-control-api",
        version: env!("CARGO_PKG_VERSION"),
    });

    let listener = tokio::net::TcpListener::bind(&config.addr).await?;
    tracing::info!(addr = %listener.local_addr()?, "control-api listening");
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
            tracing::info!("shutdown signal received");
        })
        .await?;
    Ok(())
}
