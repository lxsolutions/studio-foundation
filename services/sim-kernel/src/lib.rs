//! Deterministic simulation kernel (ADR 0018 milestone M3), Rust side.
//!
//! Contract: initial world state + seed + fixed-step event stream = final
//! state hash. Both kernels consume a COMPILED simulation contract
//! (worldc.sim_contract), never raw World IR: the contract is integer-only
//! (float state vars are milli-units), and the replay pins each contract by
//! its canonical hash. Replays are self-contained — contracts inline — so
//! native, Wasm, and hosted runs need no document I/O at all.
//!
//! Integer fixed-point state; control intent inside the hashed state;
//! fail-closed validation with stable error codes matching the canonical
//! Python kernel (tools/sim/kernel.py; spec: docs/specs/sim-replay-v0.1.md).

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

pub const MAX_EVENT_ARG: i64 = 65_535;
pub const MAX_TICKS: i64 = 1_000_000;
pub const QUANTUM: i64 = 1000;

#[derive(Debug)]
pub struct SimError {
    pub code: &'static str,
    pub message: String,
}

impl SimError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self { code, message: message.into() }
    }
}

impl std::fmt::Display for SimError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for SimError {}

// ------------------------------------------------------- canonical JSON
//
// Byte-compatible with Python's json.dumps(obj, sort_keys=True,
// separators=(",", ":")) including ensure_ascii string escaping. Contracts
// are integer-only by design; the float path exists only for completeness.

fn canon_string(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c if (c as u32) < 0x7f => out.push(c),
            c => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", unit));
                }
            }
        }
    }
    out.push('"');
}

fn canon_value(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                out.push_str(&i.to_string());
            } else if let Some(u) = n.as_u64() {
                out.push_str(&u.to_string());
            } else if let Some(f) = n.as_f64() {
                if f == f.trunc() && f.is_finite() {
                    out.push_str(&format!("{f:.1}"));
                } else {
                    out.push_str(&format!("{f}"));
                }
            }
        }
        Value::String(s) => canon_string(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                canon_value(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            out.push('{');
            let sorted: BTreeMap<&String, &Value> = map.iter().collect();
            for (i, (key, value)) in sorted.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                canon_string(key, out);
                out.push(':');
                canon_value(value, out);
            }
            out.push('}');
        }
    }
}

pub fn canonical_json(v: &Value) -> String {
    let mut out = String::new();
    canon_value(v, &mut out);
    out
}

pub fn sha256_hex(data: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data.as_bytes());
    format!("{:x}", hasher.finalize())
}

// ------------------------------------------------------------- the kernel

#[derive(Debug, Clone, Default)]
pub struct EntitySim {
    pub state: Map<String, Value>,   // declared vars; floats are milli ints
    pub control: Map<String, Value>, // drive targets; part of the hashed state
}

fn params(contract: &Value) -> &Map<String, Value> {
    contract
        .get("parameters")
        .and_then(Value::as_object)
        .expect("contract parameters present (validated)")
}

fn param_i64(contract: &Value, key: &str, default: i64) -> i64 {
    params(contract)
        .get(key)
        .and_then(Value::as_i64)
        .unwrap_or(default)
}

fn affordances(contract: &Value) -> Vec<&str> {
    contract
        .get("affordances")
        .and_then(Value::as_array)
        .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
        .unwrap_or_default()
}

fn initial_state(contract: &Value) -> Map<String, Value> {
    let mut state = Map::new();
    if let Some(schema) = contract.get("state").and_then(Value::as_object) {
        for (var, spec) in schema {
            let value = match spec.get("storage").and_then(Value::as_str) {
                Some("milli_i64") | Some("i64") => Value::from(0),
                Some("bool") => Value::from(false),
                Some("string") => Value::from(""),
                _ => Value::Null,
            };
            state.insert(var.clone(), value);
        }
    }
    state
}

