//! Ghost surface over the wire: the game server answers ghost-submit and
//! ghost-fetch application payloads through the studio handshake.

use std::sync::Arc;

use chariot_server::application::ChariotApplication;
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

#[tokio::test]
async fn ghost_submit_and_fetch_round_trip() {
    let application = Arc::new(ChariotApplication::in_memory());
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
                client: "ghost-test".into(),
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
    let submit = serde_json::json!({
        "kind": "ghost_submit",
        "member": "STABLE-1",
        "faction": "green",
        "handle": "Balios",
        "totalMs": 92_000,
        "distanceM": 1800.0,
        "ticks": ticks,
    })
    .to_string();
    let submitted = rpc(&mut ws, 2, &submit).await;
    let id = match submitted {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "submit rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            body["id"].as_str().unwrap().to_string()
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    };

    let fetched = rpc(
        &mut ws,
        3,
        &format!(r#"{{"kind":"ghost_fetch","id":"{id}"}}"#),
    )
    .await;
    match fetched {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "fetch rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            let ghost = &body["ghost"];
            assert_eq!(ghost["handle"], "Balios");
            assert_eq!(ghost["faction"], "green");
            assert_eq!(ghost["totalMs"], 92_000);
            assert_eq!(ghost["ticks"].as_array().unwrap().len(), 12);
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }

    let rejected = rpc(&mut ws, 4, r#"{"kind":"ghost_fetch","id":"g-42"}"#).await;
    assert!(matches!(
        rejected,
        Body::ApplicationResult {
            accepted: false,
            ..
        }
    ));
    handle.abort();
}
