//! Generated-game acceptance: the game's server boots and answers the studio
//! handshake on an ephemeral 127.0.0.1 port.

use futures_util::{SinkExt, StreamExt};
use studio_protocol::{decode, encode, Body, Envelope, PROTOCOL_VERSION};
use tokio_tungstenite::tungstenite::Message;

#[tokio::test]
async fn game_server_boots_and_shakes_hands() {
    let (addr, handle) = studio_dedicated_server::run_server("127.0.0.1:0".parse().unwrap())
        .await
        .expect("bind");
    let (mut ws, _) = tokio_tungstenite::connect_async(format!("ws://{addr}"))
        .await
        .expect("connect");
    let hello = Envelope {
        v: PROTOCOL_VERSION,
        seq: 1,
        body: Body::Hello {
            client: "game-boot-test".into(),
            build: "0".into(),
            protocol: PROTOCOL_VERSION,
        },
    };
    ws.send(Message::Text(String::from_utf8(encode(&hello)).unwrap()))
        .await
        .unwrap();
    let reply = loop {
        match ws.next().await.unwrap().unwrap() {
            Message::Text(text) => break decode(text.as_bytes()).unwrap(),
            _ => continue,
        }
    };
    assert!(matches!(reply.body, Body::HelloAck { .. }));
    handle.abort();
}