fn coerce_initial(entity: &str, contract: &Value, var: &str, value: &Value) -> Result<Value, SimError> {
    let schema = contract.get("state").and_then(Value::as_object);
    let storage = schema
        .and_then(|s| s.get(var))
        .and_then(|s| s.get("storage"))
        .and_then(Value::as_str);
    match storage {
        Some("milli_i64") | Some("i64") => match value.as_i64() {
            // float state vars take INTEGER MILLI-UNITS; no float conversion
            // ever happens inside the kernel
            Some(i) => Ok(Value::from(i)),
            None => Err(SimError::new(
                "E_INITIAL_TYPE",
                format!("{entity}: initial {var} must be an integer (milli-units for float vars)"),
            )),
        },
        Some("bool") => match value.as_bool() {
            Some(b) => Ok(Value::from(b)),
            None => Err(SimError::new(
                "E_INITIAL_TYPE",
                format!("{entity}: initial {var} must be a boolean"),
            )),
        },
        Some("string") => match value.as_str() {
            Some(s) => Ok(Value::from(s)),
            None => Err(SimError::new(
                "E_INITIAL_TYPE",
                format!("{entity}: initial {var} must be a string"),
            )),
        },
        Some(other) => Err(SimError::new(
            "E_CONTRACT_SHAPE",
            format!("{entity}: unknown storage {other:?}"),
        )),
        None => Err(SimError::new(
            "E_INITIAL_UNKNOWN_VAR",
            format!("{entity}: initial sets undeclared state var {var:?}"),
        )),
    }
}

fn get_i64(map: &Map<String, Value>, key: &str) -> i64 {
    map.get(key).and_then(Value::as_i64).unwrap_or(0)
}

fn apply_event(
    contract: &Value,
    entity: &str,
    sim: &mut EntitySim,
    verb: &str,
    arg: &Value,
) -> Result<(), SimError> {
    if !affordances(contract).contains(&verb) {
        return Err(SimError::new(
            "E_UNDECLARED_AFFORDANCE",
            format!("{entity}: event verb {verb:?} is not a declared affordance"),
        ));
    }
    match verb {
        "open" | "close" | "lock" | "unlock" => {
            if !arg.is_null() {
                return Err(SimError::new(
                    "E_ARGUMENT_DOMAIN",
                    format!("{entity}: {verb} takes no argument"),
                ));
            }
        }
        "attack" | "repair" => match arg.as_i64() {
            Some(n) if (0..=MAX_EVENT_ARG).contains(&n) => {}
            Some(_) => {
                return Err(SimError::new(
                    "E_ARGUMENT_RANGE",
                    format!("{entity}: {verb} amount out of range 0..{MAX_EVENT_ARG}"),
                ))
            }
            None => {
                return Err(SimError::new(
                    "E_ARGUMENT_TYPE",
                    format!("{entity}: {verb} needs a nonnegative integer amount"),
                ))
            }
        },
        other => {
            return Err(SimError::new(
                "E_NO_SEMANTICS",
                format!("{entity}: no semantics for affordance {other:?} in kernel v0.1"),
            ))
        }
    }

    let max_health = param_i64(contract, "max_health", 100);
    let destroyed = sim.state.get("destroyed").and_then(Value::as_bool).unwrap_or(false);
    let locked = sim.state.get("locked").and_then(Value::as_bool).unwrap_or(false);

    match verb {
        "open" => {
            if !destroyed && !locked {
                sim.control.insert("openness_target".into(), Value::from(QUANTUM));
            }
        }
        "close" => {
            if !destroyed {
                sim.control.insert("openness_target".into(), Value::from(0));
            }
        }
        "lock" => {
            sim.state.insert("locked".into(), Value::from(true));
        }
        "unlock" => {
            sim.state.insert("locked".into(), Value::from(false));
        }
        "attack" => {
            if !sim.state.contains_key("health") {
                return Err(SimError::new(
                    "E_NO_SEMANTICS",
                    format!("{entity}: attack needs a 'health' state var"),
                ));
            }
            let damage = arg.as_i64().unwrap_or(0);
            let health = get_i64(&sim.state, "health").saturating_sub(damage).max(0);
            sim.state.insert("health".into(), Value::from(health));
            if health == 0 && sim.state.contains_key("destroyed") {
                sim.state.insert("destroyed".into(), Value::from(true));
                sim.control.insert("openness_target".into(), Value::from(QUANTUM));
            }
        }
        "repair" => {
            if !sim.state.contains_key("health") {
                return Err(SimError::new(
                    "E_NO_SEMANTICS",
                    format!("{entity}: repair needs a 'health' state var"),
                ));
            }
            let amount = arg.as_i64().unwrap_or(0);
            let health = get_i64(&sim.state, "health").saturating_add(amount).min(max_health);
            sim.state.insert("health".into(), Value::from(health));
            if health > 0 && sim.state.contains_key("destroyed") {
                sim.state.insert("destroyed".into(), Value::from(false));
            }
        }
        _ => unreachable!(),
    }
    Ok(())
}

