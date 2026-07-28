"""Op registry + parameter spec for the bforge Blender runtime.

One decorator declares an operation's name, docs and typed parameters. From that
single declaration we derive:

  * runtime coercion/validation (agents send loose JSON; ops get real types)
  * JSON Schema for MCP `tools/list`
  * OpenAI / llama.cpp function-calling schemas
  * CLI `--help` and argument parsing

Param spec is a compact 3-tuple ``(type, default, description)``. Use
``REQUIRED`` as the default to make a parameter mandatory.

Supported types::

    num int str bool path
    vec2 vec3 color        (color is RGB or RGBA, 0..1)
    num[] int[] str[] obj[]
    enum:a|b|c
    obj                    (free-form dict, used sparingly)
    colorref               (palette name, "#rrggbb", or [r,g,b(,a)] linear)

This module must stay importable inside Blender's Python (3.11+) with no
third-party dependencies.
"""

from __future__ import annotations

import inspect

REQUIRED = object()

OPS: dict[str, "Op"] = {}


class OpError(Exception):
    """Raised by ops for expected, user-facing failures.

    The message is shown verbatim to the agent, so write it the way you would
    write a code review comment: what is wrong, and what to do instead.
    """


class Op:
    __slots__ = ("name", "fn", "summary", "params", "returns", "tags", "mutates", "last_aliases")

    def __init__(self, name, fn, summary, params, returns, tags, mutates):
        self.name = name
        self.fn = fn
        self.summary = summary
        self.params = params
        self.returns = returns
        self.tags = tags
        self.mutates = mutates
        self.last_aliases = []

    # -- schema ---------------------------------------------------------
    def json_schema(self) -> dict:
        props: dict[str, dict] = {}
        required: list[str] = []
        for key, (type_spec, default, desc) in self.params.items():
            entry = _type_to_schema(type_spec)
            entry["description"] = desc
            if default is REQUIRED:
                required.append(key)
            elif default is not None:
                entry["default"] = default
            props[key] = entry
        schema = {"type": "object", "properties": props, "additionalProperties": False}
        if required:
            schema["required"] = required
        return schema

    def describe(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "tags": list(self.tags),
            "mutates": self.mutates,
            "returns": self.returns,
            "inputSchema": self.json_schema(),
        }

    # -- invocation -----------------------------------------------------
    def coerce(self, args: dict) -> dict:
        if not isinstance(args, dict):
            raise OpError(f"{self.name}: arguments must be a JSON object")

        args, self.last_aliases = self._resolve_selector(args)

        unknown = sorted(set(args) - set(self.params))
        if unknown:
            known = ", ".join(sorted(self.params)) or "(none)"
            raise OpError(
                f"{self.name}: unknown parameter(s) {unknown}. Valid parameters: {known}"
            )
        out: dict = {}
        for key, (type_spec, default, _desc) in self.params.items():
            if key in args and args[key] is not None:
                out[key] = _coerce(self.name, key, type_spec, args[key])
            elif default is REQUIRED:
                raise OpError(f"{self.name}: missing required parameter '{key}' ({type_spec})")
            else:
                out[key] = default
        return out


    # -- selector normalisation ------------------------------------------
    #
    # Across 109 ops, "which object do I act on" is spelled five different
    # ways: name (64 ops), object (12), objects (11), target (4), mesh (2).
    # An agent composing a recipe has to remember which spelling each op wants,
    # and a wrong guess costs a whole round-trip. Worse, `material.set` declares
    # BOTH `object` (the target) and `name` (the MATERIAL's name), so the most
    # common guess is silently accepted as something else entirely and fails
    # later with "object name must be a non-empty string, got None".
    #
    # This normalises the spelling and, where it genuinely cannot, says exactly
    # what went wrong instead of failing three frames deep.

    SELECTORS = ("object", "objects", "name", "target", "mesh")
    OUTPUTS = ("out", "path", "file", "filepath", "dest", "output")

    # Groups of parameter names that mean the same thing to a caller. Ops within
    # a group are interchangeable spellings; `strict` names the members that must
    # never be silently reinterpreted (a group member that some ops declare with
    # a DIFFERENT meaning, e.g. `name` = material name in `material.set`).
    ALIAS_GROUPS = (
        {"names": SELECTORS, "primary": ("object", "objects", "target", "mesh"), "noun": "object"},
        {"names": OUTPUTS, "primary": ("out", "path"), "noun": "output path"},
    )

    def _resolve_selector(self, args: dict) -> tuple[dict, list[str]]:
        args = dict(args)
        notes: list[str] = []
        for group in self.ALIAS_GROUPS:
            self._resolve_group(args, group, notes)
        return args, notes

    def _resolve_group(self, args: dict, group: dict, notes: list) -> None:
        names = group["names"]
        declared = [s for s in names if s in self.params]
        if not declared:
            return

        # 1. A spelling this op does not declare -> map it onto the one this op
        #    does declare and the caller left unset. Only when that is
        #    unambiguous; otherwise fall through to the normal unknown-param error.
        for given in [k for k in list(args) if k in names and k not in self.params]:
            free = [s for s in declared if args.get(s) in (None, "", [])]
            if len(free) != 1:
                continue
            target = free[0]
            value = args.pop(given)
            given_value = value
            wants_list = self.params[target][0].endswith("[]")
            if wants_list and not isinstance(value, (list, tuple)):
                value = [value]
            elif not wants_list and isinstance(value, (list, tuple)):
                if len(value) != 1:
                    args[given] = value  # put it back; let the normal error fire
                    continue
                value = value[0]
            args[target] = value
            notes.append(f"{given}={given_value!r} -> {target}")

        # 2. The case aliasing cannot fix: this op declares the canonical
        #    parameter, it is still unset, and the caller supplied a different
        #    spelling that THIS op reads as something else entirely.
        primary = next((s for s in group["primary"] if s in self.params), None)
        if primary and args.get(primary) in (None, "", []):
            confusable = [k for k in names if k != primary and k in args and args[k]]
            if confusable:
                k = confusable[0]
                _, _, desc = self.params[k]
                raise OpError(
                    f"{self.name}: no {group['noun']} given. You passed {k}={args[k]!r}, but in "
                    f"this op '{k}' means \"{desc}\" — the {group['noun']} goes in '{primary}'. "
                    f"Did you mean {primary}={args[k]!r}?"
                )


