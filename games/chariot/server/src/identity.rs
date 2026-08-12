//! Plaza identity for ghost submits: verify token -> stable member key.
//!
//! The convention is the Minerals satellite's (PlatosPlaza
//! `siege/plaza-bridge/server.js`, documented in `siege/PLAZA_INTEGRATION.md`):
//! the client presents its Plaza bearer token; the server verifies it against
//! the Plaza's `/api/siege/loadout`, which answers the stable Plaza `key` and
//! the authoritative `handle`; the verified key — never the raw token — is
//! hashed into the game's member namespace, so token renewal cannot rekey a
//! stable's ghosts and the raw stable key is never written to our tables.
//!
//! The verifier is a trait so the application handler never cares how a token
//! is proven. The binary wires [`HttpPlazaVerifier`] from `PLAZA_BASE_URL`
//! (no default, no secrets in the tree: unset means no verifier, and submits
//! fall back to the client-claimed member — the pre-bridge behavior). Tests
//! use [`StubPlazaVerifier`]. What remains for a live deploy: run the server
//! with `PLAZA_BASE_URL` pointed at the Plaza (e.g. `https://platosplaza.com`,
//! `http://127.0.0.1:8091` in dev, mirroring Minerals' `ARENA_API`) and
//! confirm the Plaza accepts the stables handoff token (`?t=…` / `arb_token`)
//! as the bearer — the same session Minerals spends at that endpoint.

use std::future::Future;
use std::pin::Pin;

use sha2::{Digest, Sha256};

/// The identity a verifier vouches for: the member key our tables store and
/// the Plaza-authoritative handle (empty when the verifier does not know one).
pub struct VerifiedIdentity {
    pub member_key: String,
    pub handle: String,
}

pub type VerifyFuture<'a> = Pin<Box<dyn Future<Output = Result<VerifiedIdentity, String>> + Send + 'a>>;

/// How a presented token becomes a verified identity. Implementations must be
/// cheap to clone behind an Arc and never log the token itself.
pub trait PlazaVerifier: Send + Sync {
    fn verify<'a>(&'a self, token: &'a str) -> VerifyFuture<'a>;
}

/// Hash a verified stable key into the chariot member namespace — the
/// Minerals `accountKey` convention (sha256 hex, truncated, prefixed) so a
/// stored row can never be traced back to the raw Plaza key.
pub fn member_key_for(stable_key: &str) -> String {
    let digest = Sha256::digest(stable_key.trim().as_bytes());
    let hex: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    format!("plaza:{}", &hex[..32])
}

/// The live verifier: one bounded GET against the Plaza, bearer token in the
/// `Authorization` header, four-second budget like the Minerals bridge.
pub struct HttpPlazaVerifier {
    base_url: String,
    client: reqwest::Client,
}

impl HttpPlazaVerifier {
    pub fn new(base_url: impl Into<String>) -> Self {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(4))
            .build()
            .expect("reqwest client builds with rustls");
        Self {
            base_url: base_url.into().trim_end_matches('/').to_string(),
            client,
        }
    }
}

impl PlazaVerifier for HttpPlazaVerifier {
    fn verify<'a>(&'a self, token: &'a str) -> VerifyFuture<'a> {
        Box::pin(async move {
            let response = self
                .client
                .get(format!("{}/api/siege/loadout", self.base_url))
                .bearer_auth(token)
                .send()
                .await
                .map_err(|err| format!("the plaza is unreachable: {err}"))?;
            if !response.status().is_success() {
                return Err(format!("the plaza refused the token ({})", response.status()));
            }
            let body: serde_json::Value = response
                .json()
                .await
                .map_err(|err| format!("the plaza answered unreadably: {err}"))?;
            let stable_key = body
                .get("key")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("")
                .trim();
            if stable_key.is_empty() {
                return Err("the plaza answered without a stable key".to_string());
            }
            let handle = body
                .get("handle")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("")
                .trim()
                .to_string();
            Ok(VerifiedIdentity {
                member_key: member_key_for(stable_key),
                handle,
            })
        })
    }
}

/// Test and dev double, never wired by the binary: a token of the shape
/// `stub:<stable-key>[:<handle>]` verifies into that stable's identity;
/// anything else is refused the way a Plaza 401 would be.
pub struct StubPlazaVerifier;

impl PlazaVerifier for StubPlazaVerifier {
    fn verify<'a>(&'a self, token: &'a str) -> VerifyFuture<'a> {
        let token = token.to_string();
        Box::pin(async move {
            let Some(rest) = token.strip_prefix("stub:") else {
                return Err("the plaza refused the token (stub)".to_string());
            };
            let mut parts = rest.splitn(2, ':');
            let stable_key = parts.next().unwrap_or("");
            if stable_key.is_empty() {
                return Err("a stub token names no stable key".to_string());
            }
            Ok(VerifiedIdentity {
                member_key: member_key_for(stable_key),
                handle: parts.next().unwrap_or("").to_string(),
            })
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn member_keys_are_hashed_into_the_plaza_namespace() {
        let key = member_key_for("stable-key-1");
        assert!(key.starts_with("plaza:"), "the namespace prefix marks a verified key");
        assert_eq!(key.len(), "plaza:".len() + 32, "sha256 hex truncated to 32");
        assert!(!key.contains("stable-key-1"), "the raw stable key never appears");
        assert_eq!(key, member_key_for("  stable-key-1  "), "padding is irrelevant");
        assert_ne!(key, member_key_for("stable-key-2"), "distinct stables key distinctly");
    }

    #[tokio::test]
    async fn stub_verifies_and_refuses() {
        let verifier = StubPlazaVerifier;
        let verified = verifier.verify("stub:stable-key-1:Xanthos").await.unwrap();
        assert_eq!(verified.member_key, member_key_for("stable-key-1"));
        assert_eq!(verified.handle, "Xanthos");
        let handleless = verifier.verify("stub:stable-key-1").await.unwrap();
        assert!(handleless.handle.is_empty());
        assert!(verifier.verify("not-a-stub-token").await.is_err());
        assert!(verifier.verify("stub:").await.is_err());
    }
}
