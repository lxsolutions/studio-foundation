//! Game-owned application payloads (studio protocol `ApplicationRequest`).
//! The faction surface: stables join a faction, race results record points
//! per faction, and the standings fetch returns the season tally. Payload
//! schema is game-owned by design — the foundation transports opaque JSON.
//!
//! Persistence follows the boot wiring: PostgreSQL when `DATABASE_URL` was
//! set (game_chariot schema, migration 0002), an in-memory store otherwise so
//! the endpoint still answers offline and in tests.

use std::collections::HashMap;
use std::sync::Mutex;

use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use studio_dedicated_server::{ApplicationFuture, ApplicationHandler, ApplicationOutcome};

use crate::factions::{
    self, Finishing, DEFAULT_SEASON,
};

#[derive(Default)]
struct MemoryState {
    memberships: HashMap<String, String>,
    points: Vec<RecordedPoint>,
}

struct RecordedPoint {
    season: String,
    race_id: String,
    faction: String,
    place: u32,
    points: u32,
}

enum FactionStore {
    Memory(Mutex<MemoryState>),
    Postgres(PgPool),
}

pub struct ChariotApplication {
    store: FactionStore,
}

impl ChariotApplication {
    pub fn in_memory() -> Self {
        Self {
            store: FactionStore::Memory(Mutex::new(MemoryState::default())),
        }
    }

    pub fn postgres(pool: PgPool) -> Self {
        Self {
            store: FactionStore::Postgres(pool),
        }
    }

    async fn join(&self, member: &str, faction: &str) -> Result<(), String> {
        match &self.store {
            FactionStore::Memory(state) => {
                state
                    .lock()
                    .map_err(|_| "store poisoned".to_string())?
                    .memberships
                    .insert(member.to_string(), faction.to_string());
                Ok(())
            }
            FactionStore::Postgres(pool) => sqlx::query(
                "INSERT INTO game_chariot.faction_membership (member_key, faction) \
                 VALUES ($1, $2) \
                 ON CONFLICT (member_key) DO UPDATE SET faction = EXCLUDED.faction, \
                 joined_at = now()",
            )
            .bind(member)
            .bind(faction)
            .execute(pool)
            .await
            .map(|_| ())
            .map_err(|err| format!("membership write failed: {err}")),
        }
    }

    async fn record(
        &self,
        season: &str,
        race_id: &str,
        finishings: &[Finishing],
    ) -> Result<(), String> {
        match &self.store {
            FactionStore::Memory(state) => {
                let mut state = state.lock().map_err(|_| "store poisoned".to_string())?;
                for finishing in finishings {
                    state.points.push(RecordedPoint {
                        season: season.to_string(),
                        race_id: race_id.to_string(),
                        faction: finishing.faction.clone(),
                        place: finishing.place,
                        points: finishing.points(),
                    });
                }
                Ok(())
            }
            FactionStore::Postgres(pool) => {
                for finishing in finishings {
                    sqlx::query(
                        "INSERT INTO game_chariot.faction_race_point \
                         (season, race_id, faction, place, points) \
                         VALUES ($1, $2, $3, $4, $5)",
                    )
                    .bind(season)
                    .bind(race_id)
                    .bind(&finishing.faction)
                    .bind(finishing.place as i32)
                    .bind(finishing.points() as i32)
                    .execute(pool)
                    .await
                    .map_err(|err| format!("race points write failed: {err}"))?;
                }
                Ok(())
            }
        }
    }

