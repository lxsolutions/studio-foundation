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
/// 0.1 lists affordance names and relies on the built-in door; 0.2 declares its
/// own semantics. Both run through the same interpreter (ADR 0021).
pub const SUPPORTED_CONTRACTS: [&str; 2] = ["0.1", "0.2"];

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

// ------------------------------------------------------- declared semantics
//
// A line-for-line mirror of tools/sim/kernel.py's interpreter (ADR 0021). The
// kernel used to hardcode a door: six verbs, four state vars, one integrator,
// and E_NO_SEMANTICS for everything else — while World IR let an author
// declare any state schema and any affordance. Semantics are now DECLARED in a
// closed vocabulary: guards plus an ordered list of effects, no loops, no
// expressions, no escape hatch (ADR 0018 rules out model-emitted executable
// code reaching production state).
//
// The door is written in that vocabulary below and a v0.1 contract desugars
// into it, so there is one execution path and the frozen conformance corpus
// re-derives byte-identical golden hashes through the general interpreter.
//
// Divergence between this and the Python twin is the failure mode that matters,
// so the structure is kept deliberately parallel even where Rust would prefer
// something else.

fn door_profile() -> &'static Value {
    static PROFILE: std::sync::OnceLock<Value> = std::sync::OnceLock::new();
    PROFILE.get_or_init(|| {
        serde_json::json!({
            "affordances": {
                "open": {
                    "arg": "none",
                    // A destroyed gate hangs open; a locked one absorbs the
                    // command. A guard that does not hold is a no-op.
                    "guards": [
                        {"var": "destroyed", "equals": false},
                        {"var": "locked", "equals": false}
                    ],
                    "effects": [
                        {"op": "set_control", "control": "openness_target",
                         "value": {"const": QUANTUM}}
                    ]
                },
                "close": {
                    "arg": "none",
                    "guards": [{"var": "destroyed", "equals": false}],
                    "effects": [
                        {"op": "set_control", "control": "openness_target",
                         "value": {"const": 0}}
                    ]
                },
                "lock": {
                    "arg": "none",
                    "effects": [{"op": "set", "var": "locked", "value": {"const": true}}]
                },
                "unlock": {
                    "arg": "none",
                    "effects": [{"op": "set", "var": "locked", "value": {"const": false}}]
                },
                "attack": {
                    "arg": "count",
                    "requires": ["health"],
                    "effects": [
                        {"op": "add", "var": "health", "value": {"arg": true}, "sign": -1,
                         "clamp": {"min": {"const": 0}}},
                        // Effects apply in order and read what the previous one
                        // left, so these see the health just written.
                        {"op": "set", "var": "destroyed", "value": {"const": true},
                         "when": [{"var": "health", "equals": 0},
                                  {"var": "destroyed", "exists": true}]},
                        {"op": "set_control", "control": "openness_target",
                         "value": {"const": QUANTUM},
                         "when": [{"var": "health", "equals": 0},
                                  {"var": "destroyed", "exists": true}]}
                    ]
                },
                "repair": {
                    "arg": "count",
                    "requires": ["health"],
                    "effects": [
                        {"op": "add", "var": "health", "value": {"arg": true}, "sign": 1,
                         "clamp": {"max": {"param": "max_health", "default": 100}}},
                        {"op": "set", "var": "destroyed", "value": {"const": false},
                         "when": [{"var": "health", "gt": {"const": 0}},
                                  {"var": "destroyed", "exists": true}]}
                    ]
                }
            },
            "integrators": [
                {"var": "openness", "toward": "openness_target",
                 "rate": {"param": "open_rate_milli", "default": 250}}
            ]
        })
    })
}

pub const EFFECT_OPS: [&str; 4] = ["set", "set_control", "add", "toggle"];
pub const ARG_KINDS: [&str; 2] = ["none", "count"];
pub const GUARD_TESTS: [&str; 4] = ["equals", "exists", "gt", "lt"];
pub const VALUE_SOURCES: [&str; 4] = ["const", "arg", "param", "var"];
pub const WIRE_KEYS: [&str; 3] = ["name", "when", "then"];
/// A wire holds rather than pulses, so it may only target affordances whose
/// effects merely set (ADR 0024). Mirrors LEVEL_SAFE_OPS in kernel.py.
pub const LEVEL_SAFE_OPS: [&str; 2] = ["set", "set_control"];

/// Storage says how a value is held; the TYPE says what may be written to it
/// and compared against it. Mirrors `STORAGE_TYPE` in kernel.py.
fn storage_type(storage: &str) -> Option<&'static str> {
    match storage {
        "milli_i64" | "i64" => Some("int"),
        "bool" => Some("bool"),
        "string" => Some("string"),
        _ => None,
    }
}

/// A JSON integer in i64 range. serde_json parses anything wider as u64 or
/// f64 and `as_i64` refuses both, which is exactly Python's `_is_int`.
fn is_int(value: &Value) -> bool {
    value.as_i64().is_some()
}

/// The type of a bare literal, or None when it is not one the kernel holds.
fn literal_type(value: &Value) -> Option<&'static str> {
    match value {
        Value::Bool(_) => Some("bool"),
        Value::Number(_) if is_int(value) => Some("int"),
        Value::String(_) => Some("string"),
        _ => None,
    }
}

