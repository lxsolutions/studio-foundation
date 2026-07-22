//! Canonical world events (ADR 0007) — the single event model every client emits.
//! The simulation validates and settles these into world consequences.

use crate::economy;
use crate::state::{Resource, WorldState};
use crate::{FactionId, SectorId, Settlement};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// One authoritative world event. Every gameplay client — Plaza, Deep, strategy,
/// FPS, profession — expresses its outcome as one of these.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum WorldEvent {
    /// A miner/extractor delivered raw resource to a faction stockpile.
    ResourceExtracted {
        faction: FactionId,
        sector: SectorId,
        resource: Resource,
        /// Raw units extracted (before conversion-ratio bounding).
        units: u64,
        /// Idempotency key — replays of the same delivery never double-settle.
        idempotency_key: Uuid,
    },
    /// A factory consumed refined stock and produced equipment (e.g. a vehicle).
    FactoryCompleted {
        faction: FactionId,
        sector: SectorId,
        item: String,
        /// Refined units consumed.
        refined_units: u64,
        idempotency_key: Uuid,
    },
    /// A battle resolved control of a sector (the vertical slice's territory flip).
    TerritoryChanged {
        sector: SectorId,
        new_controller: FactionId,
        idempotency_key: Uuid,
    },
}

/// Validate and settle one event into `state`.
pub fn settle(state: &mut WorldState, event: &WorldEvent) -> Settlement {
    match event {
        WorldEvent::ResourceExtracted {
            faction,
            sector,
            resource,
            units,
            idempotency_key,
        } => {
            if !state.record_settlement(*idempotency_key) {
                return Settlement {
                    summary: "duplicate ResourceExtracted ignored (idempotency)".into(),
                    applied: false,
                };
            }
            let accepted = economy::bounded_extraction(state, *sector, *units);
            state.add_stockpile(*faction, *resource, accepted);
            Settlement {
                summary: format!(
                    "faction {:?} banked {accepted}/{} {:?} from sector {:?}",
                    faction, units, resource, sector
                ),
                applied: true,
            }
        }
        WorldEvent::FactoryCompleted {
            faction,
            sector,
            item,
            refined_units,
            idempotency_key,
        } => {
            if !state.record_settlement(*idempotency_key) {
                return Settlement {
                    summary: "duplicate FactoryCompleted ignored (idempotency)".into(),
                    applied: false,
                };
            }
            if !state.consume_stockpile(*faction, Resource::RefinedAlloy, *refined_units) {
                return Settlement {
                    summary: format!(
                        "factory in sector {sector:?} lacked {refined_units} refined alloy for {item}"
                    ),
                    applied: false,
                };
            }
            Settlement {
                summary: format!(
                    "faction {faction:?} factory produced {item} ({refined_units} alloy)"
                ),
                applied: true,
            }
        }
        WorldEvent::TerritoryChanged {
            sector,
            new_controller,
            idempotency_key,
        } => {
            if !state.record_settlement(*idempotency_key) {
                return Settlement {
                    summary: "duplicate TerritoryChanged ignored (idempotency)".into(),
                    applied: false,
                };
            }
            state.set_controller(*sector, *new_controller);
            Settlement {
                summary: format!("sector {sector:?} now controlled by {new_controller:?}"),
                applied: true,
            }
        }
    }
}
