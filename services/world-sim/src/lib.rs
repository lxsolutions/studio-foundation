//! Authoritative world simulation core for the Asha platform (ADR 0007).
//!
//! One canonical reality; many gameplay clients (Plaza, Deep, strategy, FPS) see
//! slices of it. Clients emit [`WorldEvent`]s; the simulation validates and settles
//! them into durable [`WorldState`]. Persistence is PostgreSQL (ADR 0005) — this
//! crate is the deterministic, unit-testable core with no I/O of its own.
//!
//! Design laws enforced here (ADR 0007):
//! * Contributions have **bounded impact** (throughput limits, conversion ratios,
//!   diminishing returns) so no single action decides a war.
//! * **AI/baseline automation fills vacant roles** — the world runs without humans.

pub mod economy;
pub mod events;
pub mod state;

pub use events::WorldEvent;
pub use state::{FactionId, SectorId, WorldState};

/// Result of settling one validated event against the world.
#[derive(Debug, Clone, PartialEq)]
pub struct Settlement {
    /// Human/machine-readable description of what changed.
    pub summary: String,
    /// True when the event changed world state; false when rejected/no-op.
    pub applied: bool,
}

/// The deterministic simulation. Construct with a [`WorldState`], feed it
/// [`WorldEvent`]s, read back state for persistence or client sync.
#[derive(Debug, Default)]
pub struct WorldSim {
    pub state: WorldState,
}

impl WorldSim {
    pub fn new(state: WorldState) -> Self {
        Self { state }
    }

    /// Validate and settle a single world event. Pure: no I/O, no clock, no RNG —
    /// all nondeterminism is injected by callers so replays are reproducible.
    pub fn settle(&mut self, event: &WorldEvent) -> Settlement {
        events::settle(&mut self.state, event)
    }

    /// Serialize the whole world to JSON (ADR 0005 persistence boundary). The
    /// simulation stays I/O-free; the owning server decides where this lands
    /// (PostgreSQL row, file, replication payload).
    pub fn snapshot(&self) -> serde_json::Result<String> {
        serde_json::to_string(&self.state)
    }

    /// Restore a world from a [`snapshot`](Self::snapshot) payload.
    pub fn restore(json: &str) -> serde_json::Result<Self> {
        let state = serde_json::from_str(json)?;
        Ok(Self::new(state))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_world_is_empty_but_alive() {
        let sim = WorldSim::default();
        assert!(sim.state.factions.is_empty());
        assert!(sim.state.sectors.is_empty());
    }

    #[test]
    fn snapshot_roundtrip_preserves_state() {
        use crate::state::Resource;
        let mut sim = WorldSim::default();
        let faction = FactionId(uuid::Uuid::from_u128(1));
        let sector = SectorId(uuid::Uuid::from_u128(2));
        sim.settle(&WorldEvent::ResourceExtracted {
            faction,
            sector,
            resource: Resource::RawOre,
            units: 100,
            idempotency_key: uuid::Uuid::from_u128(9),
        });
        let json = sim.snapshot().unwrap();
        let restored = WorldSim::restore(&json).unwrap();
        assert_eq!(restored.state.stockpile(faction, Resource::RawOre), 100);
        // Settled idempotency keys survive, so replays stay no-ops after restore.
        let mut restored = restored;
        let dup = restored.settle(&WorldEvent::ResourceExtracted {
            faction,
            sector,
            resource: Resource::RawOre,
            units: 100,
            idempotency_key: uuid::Uuid::from_u128(9),
        });
        assert!(!dup.applied);
    }
}
