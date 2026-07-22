//! Studio admin CLI. Dev/operator tool — talks to localhost services and the
//! configured DATABASE_URL. Not a player-facing surface.

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use sqlx::postgres::PgPoolOptions;
use std::path::PathBuf;

mod http;

/// Migrations are embedded from control-api so `admin-cli migrate` and service
/// boot-time migration can never disagree.
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("../control-api/migrations");

#[derive(Parser)]
#[command(
    name = "studio-admin",
    version,
    about = "Studio Foundation operator commands"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Apply pending platform migrations to DATABASE_URL
    Migrate,
    /// Show applied vs pending migrations
    MigrateStatus,
    /// Apply infra/postgres/seed.sql (idempotent dev data)
    Seed,
    /// GET /healthz + /readyz from the control API
    Health,
    /// GET /v1/status from the control API
    Status,
    /// Store a JSON value: kv-set mykey '{"a":1}'
    KvSet { key: String, value: String },
    /// Read a value: kv-get mykey
    KvGet { key: String },
}

fn database_url() -> Result<String> {
    std::env::var("DATABASE_URL").context("DATABASE_URL is not set (copy .env.example to .env)")
}

fn api_addr() -> String {
    std::env::var("STUDIO_CONTROL_API_ADDR").unwrap_or_else(|_| "127.0.0.1:8080".into())
}

/// Walk up from CWD to the repo root (marked by `justfile`) so the CLI works
/// from any subdirectory without absolute paths.
fn find_repo_root() -> Result<PathBuf> {
    let mut dir = std::env::current_dir()?;
    loop {
        if dir.join("justfile").is_file() {
            return Ok(dir);
        }
        if !dir.pop() {
            bail!("repo root not found (no justfile above current directory)");
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt().with_env_filter("warn").init();
    let cli = Cli::parse();

    match cli.command {
        Command::Migrate => {
            let pool = PgPoolOptions::new().connect(&database_url()?).await?;
            MIGRATOR.run(&pool).await?;
            println!("migrations applied");
        }
        Command::MigrateStatus => {
            let pool = PgPoolOptions::new().connect(&database_url()?).await?;
            let applied: Vec<(i64,)> =
                sqlx::query_as("SELECT version FROM _sqlx_migrations ORDER BY version")
                    .fetch_all(&pool)
                    .await
                    .unwrap_or_default();
            let applied_set: std::collections::HashSet<i64> =
                applied.iter().map(|(v,)| *v).collect();
            for migration in MIGRATOR.iter() {
                let state = if applied_set.contains(&migration.version) {
                    "applied"
                } else {
                    "PENDING"
                };
                println!(
                    "{:>4} {:<40} {}",
                    migration.version, migration.description, state
                );
            }
        }
        Command::Seed => {
            let root = find_repo_root()?;
            let sql = std::fs::read_to_string(root.join("infra/postgres/seed.sql"))
                .context("reading infra/postgres/seed.sql")?;
            let pool = PgPoolOptions::new().connect(&database_url()?).await?;
            sqlx::raw_sql(&sql).execute(&pool).await?;
            println!("seed applied");
        }
        Command::Health => {
            let addr = api_addr();
            let health = http::get(&addr, "/healthz").await?;
            let ready = http::get(&addr, "/readyz").await?;
            println!("healthz: {} {}", health.0, health.1.trim());
            println!("readyz:  {} {}", ready.0, ready.1.trim());
        }
        Command::Status => {
            let (code, body) = http::get(&api_addr(), "/v1/status").await?;
            println!("{code}\n{body}");
        }
        Command::KvSet { key, value } => {
            let parsed: serde_json::Value =
                serde_json::from_str(&value).context("value must be valid JSON")?;
            let (code, body) =
                http::post_json(&api_addr(), &format!("/v1/kv/{key}"), &parsed.to_string()).await?;
            println!("{code}\n{body}");
        }
        Command::KvGet { key } => {
            let (code, body) = http::get(&api_addr(), &format!("/v1/kv/{key}")).await?;
            println!("{code}\n{body}");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cli_parses_all_subcommands() {
        for args in [
            vec!["studio-admin", "migrate"],
            vec!["studio-admin", "migrate-status"],
            vec!["studio-admin", "seed"],
            vec!["studio-admin", "health"],
            vec!["studio-admin", "status"],
            vec!["studio-admin", "kv-set", "k", "{}"],
            vec!["studio-admin", "kv-get", "k"],
        ] {
            Cli::try_parse_from(&args).expect("parses");
        }
    }
}
