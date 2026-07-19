//! Real client <-> server connectivity over WebSocket on 127.0.0.1 (ephemeral port).
//! This is the loopback demonstration required by the bootstrap acceptance criteria.

use futures_util::{SinkExt, StreamExt};
use studio_protocol::{decode, encode, Body, Envelope, PROTOCOL_VERSION};
use tokio_tungstenite::tungstenite::Message;

fn text(envelope: &Envelope) -> Message {
    Message::Text(String::from_utf8(encode(envelope)).unwrap())
}

async fn next_envelope<S>(ws: &mut S) -> Envelope
where
    S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
{
    loop {
        match ws.next().await.expect("stream open").expect("frame ok") {
            Message::Text(t) => return decode(t.as_bytes()).expect("valid envelope"),
            Message::Binary(b) => return decode(&b).expect("valid envelope"),
            _ => continue,
        }
    }
}

#[tokio::test]
async fn websocket_handshake_echo_bye() {
    // Bind 127.0.0.1:0 — never a wildcard, never a fixed port (port-squatter safe).
    let (addr, server) = studio_dedicated_server::run_server("127.0.0.1:0".parse().unwrap())
        .await
        .expect("server binds");

    let (mut ws, _) = tokio_tungstenite::connect_async(format!("ws://{addr}"))
        .await
        .expect("client connects");

    ws.send(text(&Envelope {
        v: PROTOCOL_VERSION,
        seq: 1,
        body: Body::Hello {
            client: "integration-test".into(),
            build: env!("CARGO_PKG_VERSION").into(),
            protocol: PROTOCOL_VERSION,
        },
    }))
    .await
    .unwrap();

    let ack = next_envelope(&mut ws).await;
    let session = match ack.body {
        Body::HelloAck {
            protocol, session, ..
        } => {
            assert_eq!(protocol, PROTOCOL_VERSION);
            session
        }
        other => panic!("expected hello_ack, got {other:?}"),
    };
    assert!(!session.is_nil());

    ws.send(text(&Envelope {
        v: PROTOCOL_VERSION,
        seq: 2,
        body: Body::Echo {
            text: "round trip".into(),
        },
    }))
    .await
    .unwrap();
    let echo = next_envelope(&mut ws).await;
    assert!(matches!(echo.body, Body::EchoAck { text } if text == "round trip"));

    ws.send(text(&Envelope {
        v: PROTOCOL_VERSION,
        seq: 3,
        body: Body::Bye {},
    }))
    .await
    .unwrap();
    let bye = next_envelope(&mut ws).await;
    assert!(matches!(bye.body, Body::Bye {}));

    server.abort();
}

#[tokio::test]
async fn websocket_rejects_stale_protocol() {
    let (addr, server) = studio_dedicated_server::run_server("127.0.0.1:0".parse().unwrap())
        .await
        .unwrap();
    let (mut ws, _) = tokio_tungstenite::connect_async(format!("ws://{addr}"))
        .await
        .unwrap();

    ws.send(text(&Envelope {
        v: PROTOCOL_VERSION,
        seq: 1,
        body: Body::Hello {
            client: "old-client".into(),
            build: "0.0.0".into(),
            protocol: 0,
        },
    }))
    .await
    .unwrap();

    let reply = next_envelope(&mut ws).await;
    assert!(matches!(
        reply.body,
        Body::Error {
            code: studio_protocol::ErrorCode::VersionMismatch,
            ..
        }
    ));
    server.abort();
}
