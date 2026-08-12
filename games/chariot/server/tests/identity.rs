//! Identity-keyed ghost submits over the wire: a presented Plaza token is
//! verified (stub verifier here) and the stored member key is the verified
//! stable identity, never the client claim.

use std::sync::Arc;

use chariot_server::application::ChariotApplication;
use chariot_server::identity::{member_key_for, StubPlazaVerifier};
use futures_util::{SinkExt, StreamExt};
use studio_protocol::{decode, encode, Body, Envelope, PROTOCOL_VERSION};
use tokio::net::TcpStream;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream};

async fn rpc(
    ws: &mut WebSocketStream<MaybeTlsStream<TcpStream>>,
    seq: u64,
    payload_json: &str,
) -> Body {
    ws.send(Message::Text(
        String::from_utf8(encode(&Envelope {
            v: PROTOCOL_VERSION,
            seq,
            body: Body::ApplicationRequest {
                payload_json: payload_json.into(),
            },
        }))
        .unwrap(),
    ))
    .await
    .unwrap();
    loop {
        match ws.next().await.unwrap().unwrap() {
            Message::Text(text) => return decode(text.as_bytes()).unwrap().body,
            other => panic!("unexpected frame: {other:?}"),
        }
    }
}

fn submit_payload(token: Option<&str>) -> String {
    let ticks: Vec<serde_json::Value> = (0..12)
        .map(|i| {
            serde_json::json!({
                "t": i as f64 * 200.0,
                "pos": i as f64 * 3.3,
                "lane": 2.0,
                "speed": 16.5,
            })
        })
        .collect();
    let mut payload = serde_json::json!({
        "kind": "ghost_submit",
        "member": "STABLE-1",
        "faction": "green",
        "handle": "Balios",
        "totalMs": 92_000,
        "distanceM": 1800.0,
        "ticks": ticks,
    });
    if let Some(token) = token {
        payload["token"] = serde_json::json!(token);
    }
    payload.to_string()
}

async fn ghost_by_id(
    ws: &mut WebSocketStream<MaybeTlsStream<TcpStream>>,
    seq: u64,
    id: &str,
) -> serde_json::Value {
    let fetched = rpc(ws, seq, &format!(r#"{{"kind":"ghost_fetch","id":"{id}"}}"#)).await;
    match fetched {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "fetch rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            body["ghost"].clone()
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }
}

async fn submit_id(
    ws: &mut WebSocketStream<MaybeTlsStream<TcpStream>>,
    seq: u64,
    payload: &str,
) -> String {
    match rpc(ws, seq, payload).await {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "submit rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            body["id"].as_str().unwrap().to_string()
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }
}

#[tokio::test]
async fn verified_token_keys_the_ghost_by_the_plaza_identity() {
    let application = Arc::new(
        ChariotApplication::in_memory().with_verifier(Arc::new(StubPlazaVerifier)),
    );
    let (addr, handle) =
        studio_dedicated_server::run_server_with("127.0.0.1:0".parse().unwrap(), Some(application))
            .await
            .expect("bind");
    let (mut ws, _) = tokio_tungstenite::connect_async(format!("ws://{addr}"))
        .await
        .expect("connect");
    ws.send(Message::Text(
        String::from_utf8(encode(&Envelope {
            v: PROTOCOL_VERSION,
            seq: 1,
            body: Body::Hello {
                client: "identity-test".into(),
                build: "0".into(),
                protocol: PROTOCOL_VERSION,
            },
        }))
        .unwrap(),
    ))
    .await
    .unwrap();
    let ack = loop {
        match ws.next().await.unwrap().unwrap() {
            Message::Text(text) => break decode(text.as_bytes()).unwrap(),
            _ => continue,
        }
    };
    assert!(matches!(ack.body, Body::HelloAck { .. }));

    // Verified: the plaza identity keys the run and owns the handle.
    let verified_id = submit_id(&mut ws, 2, &submit_payload(Some("stub:stable-key-9:Kyllaros"))).await;
    let ghost = ghost_by_id(&mut ws, 3, &verified_id).await;
    assert_eq!(ghost["member"], serde_json::json!(member_key_for("stable-key-9")));
    assert_ne!(ghost["member"], serde_json::json!("STABLE-1"));
    assert_eq!(ghost["handle"], "Kyllaros");
    assert_eq!(ghost["schema"], 1);

    // Unverified: no token, the claimed member stands.
    let claimed_id = submit_id(&mut ws, 4, &submit_payload(None)).await;
    let ghost = ghost_by_id(&mut ws, 5, &claimed_id).await;
    assert_eq!(ghost["member"], serde_json::json!("STABLE-1"));
    assert_eq!(ghost["handle"], "Balios");

    // Refused: a token that fails verification fails the submit outright.
    let rejected = rpc(&mut ws, 6, &submit_payload(Some("forged-token"))).await;
    assert!(matches!(
        rejected,
        Body::ApplicationResult {
            accepted: false,
            ..
        }
    ));
    handle.abort();
}
