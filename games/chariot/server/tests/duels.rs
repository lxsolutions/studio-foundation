//! Ghost-duel surface over the wire: a settled duel records the derived
//! winner's stake through the studio handshake, and the season standings fold
//! duel points in with race points.

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

fn submit_payload(faction: &str, total_ms: u32) -> String {
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
    serde_json::json!({
        "kind": "ghost_submit",
        "member": "STABLE-1",
        "faction": faction,
        "handle": "Xanthos",
        "totalMs": total_ms,
        "distanceM": 1800.0,
        "ticks": ticks,
    })
    .to_string()
}

async fn submit_run(
    ws: &mut WebSocketStream<MaybeTlsStream<TcpStream>>,
    seq: u64,
    faction: &str,
    total_ms: u32,
) -> String {
    match rpc(ws, seq, &submit_payload(faction, total_ms)).await {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "submit rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            body["id"].as_str().unwrap().to_string()
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }
}

#[tokio::test]
async fn duel_record_round_trip_and_standings() {
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
                client: "duel-test".into(),
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

    let ghost_id = submit_run(&mut ws, 2, "green", 92_000).await;
    let run_id = submit_run(&mut ws, 3, "blue", 91_500).await;

    let settled = rpc(
        &mut ws,
        4,
        &serde_json::json!({
            "kind": "duel_record",
            "ghostId": ghost_id,
            "runId": run_id,
            "winner": "me",
            "faction": "blue",
            "marginMs": 250,
        })
        .to_string(),
    )
    .await;
    match settled {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "settle rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            assert_eq!(body["kind"], "duel.record");
            assert_eq!(body["outcome"], "me");
            assert_eq!(body["marginMs"], 500, "the server derives the gap");
            assert_eq!(body["faction"], "blue");
            assert_eq!(body["points"], 5, "the duel stake");
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }

    // Duel points and race points are one season tally.
    let recorded = rpc(
        &mut ws,
        5,
        r#"{"kind":"race_record","season":"s1","raceId":"r-1","results":[
            {"faction":"green","place":1},
            {"faction":"blue","place":4}
        ]}"#,
    )
    .await;
    assert!(matches!(recorded, Body::ApplicationResult { accepted: true, .. }));

    let fetched = rpc(&mut ws, 6, r#"{"kind":"standings_fetch","season":"s1"}"#).await;
    match fetched {
        Body::ApplicationResult { accepted, summary } => {
            assert!(accepted, "standings rejected: {summary}");
            let body: serde_json::Value = serde_json::from_str(&summary).unwrap();
            let rows = body["standings"].as_array().unwrap();
            assert_eq!(rows.len(), 4, "the season table always holds all four");
            assert_eq!(
                rows[0],
                serde_json::json!({"faction": "green", "points": 9}),
                "the race win"
            );
            assert_eq!(
                rows[1],
                serde_json::json!({"faction": "blue", "points": 7}),
                "fourth home (2) plus the duel stake (5)"
            );
        }
        other => panic!("expected ApplicationResult, got {other:?}"),
    }

    let rejected = rpc(
        &mut ws,
        7,
        &format!(r#"{{"kind":"duel_record","ghostId":"g-99","runId":"{run_id}","winner":"me","faction":"blue","marginMs":1}}"#),
    )
    .await;
    assert!(
        matches!(rejected, Body::ApplicationResult { accepted: false, .. }),
        "an unknown ghost refuses the record"
    );
    handle.abort();
}
