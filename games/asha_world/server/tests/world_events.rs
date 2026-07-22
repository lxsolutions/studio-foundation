//! Vertical-slice acceptance: a client submits canonical world events over the
//! wire and the shared world-sim settles them (ADR 0007). Proves the loop:
//! extract -> (bounded) bank -> factory -> territory, idempotently.

use futures_util::{SinkExt, StreamExt};
use studio_protocol::{decode, encode, Body, Envelope, PROTOCOL_VERSION};
use studio_world_sim::{FactionId, SectorId, WorldEvent};
use tokio_tungstenite::tungstenite::Message;
use uuid::Uuid;

fn envelope(seq: u64, body: Body) -> Message {
    Message::Text(
        String::from_utf8(encode(&Envelope {
            v: PROTOCOL_VERSION,
            seq,
            body,
        }))
        .unwrap(),
    )
}

async fn next_envelope(
    ws: &mut (impl StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin),
) -> Envelope {
    loop {
        match ws.next().await.unwrap().unwrap() {
            Message::Text(text) => return decode(text.as_bytes()).unwrap(),
            _ => continue,
        }
    }
}

#[tokio::test]
async fn world_events_settle_over_the_wire() {
    let world = std::sync::Arc::new(tokio::sync::Mutex::new(
        studio_world_sim::WorldSim::default(),
    ));
    let (addr, handle) = studio_dedicated_server::run_server_with(
        "127.0.0.1:0".parse().unwrap(),
        Some(world.clone()),
    )
    .await
    .expect("bind");
    let (mut ws, _) = tokio_tungstenite::connect_async(format!("ws://{addr}"))
        .await
        .expect("connect");

    // Handshake.
    ws.send(envelope(
        1,
        Body::Hello {
            client: "world-test".into(),
            build: "0".into(),
            protocol: PROTOCOL_VERSION,
        },
    ))
    .await
    .unwrap();
    assert!(matches!(
        next_envelope(&mut ws).await.body,
        Body::HelloAck { .. }
    ));

    let faction = FactionId(Uuid::from_u128(1));
    let sector = SectorId(Uuid::from_u128(2));

    // 1. ResourceExtracted settles (bounded).
    let extract = WorldEvent::ResourceExtracted {
        faction,
        sector,
        resource: studio_world_sim::state::Resource::RawOre,
        units: 100,
        idempotency_key: Uuid::from_u128(10),
    };
    ws.send(envelope(
        2,
        Body::WorldEventSubmit {
            event_json: serde_json::to_string(&extract).unwrap(),
        },
    ))
    .await
    .unwrap();
    match next_envelope(&mut ws).await.body {
        Body::WorldEventResult { applied, summary } => {
            assert!(applied, "extract should apply: {summary}");
        }
        other => panic!("expected WorldEventResult, got {other:?}"),
    }

    // 2. Replay with the same idempotency key is a no-op.
    ws.send(envelope(
        3,
        Body::WorldEventSubmit {
            event_json: serde_json::to_string(&extract).unwrap(),
        },
    ))
    .await
    .unwrap();
    match next_envelope(&mut ws).await.body {
        Body::WorldEventResult { applied, summary } => {
            assert!(!applied, "replay should be idempotent no-op: {summary}");
        }
        other => panic!("expected WorldEventResult, got {other:?}"),
    }

    // 3. TerritoryChanged flips sector control.
    let flip = WorldEvent::TerritoryChanged {
        sector,
        new_controller: faction,
        idempotency_key: Uuid::from_u128(11),
    };
    ws.send(envelope(
        4,
        Body::WorldEventSubmit {
            event_json: serde_json::to_string(&flip).unwrap(),
        },
    ))
    .await
    .unwrap();
    match next_envelope(&mut ws).await.body {
        Body::WorldEventResult { applied, summary } => {
            assert!(applied, "territory flip should apply: {summary}");
        }
        other => panic!("expected WorldEventResult, got {other:?}"),
    }

    // Server-side world reflects the settlements.
    let sim = world.lock().await;
    assert_eq!(sim.state.sectors[&sector].controller, Some(faction));
    assert_eq!(
        sim.state
            .stockpile(faction, studio_world_sim::state::Resource::RawOre),
        100
    );
    handle.abort();
}
