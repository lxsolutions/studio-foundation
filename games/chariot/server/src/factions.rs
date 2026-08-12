//! The four circus factions as pure domain logic, mirrored by the client's
//! `project/src/core/circus_factions.gd` — change both or change neither.
//! No I/O here: the store behind the application handler owns persistence.

use std::collections::BTreeMap;

/// The Byzantine four, in circus order: Veneta, Prasina, Russata, Albata.
pub const FACTION_IDS: [&str; 4] = ["blue", "green", "red", "white"];

/// First four home score; the rest of the field does not.
pub const POINTS_BY_PLACE: [u32; 4] = [9, 6, 4, 2];

/// Season tally bucket when a payload does not name one.
pub const DEFAULT_SEASON: &str = "s1";

pub fn is_valid_faction(faction: &str) -> bool {
    FACTION_IDS.contains(&faction)
}

pub fn points_for_place(place: u32) -> u32 {
    if place < 1 || place as usize > POINTS_BY_PLACE.len() {
        return 0;
    }
    POINTS_BY_PLACE[place as usize - 1]
}

/// One scoring finisher: a faction and where it finished. Points are always
/// derived server-side from the place — clients never assert their own.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finishing {
    pub faction: String,
    pub place: u32,
}

impl Finishing {
    pub fn points(&self) -> u32 {
        points_for_place(self.place)
    }
}

/// Fold one race's finishers into points per faction. Unknown factions and
/// unscored places add nothing; all four factions always appear, because zero
/// is a real standing. BTreeMap keeps the JSON output deterministic.
pub fn tally(finishings: &[Finishing]) -> BTreeMap<String, u32> {
    let mut points = zeroed_standings();
    for finishing in finishings {
        if !is_valid_faction(&finishing.faction) {
            continue;
        }
        *points.entry(finishing.faction.clone()).or_insert(0) += finishing.points();
    }
    points
}

pub fn zeroed_standings() -> BTreeMap<String, u32> {
    FACTION_IDS
        .iter()
        .map(|id| ((*id).to_string(), 0))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_byzantine_four() {
        assert_eq!(FACTION_IDS, ["blue", "green", "red", "white"]);
        assert!(is_valid_faction("blue"));
        assert!(!is_valid_faction("gold"));
        assert!(!is_valid_faction(""));
    }

    #[test]
    fn points_table() {
        assert_eq!(points_for_place(1), 9);
        assert_eq!(points_for_place(2), 6);
        assert_eq!(points_for_place(3), 4);
        assert_eq!(points_for_place(4), 2);
        assert_eq!(points_for_place(5), 0, "fifth home scores nothing");
        assert_eq!(points_for_place(0), 0);
    }

    #[test]
    fn tally_folds_one_race() {
        let points = tally(&[
            Finishing { faction: "blue".into(), place: 1 },
            Finishing { faction: "green".into(), place: 2 },
            Finishing { faction: "blue".into(), place: 3 },
            Finishing { faction: "white".into(), place: 5 },
            Finishing { faction: "gold".into(), place: 1 },
        ]);
        assert_eq!(points["blue"], 13, "first and third home");
        assert_eq!(points["green"], 6);
        assert_eq!(points["red"], 0, "all four factions always appear");
        assert_eq!(points["white"], 0, "unscored places add nothing");
        assert_eq!(points.len(), 4);
    }

    #[test]
    fn tally_of_nothing_is_four_zeros() {
        let points = tally(&[]);
        assert_eq!(points.len(), 4);
        assert!(points.values().all(|p| *p == 0));
    }
}
