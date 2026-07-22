//! Transport abstraction. The session loop is generic over [`Transport`], so the
//! same server logic runs over WebSocket today and WebTransport/QUIC datagram
//! transports later (see docs/networking/). Loopback exists for deterministic tests.

use futures_util::{SinkExt, StreamExt};
use studio_protocol::{decode, encode, Envelope, ProtocolError};
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::WebSocketStream;

#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error("transport closed")]
    Closed,
    #[error(transparent)]
    Protocol(#[from] ProtocolError),
    #[error("websocket: {0}")]
    Ws(#[from] tokio_tungstenite::tungstenite::Error),
}

#[allow(async_fn_in_trait)]
pub trait Transport: Send {
    async fn send(&mut self, envelope: Envelope) -> Result<(), TransportError>;
    /// `None` = peer closed cleanly.
    async fn recv(&mut self) -> Option<Result<Envelope, TransportError>>;
    async fn close(&mut self);
}

// ---------------------------------------------------------------- loopback

/// In-memory transport pair for tests and deterministic replay harnesses.
pub struct LoopbackTransport {
    tx: mpsc::Sender<Envelope>,
    rx: mpsc::Receiver<Envelope>,
}

pub fn loopback_pair(buffer: usize) -> (LoopbackTransport, LoopbackTransport) {
    let (a_tx, a_rx) = mpsc::channel(buffer);
    let (b_tx, b_rx) = mpsc::channel(buffer);
    (
        LoopbackTransport { tx: a_tx, rx: b_rx },
        LoopbackTransport { tx: b_tx, rx: a_rx },
    )
}

impl Transport for LoopbackTransport {
    async fn send(&mut self, envelope: Envelope) -> Result<(), TransportError> {
        self.tx
            .send(envelope)
            .await
            .map_err(|_| TransportError::Closed)
    }

    async fn recv(&mut self) -> Option<Result<Envelope, TransportError>> {
        self.rx.recv().await.map(Ok)
    }

    async fn close(&mut self) {
        self.rx.close();
    }
}

// ---------------------------------------------------------------- websocket

/// Server-side WebSocket transport (browser-compatible baseline).
pub struct WsTransport {
    inner: WebSocketStream<TcpStream>,
}

impl WsTransport {
    pub fn new(inner: WebSocketStream<TcpStream>) -> Self {
        Self { inner }
    }
}

impl Transport for WsTransport {
    async fn send(&mut self, envelope: Envelope) -> Result<(), TransportError> {
        let text = String::from_utf8(encode(&envelope)).expect("json is utf8");
        self.inner.send(Message::Text(text)).await?;
        Ok(())
    }

    async fn recv(&mut self) -> Option<Result<Envelope, TransportError>> {
        loop {
            match self.inner.next().await? {
                Ok(Message::Text(text)) => {
                    return Some(decode(text.as_bytes()).map_err(TransportError::from))
                }
                Ok(Message::Binary(bytes)) => {
                    return Some(decode(&bytes).map_err(TransportError::from))
                }
                Ok(Message::Ping(_)) | Ok(Message::Pong(_)) | Ok(Message::Frame(_)) => continue,
                Ok(Message::Close(_)) => return None,
                Err(err) => return Some(Err(err.into())),
            }
        }
    }

    async fn close(&mut self) {
        let _ = self.inner.close(None).await;
    }
}
