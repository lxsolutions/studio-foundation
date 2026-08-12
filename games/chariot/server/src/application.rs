//! Game-owned application payloads (studio protocol `ApplicationRequest`).
//! Two surfaces: the factions (stables join, race results record points per
//! faction, standings fetch returns the season tally) and the ghost runs
//! (submit stores a time-trial run, fetch returns it by id — "beat my lap").
//! Payload schema is game-owned by design — the foundation transports opaque
//! JSON.
//!
//! Persistence follows the boot wiring: PostgreSQL when `DATABASE_URL` was
//! set (game_chariot schema, migrations 0002 and 0003), an in-memory store
//! otherwise so the endpoint still answers offline and in tests.

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;

use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use studio_dedicated_server::{ApplicationFuture, ApplicationHandler, ApplicationOutcome};

use crate::factions::{
    self, Finishing, DEFAULT_SEASON,
};
use crate::ghosts::{self, GhostTick};
use crate::identity::PlazaVerifier;

#[derive(Default)]
struct MemoryState {
    memberships: HashMap<String, String>,
    points: Vec<RecordedPoint>,
    ghosts: Vec<StoredGhost>,
}

struct RecordedPoint {
    season: String,
    race_id: String,
    faction: String,
    place: u32,
    points: u32,
}

/// A stored ghost run. The tick stream is the payload; everything else is a
/// projection the fetch response is built from.
#[derive(Clone)]
struct StoredGhost {
    id: String,
    member: String,
    faction: String,
    handle: String,
    total_ms: u32,
    distance_m: f64,
    ticks: Vec<GhostTick>,
}

impl StoredGhost {
    fn summary(&self) -> Value {
        json!({
            "id": self.id,
            // The client's storage schema marker (ghost_run.gd SCHEMA), so a
            // fetched run parses and persists there exactly like a local one.
            "schema": 1,
            "member": self.member,
            "faction": self.faction,
            "handle": self.handle,
            "totalMs": self.total_ms,
            "distanceM": self.distance_m,
            "ticks": self.ticks,
        })
    }
}

enum FactionStore {
    Memory(Mutex<MemoryState>),
    Postgres(PgPool),
}

pub struct ChariotApplication {
    store: FactionStore,
    /// Plaza token verifier for ghost submits. None means the server keys
    /// ghosts by the client claim — the pre-bridge behavior, still right for
    /// dev and for any deployment without a Plaza to verify against.
    verifier: Option<Arc<dyn PlazaVerifier>>,
}

impl ChariotApplication {
    pub fn in_memory() -> Self {
        Self {
            store: FactionStore::Memory(Mutex::new(MemoryState::default())),
            verifier: None,
        }
    }

    pub fn postgres(pool: PgPool) -> Self {
        Self {
            store: FactionStore::Postgres(pool),
            verifier: None,
        }
    }