/// The contract's declared semantics, or the door profile it desugars to.
/// Resolved once per run by `run_replay_value`, never per tick.
fn semantics(contract: &Value) -> Value {
    if let Some(declared) = contract.get("semantics") {
        return declared.clone();
    }
    let names = affordances(contract);
    let mut chosen = Map::new();
    if let Some(profile) = door_profile()["affordances"].as_object() {
        for (verb, spec) in profile {
            if names.contains(&verb.as_str()) {
                chosen.insert(verb.clone(), spec.clone());
            }
        }
    }
    serde_json::json!({
        "affordances": Value::Object(chosen),
        "integrators": door_profile()["integrators"].clone(),
    })
}

/// What an absent state var compares as: the zero of the literal's type. Only
/// the v0.1 door can reach this (a v0.2 contract declares every var it names
/// and `initial_state` seeds them all), but both kernels must agree here —
/// Python says `True == 1` and serde_json does not.
fn typed_zero(like: &Value) -> Value {
    match like {
        Value::Bool(_) => Value::Bool(false),
        Value::Number(_) => Value::from(0),
        Value::String(_) => Value::String(String::new()),
        _ => Value::Null,
    }
}

/// A declared value: a bare literal, or one of {const, arg, param, var}.
/// Shapes are validated at load, so nothing here has to guess.
fn resolve(
    source: &Value,
    arg: Option<i64>,
    state: &Map<String, Value>,
    params: &Map<String, Value>,
) -> Value {
    let Some(obj) = source.as_object() else {
        return source.clone(); // bare literal
    };
    if let Some(constant) = obj.get("const") {
        return constant.clone();
    }
    if obj.contains_key("arg") {
        return Value::from(arg.unwrap_or(0));
    }
    if let Some(name) = obj.get("param").and_then(Value::as_str) {
        let default = obj.get("default").and_then(Value::as_i64).unwrap_or(0);
        return Value::from(params.get(name).and_then(Value::as_i64).unwrap_or(default));
    }
    if let Some(name) = obj.get("var").and_then(Value::as_str) {
        return state.get(name).cloned().unwrap_or_else(|| Value::from(0));
    }
    Value::Null
}

fn guard_holds(guard: &Value, state: &Map<String, Value>, params: &Map<String, Value>) -> bool {
    let Some(obj) = guard.as_object() else { return true };
    let Some(var) = obj.get("var").and_then(Value::as_str) else { return true };
    if let Some(expected) = obj.get("exists").and_then(Value::as_bool) {
        return state.contains_key(var) == expected;
    }
    for test in ["equals", "gt", "lt"] {
        let Some(spec) = obj.get(test) else { continue };
        let wanted = resolve(spec, None, state, params);
        let actual = state.get(var).cloned().unwrap_or_else(|| typed_zero(&wanted));
        if test == "equals" {
            return actual == wanted; // serde_json equality is type-strict
        }
        if actual.is_boolean() || wanted.is_boolean() {
            return false; // ordering on booleans is not a question with an answer
        }
        let (a, b) = (actual.as_i64().unwrap_or(0), wanted.as_i64().unwrap_or(0));
        return if test == "gt" { a > b } else { a < b };
    }
    true
}

fn guards_hold(
    guards: Option<&Value>,
    state: &Map<String, Value>,
    params: &Map<String, Value>,
) -> bool {
    let Some(list) = guards.and_then(Value::as_array) else { return true };
    list.iter().all(|guard| guard_holds(guard, state, params))
}

fn apply_effect(
    effect: &Value,
    arg: Option<i64>,
    state: &mut Map<String, Value>,
    control: &mut Map<String, Value>,
    params: &Map<String, Value>,
) {
    if !guards_hold(effect.get("when"), state, params) {
        return;
    }
    let op = effect.get("op").and_then(Value::as_str).unwrap_or("");
    let value_spec = effect.get("value").unwrap_or(&Value::Null);
    match op {
        "set" => {
            if let Some(var) = effect.get("var").and_then(Value::as_str) {
                let value = resolve(value_spec, arg, state, params);
                state.insert(var.to_string(), value);
            }
        }
        "set_control" => {
            if let Some(name) = effect.get("control").and_then(Value::as_str) {
                let value = resolve(value_spec, arg, state, params);
                control.insert(name.to_string(), value);
            }
        }
        "toggle" => {
            if let Some(var) = effect.get("var").and_then(Value::as_str) {
                let current = state.get(var).and_then(Value::as_bool).unwrap_or(false);
                state.insert(var.to_string(), Value::Bool(!current));
            }
        }
        "add" => {
            let Some(var) = effect.get("var").and_then(Value::as_str) else { return };
            let sign = effect.get("sign").and_then(Value::as_i64).unwrap_or(1);
            // Saturating, and the Python kernel saturates in the same two
            // places, so the two cannot drift apart at the edge of i64.
            let delta = resolve(value_spec, arg, state, params)
                .as_i64()
                .unwrap_or(0)
                .saturating_mul(sign);
            let mut next = get_i64(state, var).saturating_add(delta);
            if let Some(clamp) = effect.get("clamp").and_then(Value::as_object) {
                if let Some(low) = clamp.get("min") {
                    next = next.max(resolve(low, arg, state, params).as_i64().unwrap_or(0));
                }
                if let Some(high) = clamp.get("max") {
                    next = next.min(resolve(high, arg, state, params).as_i64().unwrap_or(0));
                }
            }
            state.insert(var.to_string(), Value::from(next));
        }
        _ => {}
    }
}