    async fn standings(&self, season: &str) -> Result<Vec<(String, u32)>, String> {
        let mut totals = factions::zeroed_standings();
        match &self.store {
            FactionStore::Memory(state) => {
                let state = state.lock().map_err(|_| "store poisoned".to_string())?;
                for row in state.points.iter().filter(|row| row.season == season) {
                    if let Some(total) = totals.get_mut(&row.faction) {
                        *total += row.points;
                    }
                }
            }
            FactionStore::Postgres(pool) => {
                let rows: Vec<(String, i64)> = sqlx::query_as(
                    "SELECT faction, SUM(points) FROM game_chariot.faction_race_point \
                     WHERE season = $1 GROUP BY faction",
                )
                .bind(season)
                .fetch_all(pool)
                .await
                .map_err(|err| format!("standings read failed: {err}"))?;
                for (faction, sum) in rows {
                    if let Some(total) = totals.get_mut(&faction) {
                        *total = sum.max(0) as u32;
                    }
                }
            }
        }
        // Highest tally first; faction order (the map's key order) breaks ties.
        let mut ordered: Vec<(String, u32)> = totals.into_iter().collect();
        ordered.sort_by(|a, b| b.1.cmp(&a.1));
        Ok(ordered)
    }
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum FactionRequest {
    FactionJoin { member: String, faction: String },
    RaceRecord {
        season: Option<String>,
        #[serde(rename = "raceId")]
        race_id: String,
        results: Vec<FinishingRow>,
    },
    StandingsFetch { season: Option<String> },
}

#[derive(Deserialize)]
struct FinishingRow {
    faction: String,
    place: u32,
}

fn ok(value: Value) -> ApplicationOutcome {
    ApplicationOutcome {
        accepted: true,
        summary: value.to_string(),
    }
}

fn rejected(message: impl Into<String>) -> ApplicationOutcome {
    ApplicationOutcome {
        accepted: false,
        summary: json!({ "ok": false, "error": message.into() }).to_string(),
    }
}

impl ApplicationHandler for ChariotApplication {
    fn handle<'a>(&'a self, payload_json: &'a str) -> ApplicationFuture<'a> {
        Box::pin(async move {
            let request: FactionRequest = match serde_json::from_str(payload_json) {
                Ok(request) => request,
                Err(err) => return rejected(format!("unknown faction payload: {err}")),
            };
            match request {
                FactionRequest::FactionJoin { member, faction } => {
                    let member = member.trim();
                    if member.is_empty() {
                        return rejected("faction.join needs a member key");
                    }
                    if !factions::is_valid_faction(&faction) {
                        return rejected(format!("no such faction: {faction}"));
                    }
                    match self.join(member, &faction).await {
                        Ok(()) => ok(json!({
                            "ok": true,
                            "kind": "faction.join",
                            "member": member,
                            "faction": faction,
                        })),
                        Err(err) => rejected(err),
                    }
                }
                FactionRequest::RaceRecord {
                    season,
                    race_id,
                    results,
                } => {
                    let season = season.unwrap_or_else(|| DEFAULT_SEASON.to_string());
                    if race_id.trim().is_empty() {
                        return rejected("race.record needs a raceId");
                    }
                    if results.is_empty() {
                        return rejected("race.record needs at least one finisher");
                    }
                    let mut finishings: Vec<Finishing> = Vec::with_capacity(results.len());
                    for row in results {
                        if !factions::is_valid_faction(&row.faction) {
                            return rejected(format!("no such faction: {}", row.faction));
                        }
                        if row.place < 1 {
                            return rejected("places start at 1");
                        }
                        finishings.push(Finishing {
                            faction: row.faction,
                            place: row.place,
                        });
                    }
                    match self.record(&season, &race_id, &finishings).await {
                        Ok(()) => ok(json!({
                            "ok": true,
                            "kind": "race.record",
                            "season": season,
                            "raceId": race_id,
                            "tally": factions::tally(&finishings),
                        })),
                        Err(err) => rejected(err),
                    }
                }
                FactionRequest::StandingsFetch { season } => {
                    let season = season.unwrap_or_else(|| DEFAULT_SEASON.to_string());
                    match self.standings(&season).await {
                        Ok(standings) => ok(json!({
                            "ok": true,
                            "kind": "standings.fetch",
                            "season": season,
                            "standings": standings
                                .iter()
                                .map(|(faction, points)| json!({
                                    "faction": faction,
                                    "points": points,
                                }))
                                .collect::<Vec<_>>(),
                        })),
                        Err(err) => rejected(err),
                    }
                }
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn handle(app: &ChariotApplication, payload: &str) -> ApplicationOutcome {
        app.handle(payload).await
    }

    fn summary(outcome: &ApplicationOutcome) -> Value {
        serde_json::from_str(&outcome.summary).expect("summary is JSON")
    }

    #[tokio::test]
    async fn join_validates_membership() {
        let app = ChariotApplication::in_memory();
        let joined = handle(&app, r#"{"kind":"faction_join","member":"STABLE-1","faction":"blue"}"#).await;
        assert!(joined.accepted);
        assert_eq!(summary(&joined)["faction"], "blue");

        let bad = handle(&app, r#"{"kind":"faction_join","member":"STABLE-1","faction":"gold"}"#).await;
        assert!(!bad.accepted, "unknown factions are rejected");
        let empty = handle(&app, r#"{"kind":"faction_join","member":"  ","faction":"blue"}"#).await;
        assert!(!empty.accepted, "a member key is required");
    }

    #[tokio::test]
    async fn record_derives_points_from_place() {
        let app = ChariotApplication::in_memory();
        let recorded = handle(
            &app,
            r#"{"kind":"race_record","season":"s1","raceId":"r-1","results":[
                {"faction":"green","place":1},
                {"faction":"blue","place":2},
                {"faction":"blue","place":3},
                {"faction":"white","place":5}
            ]}"#,
        )
        .await;
        assert!(recorded.accepted);
        let body = summary(&recorded);
        // The client asserts places; the server owns the points table.
        assert_eq!(body["tally"]["green"], 9);
        assert_eq!(body["tally"]["blue"], 10, "second and third home");
        assert_eq!(body["tally"]["white"], 0);
        assert_eq!(body["tally"]["red"], 0, "all four factions always appear");
    }

    #[tokio::test]
    async fn record_rejects_bad_rows_atomically() {
        let app = ChariotApplication::in_memory();
        let bad = handle(
            &app,
            r#"{"kind":"race_record","raceId":"r-2","results":[{"faction":"gold","place":1}]}"#,
        )
        .await;
        assert!(!bad.accepted);
        let standings = handle(&app, r#"{"kind":"standings_fetch"}"#).await;
        assert!(standings.accepted);
        let rows = summary(&standings)["standings"].as_array().unwrap().clone();
        assert!(
            rows.iter().all(|row| row["points"] == 0),
            "a rejected race records nothing"
        );
    }

    #[tokio::test]
    async fn standings_sum_the_season_per_faction() {
        let app = ChariotApplication::in_memory();
        for (race_id, results) in [
            ("r-1", r#"[{"faction":"blue","place":1},{"faction":"red","place":2}]"#),
            ("r-2", r#"[{"faction":"green","place":1},{"faction":"blue","place":4}]"#),
        ] {
            let payload = format!(
                r#"{{"kind":"race_record","season":"s1","raceId":"{race_id}","results":{results}}}"#
            );
            assert!(handle(&app, &payload).await.accepted);
        }
        // Another season must not leak into this one.
        let other = r#"{"kind":"race_record","season":"s0","raceId":"r-0","results":[{"faction":"red","place":1}]}"#;
        assert!(handle(&app, other).await.accepted);

        let fetched = handle(&app, r#"{"kind":"standings_fetch","season":"s1"}"#).await;
        assert!(fetched.accepted);
        let rows = summary(&fetched)["standings"].as_array().unwrap().clone();
        assert_eq!(rows.len(), 4);
        assert_eq!(rows[0], json!({"faction": "blue", "points": 11}));
        assert_eq!(rows[1], json!({"faction": "green", "points": 9}));
        assert_eq!(rows[2], json!({"faction": "red", "points": 6}));
        assert_eq!(rows[3], json!({"faction": "white", "points": 0}));
    }

    #[tokio::test]
    async fn unknown_payloads_are_rejected() {
        let app = ChariotApplication::in_memory();
        assert!(!handle(&app, "{nope").await.accepted);
        assert!(!handle(&app, r#"{"kind":"something_else"}"#).await.accepted);
    }
}