fn step_entity(contract: &Value, sim: &mut EntitySim) {
    if !sim.state.contains_key("openness") {
        return;
    }
    let rate = param_i64(contract, "open_rate_milli", 250);
    let current = get_i64(&sim.state, "openness");
    let target = sim
        .control
        .get("openness_target")
        .and_then(Value::as_i64)
        .unwrap_or(current);
    let next = if current < target {
        (current + rate).min(target)
    } else if current > target {
        (current - rate).max(target)
    } else {
        current
    };
    sim.state.insert("openness".into(), Value::from(next));
}

pub fn blocks_navigation(contract: &Value, state: &Map<String, Value>) -> bool {
    let nav = params(contract).get("navigation").and_then(Value::as_object);
    let Some(nav) = nav else { return false };
    if nav
        .get("never_blocks_when_destroyed")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        && state.get("destroyed").and_then(Value::as_bool).unwrap_or(false)
    {
        return false;
    }
    // EVERY blocks_below rule is evaluated; any unsatisfied rule blocks
    if let Some(rules) = nav.get("blocks_below").and_then(Value::as_array) {
        for rule in rules {
            let var = rule.get("var").and_then(Value::as_str).unwrap_or("");
            let threshold = rule.get("threshold_milli").and_then(Value::as_i64).unwrap_or(0);
            if state.get(var).and_then(Value::as_i64).unwrap_or(QUANTUM) < threshold {
                return true;
            }
        }
    }
    false
}

fn world_value(world: &BTreeMap<String, EntitySim>) -> Value {
    let mut root = Map::new();
    for (name, sim) in world {
        let mut entity = Map::new();
        entity.insert("state".into(), Value::Object(sim.state.clone()));
        entity.insert("control".into(), Value::Object(sim.control.clone()));
        root.insert(name.clone(), Value::Object(entity));
    }
    Value::Object(root)
}

fn world_hash(world: &BTreeMap<String, EntitySim>) -> String {
    sha256_hex(&canonical_json(&world_value(world)))
}

#[derive(Debug)]
pub struct RunOutput {
    pub final_state: Value,
    pub state_hash: String,
    pub hash_log: Vec<String>,
    pub snapshots: Vec<Value>,
    pub navigation: Value,
}

impl RunOutput {
    pub fn to_json(&self) -> String {
        serde_json::to_string(&serde_json::json!({
            "final_state": self.final_state,
            "state_hash": self.state_hash,
            "hash_log": self.hash_log,
            "snapshots": self.snapshots,
            "navigation": self.navigation,
        }))
        .unwrap_or_else(|_| "{\"error\":\"serialization\"}".to_string())
    }
}

fn is_lower_hex_64(s: &str) -> bool {
    s.len() == 64
        && s.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
}

