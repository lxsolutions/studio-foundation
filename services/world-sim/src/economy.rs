//! Economy rules enforcing ADR 0007's "contributions have bounded impact."
//! Throughput limits + diminishing returns keep the world controllable: a single
//! player can't mine their way to a global war outcome in ten minutes.

use crate::state::{SectorId, WorldState};

/// Max raw units one sector will bank per settlement window, regardless of how
/// much was extracted. AI/baseline automation keeps the floor; this caps the ceiling.
pub const SECTOR_EXTRACTION_CAP_PER_WINDOW: u64 = 2_000;

/// Soft cap beyond which additional extraction yields diminishing returns.
pub const DIMINISHING_THRESHOLD: u64 = 500;

/// Bound a raw extraction amount against a sector's remaining window capacity and
/// diminishing returns. Returns the units actually banked (<= requested).
pub fn bounded_extraction(state: &WorldState, sector: SectorId, requested: u64) -> u64 {
    let already = state
        .sectors
        .get(&sector)
        .map(|s| s.extraction_this_window)
        .unwrap_or(0);
    let remaining = SECTOR_EXTRACTION_CAP_PER_WINDOW.saturating_sub(already);
    let capped = requested.min(remaining);
    apply_diminishing_returns(capped)
}

/// Piecewise diminishing returns: full value up to the threshold, then a
/// logarithmic-ish taper (here a simple square-root curve for determinism).
fn apply_diminishing_returns(units: u64) -> u64 {
    if units <= DIMINISHING_THRESHOLD {
        return units;
    }
    let over = units - DIMINISHING_THRESHOLD;
    DIMINISHING_THRESHOLD + (over as f64).sqrt() as u64
}

/// Refine raw ore into refined alloy at a fixed conversion ratio (vertical slice:
/// 10 raw -> 1 refined). Deterministic, no rounding surprises.
pub fn refine(raw_ore: u64) -> u64 {
    raw_ore / REFINE_RATIO
}

pub const REFINE_RATIO: u64 = 10;

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::WorldState;
    use uuid::Uuid;

    #[test]
    fn extraction_is_capped_per_window() {
        let mut state = WorldState::default();
        let sector = SectorId(Uuid::nil());
        state.ensure_sector(sector).extraction_this_window = 1_950;
        let accepted = bounded_extraction(&state, sector, 500);
        // Only 50 units of window remain; diminishing applies within that.
        assert!(accepted <= 50);
    }

    #[test]
    fn diminishing_returns_kick_in_past_threshold() {
        assert_eq!(apply_diminishing_returns(500), 500);
        // 500 + sqrt(500) ~= 500 + 22 = 522, not 1000.
        let got = apply_diminishing_returns(1_000);
        assert!(got < 1_000 && got > 500, "got {got}");
    }

    #[test]
    fn refine_uses_fixed_ratio() {
        assert_eq!(refine(95), 9);
        assert_eq!(refine(100), 10);
    }
}
