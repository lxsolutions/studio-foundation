//! Per-connection session loop, transport-agnostic.

use studio_protocol::{handshake_reply, Body, Envelope, ErrorCode, PROTOCOL_VERSION};
use tokio::time::{timeout, Duration};

use crate::transport::Transport;
use crate::SharedApplicationHandler;

const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Default, PartialEq)]
pub struct SessionSummary {
    pub handshake_ok: bool,
    pub messages_handled: u64,
}

pub struct Session<T: Transport> {
    transport: T,
    server_name: String,
    next_seq: u64,
    application: Option<SharedApplicationHandler>,
}

impl<T: Transport> Session<T> {
    pub fn new(transport: T, server_name: impl Into<String>) -> Self {
        Self {
            transport,
            server_name: server_name.into(),
            next_seq: 0,
            application: None,
        }
    }

    /// Attach a game-owned handler for opaque application requests.
    pub fn with_application_handler(
        mut self,
        application: Option<SharedApplicationHandler>,
    ) -> Self {
        self.application = application;
        self
    }

    fn envelope(&mut self, body: Body) -> Envelope {
        self.next_seq += 1;
        Envelope {
            v: PROTOCOL_VERSION,
            seq: self.next_seq,
            body,
        }
    }

    async fn send(&mut self, body: Body) -> bool {
        let envelope = self.envelope(body);
        self.transport.send(envelope).await.is_ok()
    }

    /// Drive the connection to completion. Never panics on peer input.
    pub async fn run(mut self) -> SessionSummary {
        let mut summary = SessionSummary::default();

        // Handshake: first message must be a valid hello, within the timeout.
        let first = match timeout(HANDSHAKE_TIMEOUT, self.transport.recv()).await {
            Ok(Some(Ok(envelope))) => envelope,
            Ok(Some(Err(err))) => {
                tracing::debug!(error = %err, "handshake decode failure");
                let _ = self
                    .send(Body::Error {
                        code: ErrorCode::Malformed,
                        message: "could not decode first message".into(),
                    })
                    .await;
                self.transport.close().await;
                return summary;
            }
            Ok(None) | Err(_) => {
                self.transport.close().await;
                return summary;
            }
        };

        let reply = handshake_reply(&first.body, &self.server_name);
        let accepted = matches!(reply, Body::HelloAck { .. });
        let _ = self.send(reply).await;
        if !accepted {
            self.transport.close().await;
            return summary;
        }
        summary.handshake_ok = true;
        tracing::info!(server = %self.server_name, "session established");

        while let Some(next) = self.transport.recv().await {
            let envelope = match next {
                Ok(envelope) => envelope,
                Err(err) => {
                    tracing::debug!(error = %err, "session decode failure");
                    let _ = self
                        .send(Body::Error {
                            code: ErrorCode::Malformed,
                            message: "could not decode message".into(),
                        })
                        .await;
                    continue;
                }
            };
            summary.messages_handled += 1;
            match envelope.body {
                Body::Ping { nonce } => {
                    if !self.send(Body::Pong { nonce }).await {
                        break;
                    }
                }
                Body::Echo { text } => {
                    if !self.send(Body::EchoAck { text }).await {
                        break;
                    }
                }
                Body::ApplicationRequest { payload_json } => {
                    let result = self.handle_application(&payload_json).await;
                    if !self.send(result).await {
                        break;
                    }
                }
                Body::Bye {} => {
                    let _ = self.send(Body::Bye {}).await;
                    break;
                }
                _ => {
                    let _ = self
                        .send(Body::Error {
                            code: ErrorCode::Unexpected,
                            message: "unsupported message in session".into(),
                        })
                        .await;
                }
            }
        }
        self.transport.close().await;
        summary
    }

