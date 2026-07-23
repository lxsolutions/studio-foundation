//! Dedicated server library: bindable transport and neutral application hooks.

pub mod session;
pub mod transport;

use std::future::Future;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::Arc;

use session::Session;
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use transport::WsTransport;

/// Neutral result returned by a game-owned application handler.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApplicationOutcome {
    pub accepted: bool,
    pub summary: String,
}

pub type ApplicationFuture<'a> = Pin<Box<dyn Future<Output = ApplicationOutcome> + Send + 'a>>;

/// Optional extension point for game-owned payloads.
///
/// Foundation does not define the payload schema or assume any gameplay concept.
pub trait ApplicationHandler: Send + Sync {
    fn handle<'a>(&'a self, payload_json: &'a str) -> ApplicationFuture<'a>;
}

pub type SharedApplicationHandler = Arc<dyn ApplicationHandler>;

/// Bind addr (use port 0 for tests) and serve WebSocket sessions until aborted.
pub async fn run_server(addr: SocketAddr) -> anyhow::Result<(SocketAddr, JoinHandle<()>)> {
    run_server_with(addr, None).await
}

/// Serve with an optional game-owned application handler.
pub async fn run_server_with(
    addr: SocketAddr,
    application: Option<SharedApplicationHandler>,
) -> anyhow::Result<(SocketAddr, JoinHandle<()>)> {
    let listener = TcpListener::bind(addr).await?;
    let local = listener.local_addr()?;
    tracing::info!(
        addr = %local,
        application = application.is_some(),
        "dedicated-server listening (ws)"
    );

    let handle = tokio::spawn(async move {
        loop {
            let (stream, peer) = match listener.accept().await {
                Ok(pair) => pair,
                Err(err) => {
                    tracing::warn!(error = %err, "accept failed");
                    continue;
                }
            };
            let application = application.clone();
            tokio::spawn(async move {
                match tokio_tungstenite::accept_async(stream).await {
                    Ok(ws) => {
                        tracing::debug!(%peer, "websocket accepted");
                        let summary = Session::new(WsTransport::new(ws), "studio-dedicated")
                            .with_application_handler(application)
                            .run()
                            .await;
                        tracing::debug!(%peer, ?summary, "session finished");
                    }
                    Err(err) => tracing::debug!(%peer, error = %err, "ws upgrade failed"),
                }
            });
        }
    });

    Ok((local, handle))
}