fn validate_replay(replay: &Value) -> Result<(i64, &Map<String, Value>), SimError> {
    const ALLOWED: [&str; 10] = [
        "sim_replay", "seed", "ticks", "comment", "entities", "initial", "events",
        "expect_state_hash", "expect", "expect_error",
    ];
    if let Some(obj) = replay.as_object() {
        for key in obj.keys() {
            if !ALLOWED.contains(&key.as_str()) {
                return Err(SimError::new(
                    "E_UNKNOWN_FIELD",
                    format!("unknown replay field {key:?}"),
                ));
            }
        }
    } else {
        return Err(SimError::new("E_REPLAY_SHAPE", "a replay is a JSON object"));
    }
    if replay.get("sim_replay").and_then(Value::as_str) != Some("0.1") {
        return Err(SimError::new("E_REPLAY_VERSION", "unsupported sim_replay version"));
    }
    let ticks = replay
        .get("ticks")
        .and_then(Value::as_i64)
        .filter(|t| (0..=MAX_TICKS).contains(t))
        .ok_or_else(|| SimError::new("E_TICKS_RANGE", format!("ticks must be 0..{MAX_TICKS}")))?;
    if let Some(seed) = replay.get("seed") {
        if seed.as_i64().is_none() {
            return Err(SimError::new("E_SEED_TYPE", "seed must be an integer"));
        }
    }

    let entities = replay
        .get("entities")
        .and_then(Value::as_object)
        .filter(|e| !e.is_empty())
        .ok_or_else(|| SimError::new("E_ENTITIES_SHAPE", "entities must be a non-empty object"))?;
    for (name, entry) in entities {
        if !is_identifier(name) {
            return Err(SimError::new("E_ENTITY_ENTRY", format!("bad entity name {name:?}")));
        }
        let Some(entry) = entry.as_object() else {
            return Err(SimError::new("E_ENTITY_ENTRY", format!("entity {name:?} needs an object")));
        };
        let contract = entry.get("contract").and_then(Value::as_object);
        match contract {
            None => {
                return Err(SimError::new(
                    "E_ENTITY_ENTRY",
                    format!("entity {name:?} needs an inline contract object"),
                ))
            }
            Some(contract) => {
                if contract.get("sim_contract").and_then(Value::as_str) != Some("0.1") {
                    return Err(SimError::new(
                        "E_CONTRACT_VERSION",
                        format!("entity {name:?}: unsupported sim_contract version"),
                    ));
                }
                for field in ["state", "affordances", "parameters"] {
                    if !contract.contains_key(field) {
                        return Err(SimError::new(
                            "E_CONTRACT_SHAPE",
                            format!("entity {name:?} contract is missing {field}"),
                        ));
                    }
                }
            }
        }
        let pinned = entry.get("contract_sha256").and_then(Value::as_str);
        if !pinned.map(is_lower_hex_64).unwrap_or(false) {
            return Err(SimError::new(
                "E_ENTITY_ENTRY",
                format!("entity {name:?} must pin contract_sha256 (lowercase hex)"),
            ));
        }
    }

    if let Some(initial) = replay.get("initial") {
        let Some(initial) = initial.as_object() else {
            return Err(SimError::new("E_INITIAL_SHAPE", "initial must be an object"));
        };
        for name in initial.keys() {
            if !entities.contains_key(name) {
                return Err(SimError::new(
                    "E_UNKNOWN_ENTITY",
                    format!("initial references unknown entity {name:?}"),
                ));
            }
        }
    }

    if let Some(events) = replay.get("events") {
        let Some(events) = events.as_array() else {
            return Err(SimError::new("E_EVENTS_SHAPE", "events must be a list"));
        };
        for (i, event) in events.iter().enumerate() {
            let arr = event
                .as_array()
                .filter(|a| a.len() == 4)
                .ok_or_else(|| {
                    SimError::new("E_EVENT_SHAPE", format!("event {i} must be [tick, entity, verb, arg]"))
                })?;
            let tick = arr[0]
                .as_i64()
                .ok_or_else(|| SimError::new("E_EVENT_TICK_RANGE", format!("event {i} bad tick")))?;
            if tick < 0 || tick > ticks {
                return Err(SimError::new(
                    "E_EVENT_TICK_RANGE",
                    format!("event {i} tick {tick} outside 0..{ticks}"),
                ));
            }
            let entity = arr[1].as_str().unwrap_or("");
            if !entities.contains_key(entity) {
                return Err(SimError::new(
                    "E_UNKNOWN_ENTITY",
                    format!("event {i} targets unknown entity {entity:?}"),
                ));
            }
            let verb = arr[2].as_str().unwrap_or("");
            if !is_identifier(verb) {
                return Err(SimError::new("E_BAD_VERB", format!("event {i} bad verb {verb:?}")));
            }
        }
    }
    Ok((ticks, entities))
}

