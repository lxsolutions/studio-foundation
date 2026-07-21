//! Durable world state (ADR 0005: PostgreSQL is the source of truth; this is the
//! in-memory mirror the simulation mutates deterministically).

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct FactionId(pub Uuid);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SectorId(pub Uuid);

/// Resource kinds the closed-loop economy tracks (vertical slice scope).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Resource {
    RawOre,
    RefinedAlloy,
}

/// One sector of the campaign world.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Sector {
    pub id: SectorId,
    pub controller: Option<FactionId>,
    /// Per-settlement-window extraction already accepted (for throughput bounding).
    pub extraction_this_window: u64,
}

/// The authoritative world: factions, sectors, stockpiles, settled-event log.
#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct WorldState {
    pub factions: HashSet<FactionId>,
    pub sectors: HashMap<SectorId, Sector>,
    /// faction -> resource -> units.
    pub stockpiles: HashMap<FactionId, HashMap<Resource, u64>>,
    /// Idempotency keys already settled (append-only; mirrors the PG ledger).
    settled: HashSet<Uuid>,
}

impl WorldState {
    /// Record a settlement idempotency key. Returns false if already seen.
    pub fn record_settlement(&mut self, key: Uuid) -> bool {
        self.settled.insert(key)
    }

    pub fn ensure_sector(&mut self, id: SectorId) -> &mut Sector {
        self.sectors.entry(id).or_insert_with(|| Sector {
            id,
            controller: None,
            extraction_this_window: 0,
        })
    }

    pub fn set_controller(&mut self, sector: SectorId, faction: FactionId) {
        self.factions.insert(faction);
        self.ensure_sector(sector).controller = Some(faction);
    }

    pub fn add_stockpile(&mut self, faction: FactionId, resource: Resource, units: u64) {
        self.factions.insert(faction);
        *self
            .stockpiles
            .entry(faction)
            .or_default()
            .entry(resource)
            .or_insert(0) += units;
    }

    /// Consume units if available. Returns true on success (and deducts).
    pub fn consume_stockpile(&mut self, faction: FactionId, resource: Resource, units: u64) -> bool {
        let Some(stock) = self
            .stockpiles
            .get_mut(&faction)
            .and_then(|m| m.get_mut(&resource))
        else {
            return false;
        };
        if *stock < units {
            return false;
        }
        *stock -= units;
        true
    }

    pub fn stockpile(&self, faction: FactionId, resource: Resource) -> u64 {
        self.stockpiles
            .get(&faction)
            .and_then(|m| m.get(&resource))
            .copied()
            .unwrap_or(0)
    }
}