    /// Attach the Plaza verifier the binary builds from PLAZA_BASE_URL.
    pub fn with_verifier(mut self, verifier: Arc<dyn PlazaVerifier>) -> Self {
        self.verifier = Some(verifier);
        self
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

    /// Store a validated run and return its public id. Postgres ids come from
    /// the identity column; the memory store numbers its own — both carry the
    /// "g-" prefix so a client cannot tell which store answered.
    async fn ghost_save(&self, run: &StoredGhost) -> Result<String, String> {
        match &self.store {
            FactionStore::Memory(state) => {
                let mut state = state.lock().map_err(|_| "store poisoned".to_string())?;
                let id = format!("g-{}", state.ghosts.len() + 1);
                let mut stored = run.clone();
                stored.id = id.clone();
                state.ghosts.push(stored);
                Ok(id)
            }
            FactionStore::Postgres(pool) => {
                let row: (i64,) = sqlx::query_as(
                    "INSERT INTO game_chariot.ghost_runs \
                     (member_key, faction, handle, total_ms, payload) \
                     VALUES ($1, $2, $3, $4, $5) RETURNING id",
                )
                .bind(&run.member)
                .bind(&run.faction)
                .bind(&run.handle)
                .bind(run.total_ms as i32)
                .bind(json!({ "distanceM": run.distance_m, "ticks": run.ticks }))
                .fetch_one(pool)
                .await
                .map_err(|err| format!("ghost write failed: {err}"))?;
                Ok(format!("g-{}", row.0))
            }
        }
    }

    async fn ghost_load(&self, id: &str) -> Result<Option<StoredGhost>, String> {
        match &self.store {
            FactionStore::Memory(state) => {
                let state = state.lock().map_err(|_| "store poisoned".to_string())?;
                Ok(state.ghosts.iter().find(|ghost| ghost.id == id).cloned())
            }
            FactionStore::Postgres(pool) => {
                let Some(row_id) = id.strip_prefix("g-").and_then(|raw| raw.parse::<i64>().ok())
                else {
                    return Ok(None);
                };
                let row: Option<(String, String, String, i32, Value)> = sqlx::query_as(
                    "SELECT member_key, faction, handle, total_ms, payload \
                     FROM game_chariot.ghost_runs WHERE id = $1",
                )
                .bind(row_id)
                .fetch_optional(pool)
                .await
                .map_err(|err| format!("ghost read failed: {err}"))?;
                let Some((member, faction, handle, total_ms, payload)) = row else {
                    return Ok(None);
                };
                let ticks: Vec<GhostTick> =
                    serde_json::from_value(payload.get("ticks").cloned().unwrap_or(json!([])))
                        .map_err(|err| format!("stored ghost payload is malformed: {err}"))?;
                Ok(Some(StoredGhost {
                    id: id.to_string(),
                    member,
                    faction,
                    handle,
                    total_ms: total_ms.max(0) as u32,
                    distance_m: payload
                        .get("distanceM")
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0),
                    ticks,
                }))
            }
        }
    }
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum ChariotRequest {
    FactionJoin { member: String, faction: String },
    RaceRecord {
        season: Option<String>,
        #[serde(rename = "raceId")]
        race_id: String,
        results: Vec<FinishingRow>,
    },
    StandingsFetch { season: Option<String> },
    GhostSubmit {
        member: String,
        faction: String,
        handle: String,
        /// Plaza bearer token from the identity bridge. Optional: absent means
        /// the member field is a bare claim (dev, offline-shaped clients).
        token: Option<String>,
        #[serde(rename = "totalMs")]
        total_ms: u32,
        #[serde(rename = "distanceM", default)]
        distance_m: f64,
        ticks: Vec<GhostTick>,
    },
    GhostFetch { id: String },
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
            let request: ChariotRequest = match serde_json::from_str(payload_json) {
                Ok(request) => request,
                Err(err) => return rejected(format!("unknown chariot payload: {err}")),
            };
            match request {
                ChariotRequest::FactionJoin { member, faction } => {
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
                ChariotRequest::RaceRecord {
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
                ChariotRequest::StandingsFetch { season } => {
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
                ChariotRequest::GhostSubmit {
                    member,
                    faction,
                    handle,
                    token,
                    total_ms,
                    distance_m,
                    ticks,
                } => {
                    // Identity resolution. A presented token is verified
                    // against the Plaza and the run keys by the VERIFIED
                    // stable identity, never the client claim; a token that
                    // fails verification fails the submit. Without a token —
                    // or without a verifier wired at all (dev, tests) — the
                    // claimed member stands, the pre-bridge behavior.
                    let claimed_handle = handle.trim().to_string();
                    let (member_key, handle) = match token.as_deref().map(str::trim) {
                        Some(presented) if !presented.is_empty() => match &self.verifier {
                            Some(verifier) => match verifier.verify(presented).await {
                                Ok(identity) => {
                                    // The Plaza handle is authoritative
                                    // (Minerals): clipped to the plate, the
                                    // client claim only fills a blank one.
                                    let handle = if identity.handle.is_empty() {
                                        claimed_handle
                                    } else {
                                        identity
                                            .handle
                                            .chars()
                                            .take(ghosts::MAX_HANDLE)
                                            .collect()
                                    };
                                    (identity.member_key, handle)
                                }
                                Err(err) => return rejected(err),
                            },
                            None => {
                                let claimed = member.trim();
                                if claimed.is_empty() {
                                    return rejected("ghost.submit needs a member key");
                                }
                                (claimed.to_string(), claimed_handle)
                            }
                        },
                        _ => {
                            let claimed = member.trim();
                            if claimed.is_empty() {
                                return rejected("ghost.submit needs a member key");
                            }
                            (claimed.to_string(), claimed_handle)
                        }
                    };
                    if let Err(err) = ghosts::validate(&handle, &faction, total_ms, &ticks) {
                        return rejected(err);
                    }
                    if !(distance_m > 0.0 && distance_m <= ghosts::MAX_POS_M) {
                        return rejected("ghost.submit needs a plausible distanceM");
                    }
                    let run = StoredGhost {
                        id: String::new(),
                        member: member_key,
                        faction: faction.clone(),
                        handle,
                        total_ms,
                        distance_m,
                        ticks,
                    };
                    match self.ghost_save(&run).await {
                        Ok(id) => ok(json!({
                            "ok": true,
                            "kind": "ghost.submit",
                            "id": id,
                        })),
                        Err(err) => rejected(err),
                    }
                }
                ChariotRequest::GhostFetch { id } => {
                    let id = id.trim();
                    if id.is_empty() {
                        return rejected("ghost.fetch needs an id");
                    }
                    match self.ghost_load(id).await {
                        Ok(Some(run)) => ok(json!({
                            "ok": true,
                            "kind": "ghost.fetch",
                            "ghost": run.summary(),
                        })),
                        Ok(None) => rejected(format!("no such ghost: {id}")),
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

    fn ghost_payload(total_ms: u32) -> String {
        let ticks: Vec<Value> = (0..12)
            .map(|i| {
                json!({
                    "t": i as f64 * 200.0,
                    "pos": i as f64 * 3.3,
                    "lane": 2.0,
                    "speed": 16.5,
                })
            })
            .collect();
        json!({
            "kind": "ghost_submit",
            "member": "STABLE-1",
            "faction": "blue",
            "handle": "Xanthos",
            "totalMs": total_ms,
            "distanceM": 1800.0,
            "ticks": ticks,
        })
        .to_string()
    }

    #[tokio::test]
    async fn ghost_submit_then_fetch_round_trips() {
        let app = ChariotApplication::in_memory();
        let submitted = handle(&app, &ghost_payload(92_000)).await;
        assert!(submitted.accepted, "submit rejected: {}", submitted.summary);
        let id = summary(&submitted)["id"].as_str().unwrap().to_string();
        assert!(id.starts_with("g-"), "ids carry the ghost prefix: {id}");

        let fetched = handle(
            &app,
            &format!(r#"{{"kind":"ghost_fetch","id":"{id}"}}"#),
        )
        .await;
        assert!(fetched.accepted, "fetch rejected: {}", fetched.summary);
        let ghost = summary(&fetched)["ghost"].clone();
        assert_eq!(ghost["id"], json!(id));
        assert_eq!(ghost["schema"], 1, "fetched runs carry the client's storage schema");
        assert_eq!(ghost["handle"], "Xanthos");
        assert_eq!(ghost["faction"], "blue");
        assert_eq!(ghost["member"], "STABLE-1");
        assert_eq!(ghost["totalMs"], 92_000);
        assert_eq!(ghost["distanceM"], 1800.0);
        let ticks = ghost["ticks"].as_array().unwrap();
        assert_eq!(ticks.len(), 12, "the tick stream survives verbatim");
        assert_eq!(ticks[0]["t"], 0.0);
        assert_eq!(ticks[11]["pos"], 11.0_f64 * 3.3);
    }

    #[tokio::test]
    async fn ghost_submit_enforces_the_bounds() {
        let app = ChariotApplication::in_memory();
        let too_quick = handle(&app, &ghost_payload(5_000)).await;
        assert!(!too_quick.accepted, "a five-second lap is not a race");

        let mut sparse: Value = serde_json::from_str(&ghost_payload(92_000)).unwrap();
        sparse["ticks"] = json!([{"t": 0.0, "pos": 0.0, "lane": 1.0, "speed": 16.0}]);
        let thin = handle(&app, &sparse.to_string()).await;
        assert!(!thin.accepted, "a lone sample is not a run");

        let mut backwards: Value = serde_json::from_str(&ghost_payload(92_000)).unwrap();
        backwards["ticks"][4]["t"] = json!(0.0);
        let reversed = handle(&app, &backwards.to_string()).await;
        assert!(!reversed.accepted, "tick times never run backwards");

        let mut factionless: Value = serde_json::from_str(&ghost_payload(92_000)).unwrap();
        factionless["faction"] = json!("gold");
        assert!(!handle(&app, &factionless.to_string()).await.accepted);

        let mut memberless: Value = serde_json::from_str(&ghost_payload(92_000)).unwrap();
        memberless["member"] = json!("  ");
        assert!(!handle(&app, &memberless.to_string()).await.accepted);

        let mut distanceless: Value = serde_json::from_str(&ghost_payload(92_000)).unwrap();
        distanceless["distanceM"] = json!(0.0);
        assert!(!handle(&app, &distanceless.to_string()).await.accepted);

        // Rejections write nothing: the store stays empty behind them.
        let fetched = handle(&app, r#"{"kind":"ghost_fetch","id":"g-1"}"#).await;
        assert!(!fetched.accepted, "no run was ever stored");
    }

    #[tokio::test]
    async fn ghost_fetch_rejects_unknown_ids() {
        let app = ChariotApplication::in_memory();
        assert!(!handle(&app, r#"{"kind":"ghost_fetch","id":"g-99"}"#).await.accepted);
        assert!(!handle(&app, r#"{"kind":"ghost_fetch","id":""}"#).await.accepted);
    }

    fn ghost_payload_with_token(token: &str) -> String {
        let mut payload: Value = serde_json::from_str(&ghost_payload(92_000)).unwrap();
        payload["token"] = json!(token);
        payload.to_string()
    }

    #[tokio::test]
    async fn ghost_submit_with_a_verified_token_keys_by_the_plaza_identity() {
        use crate::identity::{member_key_for, StubPlazaVerifier};
        let app = ChariotApplication::in_memory().with_verifier(Arc::new(StubPlazaVerifier));
        let submitted = handle(&app, &ghost_payload_with_token("stub:stable-key-1:Balios")).await;
        assert!(submitted.accepted, "submit rejected: {}", submitted.summary);
        let id = summary(&submitted)["id"].as_str().unwrap().to_string();

        let fetched = handle(&app, &format!(r#"{{"kind":"ghost_fetch","id":"{id}"}}"#)).await;
        assert!(fetched.accepted);
        let ghost = summary(&fetched)["ghost"].clone();
        // The stored member key is the verified stable identity, hashed into
        // the plaza namespace — never the client-claimed "STABLE-1".
        assert_eq!(ghost["member"], json!(member_key_for("stable-key-1")));
        assert_ne!(ghost["member"], json!("STABLE-1"));
        // The verified Plaza handle is authoritative over the client claim.
        assert_eq!(ghost["handle"], "Balios");
        assert_eq!(ghost["schema"], 1, "fetched runs carry the client's storage schema");
    }

    #[tokio::test]
    async fn ghost_submit_with_a_refused_token_stores_nothing() {
        use crate::identity::StubPlazaVerifier;
        let app = ChariotApplication::in_memory().with_verifier(Arc::new(StubPlazaVerifier));
        let submitted = handle(&app, &ghost_payload_with_token("forged-token")).await;
        assert!(!submitted.accepted, "a token the plaza refuses fails the submit");
        let fetched = handle(&app, r#"{"kind":"ghost_fetch","id":"g-1"}"#).await;
        assert!(!fetched.accepted, "no run was ever stored");
    }

    #[tokio::test]
    async fn ghost_submit_with_a_token_but_no_verifier_keeps_the_claim() {
        // Dev posture: no PLAZA_BASE_URL, no verifier — a token cannot be
        // proven, so the claimed member stands (the pre-bridge behavior).
        let app = ChariotApplication::in_memory();
        let submitted = handle(&app, &ghost_payload_with_token("stub:stable-key-1:Balios")).await;
        assert!(submitted.accepted, "submit rejected: {}", submitted.summary);
        let id = summary(&submitted)["id"].as_str().unwrap().to_string();
        let fetched = handle(&app, &format!(r#"{{"kind":"ghost_fetch","id":"{id}"}}"#)).await;
        let ghost = summary(&fetched)["ghost"].clone();
        assert_eq!(ghost["member"], "STABLE-1", "the claim stands when nothing can verify it");
        assert_eq!(ghost["handle"], "Xanthos", "and the claimed handle with it");
    }
}
