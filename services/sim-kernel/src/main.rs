//! Native replay runner: `sim-replay <replay.json>` prints the full result JSON
//! (final_state, state_hash, hash_log, navigation) for parity comparison.

use std::process::ExitCode;

fn main() -> ExitCode {
    let Some(path) = std::env::args().nth(1) else {
        eprintln!("usage: sim-replay <replay.json>");
        return ExitCode::from(2);
    };
    let Ok(json) = std::fs::read_to_string(&path) else {
        eprintln!("cannot read {path}");
        return ExitCode::from(2);
    };
    match sim_kernel::run_replay_str(&json) {
        Ok(out) => {
            println!("{}", out.to_json());
            ExitCode::SUCCESS
        }
        Err(err) => {
            let out = serde_json::to_string(&serde_json::json!({
                "error": err.message,
                "code": err.code,
            }))
            .unwrap_or_else(|_| "{\"error\":\"serialization\"}".into());
            println!("{out}");
            ExitCode::FAILURE
        }
    }
}
