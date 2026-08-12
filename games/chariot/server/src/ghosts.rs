//! Ghost time-trial runs ("beat my lap") as pure domain logic, mirrored by
//! the client's `project/src/core/ghost_run.gd` — change both or change
//! neither. The server derives nothing from a submission beyond storing it:
//! validation is sane bounds on the tick stream's length and duration, so a
//! stored run is at least a plausible race. No I/O here: the store behind the
//! application handler owns persistence.

use serde::Deserialize;
use serde::Serialize;

use crate::factions;

/// A real run is hundreds of 200ms ticks; eight is the floor for a stream
/// that could still be a (very short) race.
pub const MIN_TICKS: usize = 8;
/// 20k ticks at 200ms bounds a stored run to ~66 minutes of race clock — the
/// payload-size cap, since ticks are the only unbounded field.
pub const MAX_TICKS: usize = 20_000;
/// 1800m at record pace is ~90s; 30s floors out junk that cannot be a lap.
pub const MIN_TOTAL_MS: u32 = 30_000;
/// Twenty minutes covers any race the club would ever post.
pub const MAX_TOTAL_MS: u32 = 1_200_000;
/// Handles render on name plates and the laurel board; 24 chars is plenty.
pub const MAX_HANDLE: usize = 24;
/// The hippodrome has no lane beyond the teens; positions cap far beyond any
/// posted distance.
pub const MIN_LANE: f64 = 0.5;
pub const MAX_LANE: f64 = 16.0;
pub const MAX_POS_M: f64 = 50_000.0;
/// Chariots top out near 20 m/s; 100 is generous beyond anything the sim sends.
pub const MAX_SPEED_MPS: f64 = 100.0;

/// One sample of a run: race-clock time in milliseconds (the client
/// normalizes whatever its tick clock carried), meters into the race, the
/// live lane float, and ground speed.
#[derive(Debug, Clone, Copy, PartialEq, Deserialize, Serialize)]
pub struct GhostTick {
    pub t: f64,
    pub pos: f64,
    pub lane: f64,
    #[serde(default)]
    pub speed: f64,
}

/// Bounds-check a run a client asked us to store. Every rule is a sanity
/// bound on shape and duration — the server never re-simulates or scores it.
pub fn validate(
    handle: &str,
    faction: &str,
    total_ms: u32,
    ticks: &[GhostTick],
) -> Result<(), String> {
    let handle = handle.trim();
    if handle.is_empty() || handle.chars().count() > MAX_HANDLE {
        return Err(format!("a ghost handle is 1..={MAX_HANDLE} characters"));
    }
    if !factions::is_valid_faction(faction) {
        return Err(format!("no such faction: {faction}"));
    }
    if !(MIN_TOTAL_MS..=MAX_TOTAL_MS).contains(&total_ms) {
        return Err(format!(
            "totalMs must sit within {MIN_TOTAL_MS}..={MAX_TOTAL_MS}"
        ));
    }
    if ticks.len() < MIN_TICKS || ticks.len() > MAX_TICKS {
        return Err(format!(
            "a ghost run holds {MIN_TICKS}..={MAX_TICKS} ticks"
        ));
    }
    let mut last_t = f64::NEG_INFINITY;
    for tick in ticks {
        if ![tick.t, tick.pos, tick.lane, tick.speed]
            .into_iter()
            .all(f64::is_finite)
        {
            return Err("tick values must be finite".to_string());
        }
        if tick.t < last_t {
            return Err("tick times must not run backwards".to_string());
        }
        last_t = tick.t;
        if tick.t < 0.0 || tick.t > f64::from(MAX_TOTAL_MS) {
            return Err(format!("tick times stay within 0..={MAX_TOTAL_MS}ms"));
        }
        if !(0.0..=MAX_POS_M).contains(&tick.pos) {
            return Err(format!("tick positions stay within 0..={MAX_POS_M}m"));
        }
        if !(MIN_LANE..=MAX_LANE).contains(&tick.lane) {
            return Err(format!("tick lanes stay within {MIN_LANE}..={MAX_LANE}"));
        }
        if !(0.0..=MAX_SPEED_MPS).contains(&tick.speed) {
            return Err(format!("tick speeds stay within 0..={MAX_SPEED_MPS}m/s"));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sane_ticks() -> Vec<GhostTick> {
        (0..12)
            .map(|i| GhostTick {
                t: f64::from(i) * 200.0,
                pos: f64::from(i) * 3.3,
                lane: 2.0,
                speed: 16.5,
            })
            .collect()
    }

    #[test]
    fn a_sane_run_validates() {
        assert!(validate("Xanthos", "blue", 92_000, &sane_ticks()).is_ok());
    }

    #[test]
    fn bounds_rejections() {
        let ticks = sane_ticks();
        assert!(validate("", "blue", 92_000, &ticks).is_err(), "empty handle");
        assert!(
            validate("a handle that runs far too long for a plate", "blue", 92_000, &ticks).is_err(),
            "overlong handle"
        );
        assert!(validate("Xanthos", "gold", 92_000, &ticks).is_err(), "unknown faction");
        assert!(validate("Xanthos", "blue", 5_000, &ticks).is_err(), "too quick to be a lap");
        assert!(validate("Xanthos", "blue", 9_999_999, &ticks).is_err(), "too slow to be a race");
        assert!(validate("Xanthos", "blue", 92_000, &ticks[..4]).is_err(), "too few ticks");

        let mut backwards = sane_ticks();
        backwards[5].t = 0.0;
        assert!(validate("Xanthos", "blue", 92_000, &backwards).is_err(), "time runs forward");

        let mut off_track = sane_ticks();
        off_track[3].pos = -1.0;
        assert!(validate("Xanthos", "blue", 92_000, &off_track).is_err(), "positions stay on course");

        let mut off_lane = sane_ticks();
        off_lane[3].lane = 99.0;
        assert!(validate("Xanthos", "blue", 92_000, &off_lane).is_err(), "lanes stay in the field");

        let mut timeless = sane_ticks();
        timeless[3].t = f64::NAN;
        assert!(validate("Xanthos", "blue", 92_000, &timeless).is_err(), "NaN is not a time");
    }
}