def op(name, *, summary, params=None, returns="object", tags=(), mutates=True):
    """Register a runtime operation under a dotted ``name`` (e.g. ``prop.crate``)."""

    def deco(fn):
        if name in OPS:
            raise RuntimeError(f"duplicate op name: {name}")
        spec = dict(params or {})
        signature = inspect.signature(fn)
        declared = set(signature.parameters) - {"ctx"}
        if declared != set(spec):
            missing = sorted(set(spec) - declared)
            extra = sorted(declared - set(spec))
            raise RuntimeError(
                f"op {name}: params spec and function signature disagree "
                f"(spec-only={missing}, signature-only={extra})"
            )
        OPS[name] = Op(name, fn, summary, spec, returns, tuple(tags), mutates)
        return fn

    return deco


# ---------------------------------------------------------------------------
# type handling
# ---------------------------------------------------------------------------

_VEC_LEN = {"vec2": 2, "vec3": 3}


def _type_to_schema(type_spec: str) -> dict:
    if type_spec.startswith("enum:"):
        return {"type": "string", "enum": type_spec[5:].split("|")}
    if type_spec in ("vec2", "vec3"):
        n = _VEC_LEN[type_spec]
        return {"type": "array", "items": {"type": "number"}, "minItems": n, "maxItems": n}
    if type_spec == "color":
        return {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 4}
    if type_spec == "num[]":
        return {"type": "array", "items": {"type": "number"}}
    if type_spec == "int[]":
        return {"type": "array", "items": {"type": "integer"}}
    if type_spec == "str[]":
        return {"type": "array", "items": {"type": "string"}}
    if type_spec == "obj[]":
        return {"type": "array", "items": {"type": "object"}}
    if type_spec == "num":
        return {"type": "number"}
    if type_spec == "int":
        return {"type": "integer"}
    if type_spec == "bool":
        return {"type": "boolean"}
    if type_spec == "obj":
        return {"type": "object"}
    if type_spec == "colorref":
        # Either form must work: meta.palette reports linear triples and
        # documents that they can be passed back verbatim, so a string-only
        # colour parameter breaks its own contract.
        return {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "number"},
                 "minItems": 3, "maxItems": 4},
            ]
        }
    if type_spec in ("str", "path"):
        return {"type": "string"}
    raise RuntimeError(f"unknown param type: {type_spec}")


def _coerce(op_name: str, key: str, type_spec: str, value):
    def bad(expected):
        raise OpError(f"{op_name}: parameter '{key}' expected {expected}, got {value!r}")

    if type_spec.startswith("enum:"):
        choices = type_spec[5:].split("|")
        text = str(value)
        if text not in choices:
            raise OpError(
                f"{op_name}: parameter '{key}' must be one of {choices}, got {value!r}"
            )
        return text
    if type_spec in ("vec2", "vec3", "color"):
        if isinstance(value, (int, float)) and type_spec != "color":
            return [float(value)] * _VEC_LEN[type_spec]
        if not isinstance(value, (list, tuple)):
            bad(f"a list of numbers ({type_spec})")
        nums = [float(v) for v in value]
        if type_spec == "color":
            if len(nums) == 3:
                nums.append(1.0)
            if len(nums) != 4:
                bad("3 or 4 numbers (RGB or RGBA, 0..1)")
        elif len(nums) != _VEC_LEN[type_spec]:
            bad(f"{_VEC_LEN[type_spec]} numbers")
        return nums
    if type_spec.endswith("[]"):
        if not isinstance(value, (list, tuple)):
            bad(f"a list ({type_spec})")
        inner = type_spec[:-2]
        return [_coerce(op_name, key, inner, v) for v in value]
    if type_spec == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad("a number")
        return float(value)
    if type_spec == "int":
        if isinstance(value, bool):
            bad("an integer")
        if isinstance(value, float) and not value.is_integer():
            bad("a whole number")
        if not isinstance(value, (int, float)):
            bad("an integer")
        return int(value)
    if type_spec == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        bad("a boolean")
    if type_spec == "obj":
        if not isinstance(value, dict):
            bad("an object")
        return value
    if type_spec == "colorref":
        if isinstance(value, (list, tuple)):
            nums = [float(v) for v in value]
            if len(nums) not in (3, 4):
                bad("3 or 4 numbers (linear RGB or RGBA), a palette name, or #rrggbb")
            return nums
        return str(value)
    return str(value)


def dispatch(ctx, name: str, args: dict):
    target = OPS.get(name)
    if target is None:
        near = sorted(n for n in OPS if n.split(".")[0] == name.split(".")[0])
        hint = f" Ops in '{name.split('.')[0]}': {near}" if near else ""
        raise OpError(f"unknown op '{name}'.{hint} Call 'meta.ops' for the full list.")
    return target.fn(ctx, **target.coerce(args))


def catalog() -> list[dict]:
    return [OPS[name].describe() for name in sorted(OPS)]