fn is_identifier(s: &str) -> bool {
    !s.is_empty()
        && s.chars().next().unwrap().is_ascii_lowercase()
        && s.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

/// The deterministic run over a self-contained replay (contracts inline).
pub fn run_replay_value(replay: &Value) -> Result<RunOutput, SimError> {
    let (ticks, _) = validate_replay(replay)?;

    let entities = replay["entities"].as_object().unwrap();
    let mut contracts: BTreeMap<String, Value> = BTreeMap::new();
    for (name, entry) in entities {
        let contract = entry["contract"].clone();
        let actual = sha256_hex(&canonical_json(&contract));
        let pinned = entry["contract_sha256"].as_str().unwrap_or("");
        if actual != pinned {
            return Err(SimError::new(
                "E_CONTRACT_HASH",
                format!("{name}: contract hash mismatch"),
            ));
        }
        contracts.insert(name.clone(), contract);
    }

    let mut world: BTreeMap<String, EntitySim> = BTreeMap::new();
    for (name, contract) in &contracts {
        let mut sim = EntitySim { state: initial_state(contract), control: Map::new() };
        if let Some(initial) = replay
            .get("initial")
            .and_then(|i| i.get(name))
            .and_then(Value::as_object)
        {
            for (var, value) in initial {
                let coerced = coerce_initial(name, contract, var, value)?;
                sim.state.insert(var.clone(), coerced);
            }
        }
        world.insert(name.clone(), sim);
    }

    let empty: Vec<Value> = Vec::new();
    let events = replay.get("events").and_then(Value::as_array).unwrap_or(&empty);
    let mut order: Vec<usize> = (0..events.len()).collect();
    order.sort_by_key(|&i| events[i][0].as_i64().unwrap_or(0));
    let mut by_tick: BTreeMap<i64, Vec<usize>> = BTreeMap::new();
    for i in order {
        by_tick.entry(events[i][0].as_i64().unwrap_or(0)).or_default().push(i);
    }

    let mut hash_log = Vec::new();
    let mut snapshots = Vec::new();
    for tick in 0..=ticks {
        if let Some(indices) = by_tick.get(&tick) {
            for &i in indices {
                let event = events[i].as_array().unwrap();
                let entity = event[1].as_str().unwrap_or("");
                let verb = event[2].as_str().unwrap_or("");
                let arg = &event[3];
                let contract = contracts.get(entity).unwrap();
                let sim = world.get_mut(entity).unwrap();
                apply_event(contract, entity, sim, verb, arg)?;
            }
        }
        for (name, sim) in world.iter_mut() {
            step_entity(&contracts[name], sim);
        }
        hash_log.push(world_hash(&world));
        snapshots.push(world_value(&world));
    }

    let navigation = Value::Object(
        contracts
            .iter()
            .map(|(name, contract)| {
                (name.clone(), Value::Bool(blocks_navigation(contract, &world[name].state)))
            })
            .collect(),
    );
    let final_hash = world_hash(&world);
    Ok(RunOutput {
        final_state: world_value(&world),
        state_hash: final_hash,
        hash_log,
        snapshots,
        navigation,
    })
}

/// Python's json parser rejects NaN/Infinity via parse_constant; serde_json
/// rejects them at parse with a generic error. Detect the tokens first so
/// both kernels return the same code.
fn reject_non_finite(text: &str) -> Result<(), SimError> {
    for token in text.split(|c: char| matches!(c, ',' | '[' | ']' | '{' | '}' | ':' | ' ' | '\t' | '\n' | '\r')) {
        if matches!(token, "NaN" | "Infinity" | "-Infinity") {
            return Err(SimError::new(
                "E_NON_FINITE",
                format!("non-finite constant {token} is not valid JSON"),
            ));
        }
    }
    Ok(())
}

pub fn parse_strict(text: &str) -> Result<Value, SimError> {
    reject_non_finite(text)?;
    serde_json::from_str(text)
        .map_err(|e| SimError::new("E_INVALID_JSON", format!("not valid JSON: {e}")))
}

/// Native path: run a replay file from disk (self-contained).
pub fn run_replay_str(replay_json: &str) -> Result<RunOutput, SimError> {
    let replay = parse_strict(replay_json)?;
    run_replay_value(&replay)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn golden_replay() -> String {
        let path =
            concat!(env!("CARGO_MANIFEST_DIR"), "/../../tools/sim/replays/gate_open_destroy.json");
        std::fs::read_to_string(path).expect("golden replay readable")
    }

    #[test]
    fn golden_replay_matches_the_python_kernel() {
        let replay = golden_replay();
        let expected: Value = serde_json::from_str(&replay).unwrap();
        let result = run_replay_str(&replay).unwrap();
        assert_eq!(
            result.state_hash,
            expected["expect_state_hash"].as_str().unwrap(),
            "native kernel must match the committed golden hash"
        );
        assert_eq!(result.navigation["fortress_gate"], Value::Bool(false));
    }

    #[test]
    fn control_intent_changes_the_hash() {
        let mk = |drive: Option<i64>| {
            let mut sim = EntitySim::default();
            sim.state.insert("openness".into(), Value::from(750));
            if let Some(target) = drive {
                sim.control.insert("openness_target".into(), Value::from(target));
            }
            sim
        };
        let mut a = BTreeMap::new();
        a.insert("gate".to_string(), mk(Some(1000)));
        let mut b = BTreeMap::new();
        b.insert("gate".to_string(), mk(None));
        assert_ne!(world_hash(&a), world_hash(&b));
    }

    #[test]
    fn out_of_range_event_tick_is_rejected() {
        let replay = r#"{"sim_replay":"0.1","seed":0,"ticks":5,
            "entities":{"gate":{"contract":{"sim_contract":"0.1","state":{},"affordances":[],"parameters":{}},"contract_sha256":"0000000000000000000000000000000000000000000000000000000000000000"}},
            "initial":{},
            "events":[[6,"gate","open",null]]}"#;
        let err = run_replay_str(replay).unwrap_err();
        assert_eq!(err.code, "E_EVENT_TICK_RANGE");
    }

    #[test]
    fn canonical_json_matches_python_escaping() {
        let v = serde_json::json!({"b—dash": [1, true, null], "a": 0.7});
        assert_eq!(
            canonical_json(&v),
            "{\"a\":0.7,\"b\\u2014dash\":[1,true,null]}"
        );
    }
}