fn apply_event(
    contract: &Value,
    declared: &Value,
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
    let Some(spec) = declared.get("affordances").and_then(|a| a.get(verb)) else {
        return Err(SimError::new(
            "E_NO_SEMANTICS",
            format!("{entity}: affordance {verb:?} is declared but has no semantics"),
        ));
    };

    let kind = spec.get("arg").and_then(Value::as_str).unwrap_or("none");
    if kind == "none" && !arg.is_null() {
        return Err(SimError::new(
            "E_ARGUMENT_DOMAIN",
            format!("{entity}: {verb} takes no argument"),
        ));
    }
    let mut amount: Option<i64> = None;
    if kind == "count" {
        match arg.as_i64() {
            Some(n) if (0..=MAX_EVENT_ARG).contains(&n) => amount = Some(n),
            Some(_) => {
                return Err(SimError::new(
                    "E_ARGUMENT_RANGE",
                    format!("{entity}: {verb} amount outside 0..{MAX_EVENT_ARG}"),
                ))
            }
            None => {
                return Err(SimError::new(
                    "E_ARGUMENT_TYPE",
                    format!("{entity}: {verb} needs a nonnegative integer amount"),
                ))
            }
        }
    }

    let parameters = params(contract);
    if let Some(required) = spec.get("requires").and_then(Value::as_array) {
        for var in required.iter().filter_map(Value::as_str) {
            if !sim.state.contains_key(var) {
                return Err(SimError::new(
                    "E_NO_SEMANTICS",
                    format!("{entity}: {verb} needs a {var:?} state var"),
                ));
            }
        }
    }
    if !guards_hold(spec.get("guards"), &sim.state, parameters) {
        return Ok(()); // a guard that does not hold is a no-op, not a failure
    }
    if let Some(effects) = spec.get("effects").and_then(Value::as_array) {
        for effect in effects {
            apply_effect(effect, amount, &mut sim.state, &mut sim.control, parameters);
        }
    }
    Ok(())
}

fn step_entity(contract: &Value, declared: &Value, sim: &mut EntitySim) {
    let Some(integrators) = declared.get("integrators").and_then(Value::as_array) else {
        return;
    };
    let parameters = params(contract);
    for integrator in integrators {
        let Some(var) = integrator.get("var").and_then(Value::as_str) else { continue };
        if !sim.state.contains_key(var) {
            continue; // nothing to integrate on an entity without the variable
        }
        let current = get_i64(&sim.state, var);
        let target = integrator
            .get("toward")
            .and_then(Value::as_str)
            .and_then(|name| sim.control.get(name))
            .and_then(Value::as_i64)
            .unwrap_or(current);
        let rate = integrator
            .get("rate")
            .map(|spec| resolve(spec, None, &sim.state, parameters))
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let next = if current < target {
            current.saturating_add(rate).min(target)
        } else if current > target {
            current.saturating_sub(rate).max(target)
        } else {
            current
        };
        sim.state.insert(var.to_string(), Value::from(next));
    }
}

/// Shape the contract before either kernel reads a value from it.
///
/// Mirrors `_validate_contract` in kernel.py. Everything here is a place the
/// two kernels used to be able to disagree on malformed input — a float
/// parameter Python truncates and this kernel ignores, a storage type one
/// knows and the other does not. Each is refused up front with a stable code,
/// so parity holds for rejections too.
fn validate_contract(entity: &str, contract: &Map<String, Value>) -> Result<(), SimError> {
    let version = contract.get("sim_contract").and_then(Value::as_str).unwrap_or("");
    if !SUPPORTED_CONTRACTS.contains(&version) {
        return Err(SimError::new(
            "E_CONTRACT_VERSION",
            format!("entity {entity:?}: unsupported sim_contract version"),
        ));
    }
    let reject = |message: String| {
        SimError::new("E_CONTRACT_SHAPE", format!("entity {entity:?} {message}"))
    };
    for field in ["state", "affordances", "parameters"] {
        if !contract.contains_key(field) {
            return Err(reject(format!("contract is missing {field}")));
        }
    }

    let Some(state) = contract["state"].as_object() else {
        return Err(reject("state must be an object".into()));
    };
    for (var, spec) in state {
        let known = spec
            .get("storage")
            .and_then(Value::as_str)
            .and_then(storage_type)
            .is_some();
        if !known {
            return Err(reject(format!(
                "state var {var:?} needs a storage of [milli_i64, i64, bool, string]"
            )));
        }
    }

    let identifiers = contract["affordances"]
        .as_array()
        .map(|list| list.iter().all(|v| v.as_str().map(is_identifier).unwrap_or(false)))
        .unwrap_or(false);
    if !identifiers {
        return Err(reject("affordances must be a list of snake_case identifiers".into()));
    }

    let Some(parameters) = contract["parameters"].as_object() else {
        return Err(reject("parameters must be an object".into()));
    };
    for (name, value) in parameters {
        if name != "navigation" && !is_int(value) {
            return Err(reject(format!("parameter {name:?} must be an i64 integer")));
        }
    }
    if let Some(nav) = parameters.get("navigation") {
        let Some(nav) = nav.as_object() else {
            return Err(reject("parameters.navigation must be an object".into()));
        };
        if let Some(flag) = nav.get("never_blocks_when_destroyed") {
            if !flag.is_boolean() {
                return Err(reject(
                    "parameters.navigation.never_blocks_when_destroyed must be a bool".into(),
                ));
            }
        }
        if let Some(rules) = nav.get("blocks_below") {
            let Some(rules) = rules.as_array() else {
                return Err(reject("parameters.navigation.blocks_below must be a list".into()));
            };
            for rule in rules {
                let shaped = rule
                    .as_object()
                    .map(|r| {
                        r.get("var").and_then(Value::as_str).is_some()
                            && r.get("threshold_milli").map(is_int).unwrap_or(false)
                    })
                    .unwrap_or(false);
                if !shaped {
                    return Err(reject(
                        "parameters.navigation.blocks_below entries need a var and an i64 threshold_milli".into(),
                    ));
                }
            }
        }
    }

    // The version says where meaning comes from: 0.1 inherits the door, 0.2
    // declares its own. A contract that says one and does the other is a
    // contract two readers can interpret differently.
    let has_semantics = contract.contains_key("semantics");
    if version == "0.1" && has_semantics {
        return Err(reject(
            "a 0.1 contract inherits the door and cannot carry semantics; declare sim_contract 0.2".into(),
        ));
    }
    if version == "0.2" && !has_semantics {
        return Err(reject("a 0.2 contract must declare a semantics block".into()));
    }
    validate_semantics(entity, contract)
}

