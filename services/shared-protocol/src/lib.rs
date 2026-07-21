//! Studio wire protocol v1.
//!
//! Canonical spec: `shared/protocol/PROTOCOL.md`. The GDScript mirror is
//! `shared/godot-addons/studio_core/net/protocol.gd`. Any change here MUST:
//! 1) bump [`PROTOCOL_VERSION`] or stay wire-compatible,
//! 2) update the golden fixtures in `shared/protocol/fixtures/`,
//! 3) update the GDScript mirror (CI runs both sides against the fixtures).

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Bump only with an ADR note; the server rejects mismatched clients.
pub const PROTOCOL_VERSION: u16 = 1;

/// Transport-agnostic message envelope. `seq` is per-sender, monotonically
/// increasing from 1. Timestamps are deliberately absent (determinism/replay).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Envelope {
    pub v: u16,
    pub seq: u64,
    #[serde(flatten)]
    pub body: Body,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Body {
    /// First client message on any transport.
    Hello {
        client: String,
        build: String,
        protocol: u16,
    },
    /// Server accepts; `session` identifies this connection server-side.
    HelloAck {
        server: String,
        protocol: u16,
        session: Uuid,
    },
    Ping {
        nonce: u64,
    },
    Pong {
        nonce: u64,
    },
    /// Bootstrap round-trip demo (no gameplay meaning).
    Echo {
        text: String,
    },
    EchoAck {
        text: String,
    },
    /// Client submits one canonical world event (ADR 0007) for settlement.
    /// `event_json` is the serialized `WorldEvent` (world-sim crate owns the schema);
    /// the protocol stays agnostic so event types evolve without a wire bump.
    WorldEventSubmit {
        event_json: String,
    },
    /// Server's settlement outcome for a submitted world event.
    WorldEventResult {
        applied: bool,
        summary: String,
    },
    /// Graceful close intent from either side.
    Bye {},
    Error {
        code: ErrorCode,
        message: String,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    VersionMismatch,
    Malformed,
    Unexpected,
    Internal,
}

#[derive(Debug, thiserror::Error)]
pub enum ProtocolError {
    #[error("malformed message: {0}")]
    Malformed(#[from] serde_json::Error),
    #[error("protocol version {got} not supported (want {want})")]
    Version { got: u16, want: u16 },
}

pub fn encode(envelope: &Envelope) -> Vec<u8> {
    serde_json::to_vec(envelope).expect("protocol types are always serializable")
}

pub fn decode(bytes: &[u8]) -> Result<Envelope, ProtocolError> {
    let envelope: Envelope = serde_json::from_slice(bytes)?;
    if envelope.v != PROTOCOL_VERSION {
        return Err(ProtocolError::Version {
            got: envelope.v,
            want: PROTOCOL_VERSION,
        });
    }
    Ok(envelope)
}

/// Validate a client Hello, producing either the ack body or the error to send.
pub fn handshake_reply(body: &Body, server_name: &str) -> Body {
    match body {
        Body::Hello { protocol, .. } if *protocol == PROTOCOL_VERSION => Body::HelloAck {
            server: server_name.to_string(),
            protocol: PROTOCOL_VERSION,
            session: Uuid::new_v4(),
        },
        Body::Hello { protocol, .. } => Body::Error {
            code: ErrorCode::VersionMismatch,
            message: format!("client protocol {protocol}, server {PROTOCOL_VERSION}"),
        },
        _ => Body::Error {
            code: ErrorCode::Unexpected,
            message: "first message must be hello".into(),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn fixtures_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../shared/protocol/fixtures")
    }

    #[test]
    fn roundtrip() {
        let env = Envelope {
            v: PROTOCOL_VERSION,
            seq: 7,
            body: Body::Echo { text: "hi".into() },
        };
        let decoded = decode(&encode(&env)).unwrap();
        assert_eq!(env, decoded);
    }

    #[test]
    fn rejects_wrong_version() {
        let bytes = br#"{"v":999,"seq":1,"type":"ping","nonce":1}"#;
        assert!(matches!(
            decode(bytes),
            Err(ProtocolError::Version { got: 999, .. })
        ));
    }

    #[test]
    fn rejects_malformed() {
        assert!(matches!(
            decode(b"{nope"),
            Err(ProtocolError::Malformed(_))
        ));
    }

    /// Every golden fixture must decode, re-encode, and match as JSON values.
    /// This is the cross-language contract shared with the GDScript suite.
    #[test]
    fn golden_fixtures() {
        let dir = fixtures_dir();
        let mut checked = 0;
        for entry in std::fs::read_dir(&dir).expect("fixtures dir exists") {
            let path = entry.unwrap().path();
            if path.extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            let raw = std::fs::read(&path).unwrap();
            let expect_err = path
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("invalid_");
            match decode(&raw) {
                Ok(envelope) => {
                    assert!(!expect_err, "{path:?} decoded but is an invalid_ fixture");
                    let reencoded: serde_json::Value =
                        serde_json::from_slice(&encode(&envelope)).unwrap();
                    let original: serde_json::Value = serde_json::from_slice(&raw).unwrap();
                    assert_eq!(reencoded, original, "{path:?} not canonical");
                }
                Err(_) => assert!(expect_err, "{path:?} failed to decode"),
            }
            checked += 1;
        }
        assert!(checked >= 5, "expected fixtures in {dir:?}, found {checked}");
    }

    #[test]
    fn handshake_accepts_and_rejects() {
        let good = Body::Hello {
            client: "godot".into(),
            build: "dev".into(),
            protocol: PROTOCOL_VERSION,
        };
        assert!(matches!(
            handshake_reply(&good, "test"),
            Body::HelloAck { .. }
        ));
        let bad = Body::Hello {
            client: "godot".into(),
            build: "dev".into(),
            protocol: 0,
        };
        assert!(matches!(
            handshake_reply(&bad, "test"),
            Body::Error {
                code: ErrorCode::VersionMismatch,
                ..
            }
        ));
    }
}
