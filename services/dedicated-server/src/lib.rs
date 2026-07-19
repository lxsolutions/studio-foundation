//! Dedicated server library: bindable server loop reused by main.rs and tests.

pub mod session;
pub mod transport;

use std::net::SocketAddr;

use session::Session;
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use transport::WsTransport;

/// Bind `addr` (use port 0 for tests) and serve WebSocket sessions until aborted.
/// Returns the actual bound address and the accept-loop task handle.
pub async fn run_server(addr: SocketAddr) -> anyhow::Result<(SocketAddr, JoinHandle<()>)> {
    let listener = TcpListener::bind(addr).await?;
    let local = listener.local_addr()?;
    tracing::info!(addr = %local, "dedicated-server listening (ws)");

    let handle = tokio::spawn(async move {
        loop {
            let (stream, peer) = match listener.accept().await {
                Ok(pair) => pair,
                Err(err) => {
                    tracing::warn!(error = %err, "accept failed");
                    continue;
                }
            };
            tokio::spawn(async move {
                match tokio_tungstenite::accept_async(stream).await {
                    Ok(ws) => {
                        tracing::debug!(%peer, "websocket accepted");
                        let summary = Session::new(WsTransport::new(ws), "studio-dedicated").run().await;
                        tracing::debug!(%peer, ?summary, "session finished");
                    }
                    Err(err) => tracing::debug!(%peer, error = %err, "ws upgrade failed"),
                }
            });
        }
    });

    Ok((local, handle))
}