/// The state schema a semantics block is typed against (ADR 0021). A
/// line-for-line mirror of the closures inside `_validate_semantics` in
/// kernel.py: same checks, same order, same stable code.
struct SemanticsSchema<'a> {
    entity: &'a str,
    var_types: BTreeMap<&'a str, &'static str>,
    int_params: Vec<&'a str>,
    listed: Vec<&'a str>,
}

impl<'a> SemanticsSchema<'a> {
    fn reject(&self, message: String) -> SimError {
        SimError::new("E_SEMANTICS_SHAPE", format!("entity {:?} {message}", self.entity))
    }

    fn only_keys(
        &self,
        obj: &Map<String, Value>,
        allowed: &[&str],
        what: &str,
    ) -> Result<(), SimError> {
        let unknown: Vec<&String> =
            obj.keys().filter(|key| !allowed.contains(&key.as_str())).collect();
        if unknown.is_empty() {
            Ok(())
        } else {
            Err(self.reject(format!("{what} has unknown keys {unknown:?}")))
        }
    }

    /// A value source of the expected type: a bare literal or one of VALUE_SOURCES.
    fn check_value(
        &self,
        value: Option<&Value>,
        what: &str,
        expected: &str,
        arg_kind: &str,
    ) -> Result<(), SimError> {
        let not_a_source = || {
            self.reject(format!(
                "{what} must be a bool, i64 integer or string literal, or a value source"
            ))
        };
        let Some(value) = value else { return Err(not_a_source()) };
        let actual: &str = match value.as_object() {
            None => literal_type(value).ok_or_else(not_a_source)?,
            Some(obj) => {
                let sources: Vec<&str> =
                    VALUE_SOURCES.iter().copied().filter(|key| obj.contains_key(*key)).collect();
                if sources.len() != 1 {
                    return Err(self.reject(format!("{what} needs exactly one of {VALUE_SOURCES:?}")));
                }
                let kind = sources[0];
                let allowed: &[&str] =
                    if kind == "param" { &["param", "default"] } else { std::slice::from_ref(&kind) };
                self.only_keys(obj, allowed, what)?;
                match kind {
                    "const" => literal_type(&obj["const"]).ok_or_else(|| {
                        self.reject(format!("{what}.const must be a bool, an i64 integer or a string"))
                    })?,
                    "arg" => {
                        if obj["arg"] != Value::Bool(true) {
                            return Err(self.reject(format!("{what}.arg must be true")));
                        }
                        if arg_kind != "count" {
                            return Err(self.reject(format!(
                                "{what} reads the event argument, but the affordance takes none"
                            )));
                        }
                        "int"
                    }
                    "param" => {
                        let Some(name) = obj["param"].as_str() else {
                            return Err(self.reject(format!("{what}.param must name a parameter")));
                        };
                        if let Some(default) = obj.get("default") {
                            if !is_int(default) {
                                return Err(self.reject(format!("{what}.default must be an i64 integer")));
                            }
                        }
                        if !self.int_params.contains(&name) && !obj.contains_key("default") {
                            return Err(self.reject(format!(
                                "{what} reads parameter {name:?}, which is not set and has no default"
                            )));
                        }
                        "int"
                    }
                    _ => {
                        let name = obj["var"].as_str();
                        match name.and_then(|n| self.var_types.get(n)) {
                            Some(var_type) => var_type,
                            None => {
                                return Err(self.reject(format!(
                                    "{what} reads undeclared state var {:?}",
                                    obj["var"]
                                )))
                            }
                        }
                    }
                }
            }
        };
        if actual != expected {
            return Err(self.reject(format!("{what} must be {expected}, not {actual}")));
        }
        Ok(())
    }