// ---------------------------------------------------------------- wasm ABI

/// Raw wasm exports. Allocation is boxed-slice based so `sim_free` can rebuild
/// the exact allocation from (ptr, len). Input is the raw replay JSON text —
/// contracts are inline, so no document I/O is ever needed.
#[no_mangle]
pub extern "C" fn sim_alloc(len: usize) -> *mut u8 {
    let mut buf = vec![0u8; len].into_boxed_slice();
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

/// # Safety
/// `ptr`/`len` must come from `sim_alloc` or a `sim_run` result.
#[no_mangle]
pub unsafe extern "C" fn sim_free(ptr: *mut u8, len: usize) {
    if !ptr.is_null() {
        let slice = std::ptr::slice_from_raw_parts_mut(ptr, len);
        drop(unsafe { Box::from_raw(slice) });
    }
}

#[no_mangle]
pub extern "C" fn sim_run(in_ptr: *const u8, in_len: usize) -> u64 {
    let input = unsafe { std::slice::from_raw_parts(in_ptr, in_len) };
    let json = std::str::from_utf8(input).unwrap_or("");
    let out = match run_replay_str(json) {
        Ok(result) => result.to_json(),
        Err(err) => serde_json::to_string(&serde_json::json!({
            "error": err.message,
            "code": err.code,
        }))
        .unwrap_or_else(|_| "{\"error\":\"serialization\"}".into()),
    };
    let mut bytes = out.into_bytes().into_boxed_slice();
    let ptr = bytes.as_mut_ptr();
    let len = bytes.len();
    std::mem::forget(bytes);
    ((ptr as u64) << 32) | (len as u64)
}
