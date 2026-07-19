//! Deliberately tiny HTTP/1.1 client for localhost dev endpoints only.
//! Avoids pulling a TLS-capable HTTP stack into the pure-Rust workspace
//! (ADR 0004); production operator tooling would use proper clients.

use anyhow::{bail, Context, Result};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

async fn request(addr: &str, raw: String) -> Result<(u16, String)> {
    let mut stream = TcpStream::connect(addr)
        .await
        .with_context(|| format!("connecting to control-api at {addr} (is it running?)"))?;
    stream.write_all(raw.as_bytes()).await?;
    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).await?;
    let text = String::from_utf8_lossy(&buf);
    let mut parts = text.splitn(2, "\r\n\r\n");
    let head = parts.next().unwrap_or("");
    let body = parts.next().unwrap_or("").to_string();
    let code: u16 = head
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|c| c.parse().ok())
        .unwrap_or(0);
    if code == 0 {
        bail!("unparseable HTTP response from {addr}");
    }
    Ok((code, body))
}

pub async fn get(addr: &str, path: &str) -> Result<(u16, String)> {
    request(
        addr,
        format!("GET {path} HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\n\r\n"),
    )
    .await
}

pub async fn post_json(addr: &str, path: &str, json: &str) -> Result<(u16, String)> {
    request(
        addr,
        format!(
            "POST {path} HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{json}",
            json.len()
        ),
    )
    .await
}
