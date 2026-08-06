//! Conformance corpus runner (Rust side): every valid fixture must reproduce
//! the committed final state, hash log, and navigation; every invalid fixture
//! must fail with the committed error code. The same corpus drives the Python
//! and Wasm kernels — that is what makes "same semantics" a checked property.

use sim_kernel::{run_replay_str, SimError};
use serde_json::Value;
use std::path::{Path, PathBuf};

fn corpus() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/sim/conformance/v0.1")
}

#[test]
fn valid_fixtures_match_committed_expectations() {
    let dir = corpus().join("valid");
    let mut count = 0;
    for entry in std::fs::read_dir(&dir).unwrap() {
        let path = entry.unwrap().path();
        let text = std::fs::read_to_string(&path).unwrap();
        let fixture: Value = serde_json::from_str(&text).unwrap();
        let result = run_replay_str(&text)
            .unwrap_or_else(|e| panic!("{}: kernel rejected a valid fixture: {e}", path.display()));
        let expect = &fixture["expect"];
        assert_eq!(
            serde_json::to_value(&result.final_state).unwrap(),
            *expect.get("final_state").unwrap(),
            "{}: final_state",
            path.display()
        );
        assert_eq!(
            serde_json::to_value(&result.hash_log).unwrap(),
            *expect.get("hash_log").unwrap(),
            "{}: hash_log",
            path.display()
        );
        assert_eq!(
            result.state_hash,
            expect["state_hash"].as_str().unwrap(),
            "{}: state_hash",
            path.display()
        );
        assert_eq!(
            result.navigation,
            *expect.get("navigation").unwrap(),
            "{}: navigation",
            path.display()
        );
        count += 1;
    }
    assert!(count >= 5, "corpus must not silently shrink: {count} valid fixtures");
}

#[test]
fn invalid_fixtures_fail_with_committed_error_codes() {
    let dir = corpus().join("invalid");
    let mut count = 0;
    for entry in std::fs::read_dir(&dir).unwrap() {
        let path = entry.unwrap().path();
        let text = std::fs::read_to_string(&path).unwrap();
        // expect_error is read textually: some fixtures are deliberately not
        // parseable JSON (NaN), which is exactly what they test
        let marker = "\"expect_error\": \"";
        let start = text.find(marker).expect("fixture carries expect_error") + marker.len();
        let expected: String = text[start..].chars().take_while(|c| c.is_ascii_alphanumeric() || *c == '_').collect();
        match run_replay_str(&text) {
            Ok(_) => panic!("{}: invalid fixture ran clean", path.display()),
            Err(SimError { code, message }) => assert_eq!(
                code, expected,
                "{}: wrong error code ({message})",
                path.display()
            ),
        }
        count += 1;
    }
    assert!(count >= 8, "corpus must not silently shrink: {count} invalid fixtures");
}

#[test]
fn same_visible_state_different_drive_pair() {
    let dir = corpus().join("state");
    let a_text = std::fs::read_to_string(dir.join("same_visible_different_drive_a.json")).unwrap();
    let b_text = std::fs::read_to_string(dir.join("same_visible_different_drive_b.json")).unwrap();
    let a = run_replay_str(&a_text).unwrap();
    let b = run_replay_str(&b_text).unwrap();
    assert_eq!(
        a.final_state.pointer("/fortress_gate/state/openness"),
        b.final_state.pointer("/fortress_gate/state/openness"),
        "the fixture pair must present identical visible state"
    );
    assert_ne!(a.state_hash, b.state_hash, "control intent is hashed state");
}