    fn check_guards(
        &self,
        guards: Option<&Value>,
        what: &str,
        arg_kind: &str,
    ) -> Result<(), SimError> {
        let Some(guards) = guards else { return Ok(()) };
        let Some(list) = guards.as_array() else {
            return Err(self.reject(format!("{what} must be a list")));
        };
        for (i, guard) in list.iter().enumerate() {
            let label = format!("{what}[{i}]");
            let var = guard.as_object().and_then(|g| g.get("var")).and_then(Value::as_str);
            let (Some(obj), Some(var)) = (guard.as_object(), var) else {
                return Err(self.reject(format!("{label} needs a var")));
            };
            let Some(var_type) = self.var_types.get(var).copied() else {
                return Err(self.reject(format!("{label} tests undeclared state var {var:?}")));
            };
            let tests: Vec<&str> =
                GUARD_TESTS.iter().copied().filter(|test| obj.contains_key(*test)).collect();
            if tests.len() != 1 {
                return Err(self.reject(format!("{label} needs exactly one of {GUARD_TESTS:?}")));
            }
            let test = tests[0];
            self.only_keys(obj, &["var", test], &label)?;
            match test {
                "exists" => {
                    if !obj["exists"].is_boolean() {
                        return Err(self.reject(format!("{label}.exists must be a bool")));
                    }
                }
                "equals" => {
                    self.check_value(obj.get("equals"), &format!("{label}.equals"), var_type, arg_kind)?
                }
                _ => {
                    if var_type != "int" {
                        return Err(self.reject(format!(
                            "{label}.{test} orders state var {var:?}, which is not an integer"
                        )));
                    }
                    self.check_value(obj.get(test), &format!("{label}.{test}"), "int", arg_kind)?;
                }
            }
        }
        Ok(())
    }

    fn check_effect(&self, effect: &Value, label: &str, arg_kind: &str) -> Result<(), SimError> {
        let op = effect.as_object().and_then(|e| e.get("op")).and_then(Value::as_str).unwrap_or("");
        let (Some(obj), true) = (effect.as_object(), EFFECT_OPS.contains(&op)) else {
            return Err(self.reject(format!("{label}.op must be one of {EFFECT_OPS:?}")));
        };
        let keys: &[&str] = match op {
            "set" => &["op", "var", "value", "when"],
            "set_control" => &["op", "control", "value", "when"],
            "add" => &["op", "var", "value", "sign", "clamp", "when"],
            _ => &["op", "var", "when"],
        };
        self.only_keys(obj, keys, label)?;
        self.check_guards(obj.get("when"), &format!("{label}.when"), arg_kind)?;
        if op == "set_control" {
            let control = obj.get("control").and_then(Value::as_str).unwrap_or("");
            if !is_identifier(control) {
                return Err(self.reject(format!("{label} needs a snake_case control name")));
            }
            return self.check_value(obj.get("value"), &format!("{label}.value"), "int", arg_kind);
        }
        let var = obj.get("var").and_then(Value::as_str).unwrap_or("");
        let Some(var_type) = self.var_types.get(var).copied() else {
            return Err(self.reject(format!("{label} writes undeclared state var {:?}", obj.get("var"))));
        };
        match op {
            "toggle" => {
                if var_type != "bool" {
                    return Err(self.reject(format!(
                        "{label} toggles state var {var:?}, which is not a bool"
                    )));
                }
                Ok(())
            }
            "set" => self.check_value(obj.get("value"), &format!("{label}.value"), var_type, arg_kind),
            _ => {
                if var_type != "int" {
                    return Err(self.reject(format!(
                        "{label} adds to state var {var:?}, which is not an integer"
                    )));
                }
                self.check_value(obj.get("value"), &format!("{label}.value"), "int", arg_kind)?;
                let sign = obj.get("sign").map(Value::as_i64).unwrap_or(Some(1));
                if !matches!(sign, Some(1) | Some(-1)) {
                    return Err(self.reject(format!("{label}.sign must be 1 or -1")));
                }
                if let Some(clamp) = obj.get("clamp") {
                    let Some(clamp) = clamp.as_object() else {
                        return Err(self.reject(format!("{label}.clamp must be an object")));
                    };
                    self.only_keys(clamp, &["min", "max"], &format!("{label}.clamp"))?;
                    for bound in ["min", "max"] {
                        if clamp.contains_key(bound) {
                            self.check_value(
                                clamp.get(bound),
                                &format!("{label}.clamp.{bound}"),
                                "int",
                                arg_kind,
                            )?;
                        }
                    }
                }
                Ok(())
            }
        }
    }
}

