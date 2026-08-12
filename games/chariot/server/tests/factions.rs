//! Faction surface over the wire: the game server answers join, race-record,
//! and standings-fetch application payloads through the studio handshake.

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
async fn faction_join_record_and_standings_round_trip() {
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
                client: "faction-test".into(),
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

    let joined = rpc(
        &mut ws,
        2,
        r#"{"kind":"faction_join","member":"STABLE-1","faction":"green"}"#,
    )
    .await;
    assert!(
        matches!(joined, Body::ApplicationResult { accepted: true, .. }),
        "join must be accepted: {joined:?}"
    );

    let recorded = rpc(
        &mut ws,
        3,
        r#"{"kind":"race_record","season":"s1","raceId":"r-1","results":[
            {"faction":"green","place":1},
            {"faction":"blue","place":2},
            {"faction":"red","place":3}
        ]}"#,
    )
    .await;
    match recorded {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "record rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            assert_eq!(body["tally"]["green"], 9);
            assert_eq!(body["tally"]["blue"], 6);
            assert_eq!(body["tally"]["red"], 4);
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }

    let fetched = rpc(&mut ws, 4, r#"{"kind":"standings_fetch","season":"s1"}"#).await;
    match fetched {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "standings rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            let rows = body["standings"].as_array().unwrap();
            assert_eq!(rows.len(), 4, "the season table always holds all four");
            assert_eq!(rows[0], serde_json::json!({"faction": "green", "points": 9}));
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }

    let rejected = rpc(
        &mut ws,
        5,
        r#"{"kind":"faction_join","member":"STABLE-2","faction":"gold"}"#,
    )
    .await;
    assert!(matches!(
        rejected,
        Body::ApplicationResult {
            accepted: false,
            ..
        }
    ));
    handle.abort();
}