    async fn handle_application(&mut self, payload_json: &str) -> Body {
        let Some(application) = &self.application else {
            return Body::Error {
                code: ErrorCode::Unexpected,
                message: "this server has no application handler".into(),
            };
        };
        let outcome = application.handle(payload_json).await;
        Body::ApplicationResult {
            accepted: outcome.accepted,
            summary: outcome.summary,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transport::{loopback_pair, Transport};
    use crate::{ApplicationFuture, ApplicationHandler, ApplicationOutcome};
    use std::sync::Arc;

    fn hello(protocol: u16) -> Envelope {
        Envelope {
            v: PROTOCOL_VERSION,
            seq: 1,
            body: Body::Hello {
                client: "test".into(),
                build: "0".into(),
                protocol,
            },
        }
    }

    struct AcceptingHandler;

    impl ApplicationHandler for AcceptingHandler {
        fn handle<'a>(&'a self, payload_json: &'a str) -> ApplicationFuture<'a> {
            Box::pin(async move {
                ApplicationOutcome {
                    accepted: true,
                    summary: format!("accepted {payload_json}"),
                }
            })
        }
    }

    #[tokio::test]
    async fn game_owned_application_handler_is_optional_and_schema_neutral() {
        let (server_side, mut client) = loopback_pair(16);
        let session = tokio::spawn(
            Session::new(server_side, "unit")
                .with_application_handler(Some(Arc::new(AcceptingHandler)))
                .run(),
        );

        client.send(hello(PROTOCOL_VERSION)).await.unwrap();
        let _ack = client.recv().await.unwrap().unwrap();
        client
            .send(Envelope {
                v: PROTOCOL_VERSION,
                seq: 2,
                body: Body::ApplicationRequest {
                    payload_json: r#"{"kind":"example.increment","value":1}"#.into(),
                },
            })
            .await
            .unwrap();
        let result = client.recv().await.unwrap().unwrap();
        assert!(matches!(
            result.body,
            Body::ApplicationResult {
                accepted: true,
                summary
            } if summary.contains("example.increment")
        ));
        client
            .send(Envelope {
                v: PROTOCOL_VERSION,
                seq: 3,
                body: Body::Bye {},
            })
            .await
            .unwrap();
        let _bye = client.recv().await.unwrap().unwrap();
        assert_eq!(session.await.unwrap().messages_handled, 2);
    }

    #[tokio::test]
    async fn handshake_ping_bye() {
        let (server_side, mut client) = loopback_pair(16);
        let session = tokio::spawn(Session::new(server_side, "unit").run());

        client.send(hello(PROTOCOL_VERSION)).await.unwrap();
        let ack = client.recv().await.unwrap().unwrap();
        assert!(
            matches!(ack.body, Body::HelloAck { protocol, .. } if protocol == PROTOCOL_VERSION)
        );

        client
            .send(Envelope {
                v: PROTOCOL_VERSION,
                seq: 2,
                body: Body::Ping { nonce: 99 },
            })
            .await
            .unwrap();
        let pong = client.recv().await.unwrap().unwrap();
        assert!(matches!(pong.body, Body::Pong { nonce: 99 }));

        client
            .send(Envelope {
                v: PROTOCOL_VERSION,
                seq: 3,
                body: Body::Bye {},
            })
            .await
            .unwrap();
        let bye = client.recv().await.unwrap().unwrap();
        assert!(matches!(bye.body, Body::Bye {}));

        let summary = session.await.unwrap();
        assert!(summary.handshake_ok);
        assert_eq!(summary.messages_handled, 2);
    }

    #[tokio::test]
    async fn rejects_version_mismatch() {
        let (server_side, mut client) = loopback_pair(16);
        let session = tokio::spawn(Session::new(server_side, "unit").run());

        client.send(hello(0)).await.unwrap();
        let reply = client.recv().await.unwrap().unwrap();
        assert!(matches!(
            reply.body,
            Body::Error {
                code: ErrorCode::VersionMismatch,
                ..
            }
        ));
        let summary = session.await.unwrap();
        assert!(!summary.handshake_ok);
    }

    #[tokio::test]
    async fn rejects_non_hello_first() {
        let (server_side, mut client) = loopback_pair(16);
        let session = tokio::spawn(Session::new(server_side, "unit").run());

        client
            .send(Envelope {
                v: PROTOCOL_VERSION,
                seq: 1,
                body: Body::Ping { nonce: 1 },
            })
            .await
            .unwrap();
        let reply = client.recv().await.unwrap().unwrap();
        assert!(matches!(
            reply.body,
            Body::Error {
                code: ErrorCode::Unexpected,
                ..
            }
        ));
        assert!(!session.await.unwrap().handshake_ok);
    }
}