/// Reject a malformed semantics block at load, not mid-replay.
///
/// Mirrors `_validate_semantics` in tools/sim/kernel.py. Everything the
/// interpreter reads is checked here, so effect evaluation can assume
/// well-formedness: a replay that fails halfway leaves a partial world and a
/// hash nobody can reproduce, which is the one outcome a deterministic kernel
/// must never produce. The block is TYPED against the state schema, and
/// unknown keys are refused everywhere — a `guard` where `guards` was meant
/// would otherwise vanish silently.
fn validate_semantics(entity: &str, contract: &Map<String, Value>) -> Result<(), SimError> {
    let Some(declared) = contract.get("semantics") else { return Ok(()) };
    let schema = SemanticsSchema {
        entity,
        var_types: contract["state"]
            .as_object()
            .map(|state| {
                state
                    .iter()
                    .filter_map(|(var, spec)| {
                        spec.get("storage")
                            .and_then(Value::as_str)
                            .and_then(storage_type)
                            .map(|t| (var.as_str(), t))
                    })
                    .collect()
            })
            .unwrap_or_default(),
        int_params: contract["parameters"]
            .as_object()
            .map(|p| p.keys().map(String::as_str).filter(|k| *k != "navigation").collect())
            .unwrap_or_default(),
        listed: contract["affordances"]
            .as_array()
            .map(|a| a.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default(),
    };

    let Some(declared) = declared.as_object() else {
        return Err(schema.reject("semantics must be an object".into()));
    };
    schema.only_keys(declared, &["affordances", "integrators"], "semantics")?;
    let empty_map = Map::new();
    let empty_list: Vec<Value> = Vec::new();
    let affordances = match declared.get("affordances") {
        None => &empty_map,
        Some(a) => a
            .as_object()
            .ok_or_else(|| schema.reject("semantics.affordances must be an object".into()))?,
    };
    let integrators = match declared.get("integrators") {
        None => &empty_list,
        Some(i) => i
            .as_array()
            .ok_or_else(|| schema.reject("semantics.integrators must be a list".into()))?,
    };

    for (verb, spec) in affordances {
        let what = format!("semantics.affordances.{verb}");
        if !schema.listed.contains(&verb.as_str()) {
            return Err(schema.reject(format!("{what} is not in the contract's affordance list")));
        }
        let Some(spec) = spec.as_object() else {
            return Err(schema.reject(format!("{what} must be an object")));
        };
        schema.only_keys(spec, &["arg", "guards", "requires", "effects"], &what)?;
        let arg_kind = match spec.get("arg") {
            None => "none",
            Some(kind) => kind.as_str().unwrap_or(""),
        };
        if !ARG_KINDS.contains(&arg_kind) {
            return Err(schema.reject(format!("{what}.arg must be one of {ARG_KINDS:?}")));
        }
        if let Some(requires) = spec.get("requires") {
            let Some(list) = requires.as_array() else {
                return Err(schema.reject(format!("{what}.requires must be a list")));
            };
            for required in list {
                let declared_var = required
                    .as_str()
                    .map(|name| schema.var_types.contains_key(name))
                    .unwrap_or(false);
                if !declared_var {
                    return Err(schema.reject(format!(
                        "{what} requires undeclared state var {required:?}"
                    )));
                }
            }
        }
        schema.check_guards(spec.get("guards"), &format!("{what}.guards"), arg_kind)?;
        if let Some(effects) = spec.get("effects") {
            let Some(list) = effects.as_array() else {
                return Err(schema.reject(format!("{what}.effects must be a list")));
            };
            for (i, effect) in list.iter().enumerate() {
                schema.check_effect(effect, &format!("{what}.effects[{i}]"), arg_kind)?;
            }
        }
    }
    let missing: Vec<&str> = schema
        .listed
        .iter()
        .copied()
        .filter(|verb| !affordances.contains_key(*verb))
        .collect();
    if !missing.is_empty() {
        return Err(schema.reject(format!(
            "semantics.affordances must cover every listed affordance; missing {missing:?}"
        )));
    }

    for (i, integrator) in integrators.iter().enumerate() {
        let label = format!("semantics.integrators[{i}]");
        let Some(obj) = integrator.as_object() else {
            return Err(schema.reject(format!("{label} must be an object")));
        };
        schema.only_keys(obj, &["var", "toward", "rate"], &label)?;
        let var = obj.get("var").and_then(Value::as_str).unwrap_or("");
        let Some(var_type) = schema.var_types.get(var).copied() else {
            return Err(schema.reject(format!(
                "{label} integrates undeclared state var {:?}",
                obj.get("var")
            )));
        };
        if var_type != "int" {
            return Err(schema.reject(format!(
                "{label} integrates state var {var:?}, which is not an integer"
            )));
        }
        let toward = obj.get("toward").and_then(Value::as_str).unwrap_or("");
        if !is_identifier(toward) {
            return Err(schema.reject(format!(
                "{label} needs a snake_case control name to move toward"
            )));
        }
        schema.check_value(obj.get("rate"), &format!("{label}.rate"), "int", "none")?;
    }
    Ok(())
}

// ------------------------------------------------------ clauses and wires
//
// A clause is a guard over the WORLD: one entity, one state var or control,
// one test against a literal. Wires (ADR 0024) speak this vocabulary, and so
// does the Python prover's property language, so both kernels must agree on
// exactly what a clause admits. Mirrors validate_clause / clause_holds /
// validate_wires / apply_wires in kernel.py.

fn validate_clause(
    clause: &Value,
    label: &str,
    contracts: &BTreeMap<&str, &Map<String, Value>>,
    reject: &dyn Fn(String) -> SimError,
) -> Result<(), SimError> {
    let Some(obj) = clause.as_object() else {
        return Err(reject(format!("{label} must be an object")));
    };
    let entity = obj.get("entity").and_then(Value::as_str).unwrap_or("");
    let Some(contract) = contracts.get(entity) else {
        return Err(reject(format!("{label} names unknown entity {:?}", obj.get("entity"))));
    };
    let tests: Vec<&str> = GUARD_TESTS.iter().copied().filter(|t| obj.contains_key(*t)).collect();
    if tests.len() != 1 {
        return Err(reject(format!("{label} needs exactly one of {GUARD_TESTS:?}")));
    }
    let test = tests[0];
    if obj.contains_key("var") == obj.contains_key("control") {
        return Err(reject(format!("{label} reads either a var or a control")));
    }
    let (var_type, allowed): (&str, [&str; 3]) = if obj.contains_key("var") {
        let var = obj["var"].as_str().unwrap_or("");
        let declared = contract
            .get("state")
            .and_then(Value::as_object)
            .and_then(|state| state.get(var))
            .and_then(|spec| spec.get("storage"))
            .and_then(Value::as_str)
            .and_then(storage_type);
        let Some(var_type) = declared else {
            return Err(reject(format!(
                "{label} reads undeclared state var {:?} of {entity}",
                obj["var"]
            )));
        };
        (var_type, ["entity", "var", test])
    } else {
        let control = obj["control"].as_str().unwrap_or("");
        if !is_identifier(control) {
            return Err(reject(format!("{label} control must be a snake_case name")));
        }
        ("int", ["entity", "control", test])
    };
    let unknown: Vec<&String> =
        obj.keys().filter(|key| !allowed.contains(&key.as_str())).collect();
    if !unknown.is_empty() {
        return Err(reject(format!("{label} has unknown keys {unknown:?}")));
    }
    let literal = &obj[test];
    if test == "exists" {
        if !literal.is_boolean() {
            return Err(reject(format!("{label}.exists must be a bool")));
        }
        return Ok(());
    }
    let Some(literal_type) = literal_type(literal) else {
        return Err(reject(format!(
            "{label}.{test} must be a bool, i64 integer or string literal"
        )));
    };
    if (test == "gt" || test == "lt") && (var_type != "int" || literal_type != "int") {
        return Err(reject(format!("{label}.{test} orders integers only")));
    }
    if test == "equals" && literal_type != var_type {
        return Err(reject(format!(
            "{label}.equals compares a {var_type} with a {literal_type}"
        )));
    }
    Ok(())
}

/// One clause against the world, with the kernel's own guard semantics.
fn clause_holds(clause: &Value, world: &BTreeMap<String, EntitySim>) -> bool {
    let Some(obj) = clause.as_object() else { return false };
    let entity = obj.get("entity").and_then(Value::as_str).unwrap_or("");
    let Some(sim) = world.get(entity) else { return false };
    let (table, var) = match obj.get("control") {
        Some(control) => (&sim.control, control.clone()),
        None => (&sim.state, obj.get("var").cloned().unwrap_or(Value::Null)),
    };
    let mut guard = Map::new();
    guard.insert("var".into(), var);
    for test in GUARD_TESTS {
        if let Some(value) = obj.get(test) {
            guard.insert(test.into(), value.clone());
        }
    }
    guard_holds(&Value::Object(guard), table, &Map::new())
}

/// Reject a malformed wiring block at load (`E_WIRE_SHAPE`). Mirrors
/// validate_wires in kernel.py: entities exist, vars are declared and typed,
/// verbs are declared affordances with semantics, arguments fit the verb,
/// and every target affordance only sets.
fn validate_wires(
    wires: &Value,
    contracts: &BTreeMap<&str, &Map<String, Value>>,
) -> Result<(), SimError> {
    let reject = |message: String| SimError::new("E_WIRE_SHAPE", format!("wires {message}"));
    let Some(list) = wires.as_array() else {
        return Err(reject("must be a list".into()));
    };
    let mut names: Vec<&str> = Vec::new();
    for (i, wire) in list.iter().enumerate() {
        let label = format!("[{i}]");
        let Some(obj) = wire.as_object() else {
            return Err(reject(format!("{label} must be an object")));
        };
        let unknown: Vec<&String> =
            obj.keys().filter(|key| !WIRE_KEYS.contains(&key.as_str())).collect();
        if !unknown.is_empty() {
            return Err(reject(format!("{label} has unknown keys {unknown:?}")));
        }
        let name = obj.get("name").and_then(Value::as_str).unwrap_or("");
        if !is_identifier(name) {
            return Err(reject(format!("{label} needs a snake_case name")));
        }
        if names.contains(&name) {
            return Err(reject(format!("{label} repeats the name {name:?}")));
        }
        names.push(name);
        let when = obj.get("when").and_then(Value::as_array).filter(|w| !w.is_empty());
        let Some(when) = when else {
            return Err(reject(format!("{label}.when must be a non-empty list of clauses")));
        };
        for (j, clause) in when.iter().enumerate() {
            validate_clause(clause, &format!("{label}.when[{j}]"), contracts, &reject)?;
        }
        let then = obj.get("then").and_then(Value::as_array).filter(|t| !t.is_empty());
        let Some(then) = then else {
            return Err(reject(format!("{label}.then must be a non-empty list of verbs")));
        };
        for (j, act) in then.iter().enumerate() {
            let lab = format!("{label}.then[{j}]");
            let shaped = act
                .as_object()
                .map(|a| {
                    a.len() == 3
                        && a.contains_key("entity")
                        && a.contains_key("verb")
                        && a.contains_key("arg")
                })
                .unwrap_or(false);
            if !shaped {
                return Err(reject(format!("{lab} needs exactly entity, verb and arg")));
            }
            let act = act.as_object().unwrap();
            let entity = act["entity"].as_str().unwrap_or("");
            let Some(contract) = contracts.get(entity) else {
                return Err(reject(format!("{lab} targets unknown entity {:?}", act["entity"])));
            };
            let verb = act["verb"].as_str().unwrap_or("");
            let listed = contract
                .get("affordances")
                .and_then(Value::as_array)
                .map(|a| a.iter().any(|v| v.as_str() == Some(verb)))
                .unwrap_or(false);
            if !listed {
                return Err(reject(format!(
                    "{lab} targets undeclared affordance {verb:?} of {entity}"
                )));
            }
            let declared = semantics(&Value::Object((*contract).clone()));
            let Some(spec) = declared.get("affordances").and_then(|a| a.get(verb)) else {
                return Err(reject(format!(
                    "{lab} targets {verb:?} of {entity}, which has no semantics"
                )));
            };
            let pulses = spec
                .get("effects")
                .and_then(Value::as_array)
                .map(|effects| {
                    effects.iter().any(|e| {
                        !LEVEL_SAFE_OPS.contains(&e.get("op").and_then(Value::as_str).unwrap_or(""))
                    })
                })
                .unwrap_or(false);
            if pulses {
                return Err(reject(format!(
                    "{lab} targets {verb:?} of {entity}, which adds or toggles; a wire holds, it does not pulse"
                )));
            }
            let kind = spec.get("arg").and_then(Value::as_str).unwrap_or("none");
            let arg = &act["arg"];
            if kind == "none" && !arg.is_null() {
                return Err(reject(format!("{lab}: {verb} takes no argument")));
            }
            let amount_ok = arg.as_i64().map(|n| (0..=MAX_EVENT_ARG).contains(&n)).unwrap_or(false);
            if kind == "count" && !amount_ok {
                return Err(reject(format!(
                    "{lab}: {verb} needs an integer amount 0..{MAX_EVENT_ARG}"
                )));
            }
        }
    }
    Ok(())
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
    const ALLOWED: [&str; 11] = [
        "sim_replay", "seed", "ticks", "comment", "entities", "initial", "events",
        "expect_state_hash", "wires", "expect", "expect_error",
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
        match entry.get("contract").and_then(Value::as_object) {
            None => {
                return Err(SimError::new(
                    "E_ENTITY_ENTRY",
                    format!("entity {name:?} needs an inline contract object"),
                ))
            }
            Some(contract) => validate_contract(name, contract)?,
        }
        let pinned = entry.get("contract_sha256").and_then(Value::as_str);
        if !pinned.map(is_lower_hex_64).unwrap_or(false) {
            return Err(SimError::new(
                "E_ENTITY_ENTRY",
                format!("entity {name:?} must pin contract_sha256 (lowercase hex)"),
            ));
        }
    }
    if let Some(wires) = replay.get("wires") {
        let contracts: BTreeMap<&str, &Map<String, Value>> = entities
            .iter()
            .filter_map(|(name, entry)| {
                entry.get("contract").and_then(Value::as_object).map(|c| (name.as_str(), c))
            })
            .collect();
        validate_wires(wires, &contracts)?;
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

    // Resolved once per run: the declared block, or the door profile a v0.1
    // contract desugars to. The Python kernel does this in the same place.
    let declared: BTreeMap<String, Value> =
        contracts.iter().map(|(name, contract)| (name.clone(), semantics(contract))).collect();

    let empty: Vec<Value> = Vec::new();
    let events = replay.get("events").and_then(Value::as_array).unwrap_or(&empty);
    let wires: Vec<Value> = replay.get("wires").and_then(Value::as_array).cloned().unwrap_or_default();
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
                apply_event(contract, &declared[entity], entity, sim, verb, arg)?;
            }
        }
        // The world's couplings (ADR 0024): after the tick's events, before
        // integration, in declared order; later wires see what earlier ones did.
        for wire in &wires {
            let holds = wire
                .get("when")
                .and_then(Value::as_array)
                .map(|when| when.iter().all(|clause| clause_holds(clause, &world)))
                .unwrap_or(false);
            if !holds {
                continue;
            }
            if let Some(then) = wire.get("then").and_then(Value::as_array) {
                for act in then {
                    let target = act.get("entity").and_then(Value::as_str).unwrap_or("");
                    let verb = act.get("verb").and_then(Value::as_str).unwrap_or("");
                    let arg = act.get("arg").unwrap_or(&Value::Null);
                    let contract = contracts.get(target).unwrap();
                    let sim = world.get_mut(target).unwrap();
                    apply_event(contract, &declared[target], target, sim, verb, arg)?;
                }
            }
        }
        for (name, sim) in world.iter_mut() {
            step_entity(&contracts[name], &declared[name], sim);
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
