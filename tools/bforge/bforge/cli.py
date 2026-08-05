"""bforge command line — the front door for humans, shells and CI.

    bforge doctor                             # is Blender wired up?
    bforge ops [--tag prop] [--search rock]   # what can it do?
    bforge help prop.crate                    # how do I call this?
    bforge run prop.barrel height=1.2 seed=4 --render out.png
    bforge script recipe.json                 # batch of ops from a file
    bforge make crate_a --recipe prop.crate --param size=[1,1,1] --export
    bforge catalog --refresh                  # regenerate the committed catalog
    bforge schema --format openai > tools.json

`run` takes loose ``key=value`` pairs and coerces them: JSON when it parses,
otherwise a bare string. So ``size=[1,2,1]``, ``seed=4``, ``smooth=true`` and
``material=wood`` all do the obvious thing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import schema as schema_mod  # noqa: E402
from bforge.client import DaemonError, Forge, ForgeError, find_blender  # noqa: E402


def parse_params(pairs) -> dict:
    args: dict = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"bad parameter '{pair}' — use key=value")
        key, _, raw = pair.partition("=")
        try:
            args[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            args[key.strip()] = raw
    return args


def _forge(args) -> Forge:
    return Forge(
        blender=getattr(args, "blender", None),
        workdir=getattr(args, "workdir", None) or ".",
        out_dir=getattr(args, "out_dir", None),
        verbose=getattr(args, "verbose", False),
    )


def _emit(payload, as_json: bool):
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(json.dumps(payload, indent=2, default=str))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_doctor(args) -> int:
    problems = []
    try:
        binary = find_blender(args.blender)
        print(f"blender      : {binary}")
    except DaemonError as exc:
        print(f"blender      : NOT FOUND — {exc}")
        return 1

    try:
        catalog = schema_mod.load_catalog()
        print(f"catalog      : {len(catalog)} ops ({schema_mod.CATALOG_PATH.name})")
    except FileNotFoundError:
        print("catalog      : missing (run `bforge catalog --refresh`)")
        problems.append("catalog")

    started = time.time()
    forge = _forge(args)
    try:
        info = forge.start()
        boot = time.time() - started
        print(
            f"daemon       : ready in {boot:.1f}s — Blender {info['blender']}, "
            f"Python {info['python']}, {info['ops']} ops"
        )
        result = forge.call("build.box", name="doctor_box", size=[1, 1, 1])
        print(f"build.box    : {result['triangles']} tris, bounds {result['bounds']['size']}")
        shot = forge.call(
            "render.view", out="_doctor/probe.png", resolution=128, samples=4, _timeout=600
        )
        print(f"render       : {shot['engine']} -> {shot['rel']}")
        check = forge.call("check.asset", triangle_budget=5000)
        print(
            f"validate     : {'ok' if check['ok'] else 'FAILED'} "
            f"({check['errors']} errors, {check['warnings']} warnings)"
        )
        glb = forge.call("export.gltf", out="_doctor/probe.glb", strict=False)
        print(f"export       : {glb['bytes']} bytes -> {glb['rel']}")
    except (ForgeError, DaemonError) as exc:
        print(f"FAILED       : {exc}")
        return 1
    finally:
        forge.stop()
    print("\nbforge doctor: all good" if not problems else f"\nissues: {problems}")
    return 0


def cmd_ops(args) -> int:
    catalog = _catalog(args)
    rows = schema_mod.compact(catalog, args.tag, args.search)
    if args.json:
        _emit(rows, True)
        return 0
    width = max((len(r["name"]) for r in rows), default=10)
    for row in rows:
        print(f"{row['name']:<{width}}  {row['summary'][:110]}")
    print(f"\n{len(rows)} ops")
    return 0


def cmd_help(args) -> int:
    catalog = _catalog(args)
    match = next((o for o in catalog if o["name"] == args.op), None)
    if match is None:
        near = [o["name"] for o in catalog if args.op.split(".")[0] in o["name"]]
        print(f"no op '{args.op}'." + (f" Did you mean: {near}" if near else ""))
        return 1
    if args.json:
        _emit(match, True)
        return 0
    print(f"{match['name']}\n\n  {match['summary']}\n")
    print(f"  tags: {', '.join(match['tags']) or '-'}   mutates: {match['mutates']}\n")
    props = match["inputSchema"].get("properties", {})
    required = set(match["inputSchema"].get("required", []))
    for key, spec in props.items():
        kind = " | ".join(spec["enum"]) if "enum" in spec else spec.get("type", "any")
        default = "REQUIRED" if key in required else json.dumps(spec.get("default"))
        print(f"  {key:<18} {kind:<28} = {default}")
        print(f"    {spec.get('description', '')}")
    return 0


def cmd_run(args) -> int:
    params = parse_params(args.params)
    forge = _forge(args)
    try:
        forge.start()
        if args.reset:
            forge.call("session.reset")
        started = time.time()
        result = forge.call(args.op, _timeout=args.timeout, **params)
        elapsed = time.time() - started
        outputs = {"op": args.op, "ms": int(elapsed * 1000), "result": result}
        if args.render:
            outputs["render"] = forge.call(
                "render.contact_sheet", out=args.render, tile=args.tile, _timeout=900
            )
        if args.export:
            outputs["export"] = forge.call("export.gltf", out=args.export, strict=False)
        _emit(outputs, True)
        return 0
    except (ForgeError, DaemonError) as exc:
        print(json.dumps({"op": args.op, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    finally:
        forge.stop()


def cmd_script(args) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"no such file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = data["steps"] if isinstance(data, dict) else data
    forge = _forge(args)
    try:
        forge.start()
        results = forge.script(steps, stop_on_error=not args.keep_going)
        _emit(results, True)
        return 1 if any(not r.get("ok") for r in results) else 0
    finally:
        forge.stop()


def cmd_make(args) -> int:
    """Recipe -> finished asset: generate, validate, collide, render, export."""
    params = parse_params(args.param)
    forge = _forge(args)
    try:
        forge.start()
        forge.call("session.reset")
        built = forge.call(args.recipe, name=args.asset_id, _timeout=args.timeout, **params)
        target = built.get("name", args.asset_id)
        steps = {"build": built}

        if args.collision != "none":
            steps["collision"] = forge.call("gameready.collision", name=target, mode=args.collision)
        if args.lods > 0:
            steps["lod"] = forge.call("gameready.lod", name=target, levels=args.lods)
        steps["budget"] = forge.call(
            "gameready.budget", profile=args.profile, asset_class=args.asset_class
        )
        steps["critique"] = forge.call("check.critique")
        if args.export:
            steps["export"] = forge.call(
                "export.asset",
                asset_id=args.asset_id,
                engine=args.engine,
                category=args.asset_class if args.asset_class != "hero" else "prop",
                ai_prompt=args.prompt,
                contact_sheet=True,
                strict=False,
                _timeout=1200,
            )
        _emit({"asset_id": args.asset_id, "steps": steps}, True)
        findings = steps["critique"].get("findings", [])
        errors = [f for f in findings if f["severity"] == "error"]
        return 1 if errors else 0
    except (ForgeError, DaemonError) as exc:
        print(json.dumps({"asset_id": args.asset_id, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    finally:
        forge.stop()


def cmd_cook(args) -> int:
    """Compile a Recipe IR document: cache check -> worker -> gates -> proof."""
    from bforge import recipe as recipe_mod

    def factory() -> Forge:
        return _forge(args)

    try:
        proof = recipe_mod.cook(
            args.file,
            cache_dir=args.cache_dir,
            no_cache=args.no_cache,
            forge_factory=factory,
            allow_unpinned=args.allow_unpinned,
        )
    except recipe_mod.RecipeError as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    _emit(proof, True)
    return 0


def cmd_catalog(args) -> int:
    if args.refresh:
        forge = _forge(args)
        try:
            forge.start()
            ops = forge.catalog()
        finally:
            forge.stop()
        path = schema_mod.save_catalog(ops)
        print(f"wrote {len(ops)} ops -> {path}")
        if args.reference:
            reference = Path(args.reference)
            reference.parent.mkdir(parents=True, exist_ok=True)
            reference.write_text(schema_mod.markdown_reference(ops), encoding="utf-8")
            print(f"wrote reference -> {reference}")
        return 0
    catalog = _catalog(args)
    print(json.dumps({"count": len(catalog), "ops": [o["name"] for o in catalog]}, indent=2))
    return 0


def cmd_schema(args) -> int:
    catalog = _catalog(args)
    if args.format == "openai":
        payload = schema_mod.to_openai(catalog)
    elif args.format == "anthropic":
        payload = schema_mod.to_anthropic(catalog)
    elif args.format == "mcp":
        payload = schema_mod.to_mcp_tools(catalog)
    elif args.format == "markdown":
        print(schema_mod.markdown_reference(catalog))
        return 0
    else:
        payload = catalog
    print(json.dumps(payload, indent=2))
    return 0


def cmd_mcp(args) -> int:
    from bforge import mcp_server

    return mcp_server.main(
        ["--workdir", args.workdir or ".", "--tools", args.tools]
        + (["--out", args.out_dir] if args.out_dir else [])
        + (["--self-check"] if args.self_check else [])
    )


def _catalog(args) -> list[dict]:
    try:
        return schema_mod.load_catalog()
    except FileNotFoundError:
        forge = _forge(args)
        try:
            forge.start()
            return forge.catalog()
        finally:
            forge.stop()


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bforge", description=__doc__.split("\n")[0])
    parser.add_argument("--blender", default=None, help="Path to the Blender executable")
    parser.add_argument("--workdir", default=None, help="Project root (default: cwd)")
    parser.add_argument("--out-dir", default=None, help="Output directory for generated files")
    parser.add_argument("--verbose", action="store_true", help="Echo Blender's stderr")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Verify the whole chain end to end").set_defaults(func=cmd_doctor)

    ops = sub.add_parser("ops", help="List operations")
    ops.add_argument("--tag", default="")
    ops.add_argument("--search", default="")
    ops.add_argument("--json", action="store_true")
    ops.set_defaults(func=cmd_ops)

    helper = sub.add_parser("help", help="Show one op's parameters")
    helper.add_argument("op")
    helper.add_argument("--json", action="store_true")
    helper.set_defaults(func=cmd_help)

    run = sub.add_parser("run", help="Run a single op")
    run.add_argument("op")
    run.add_argument("params", nargs="*", help="key=value pairs (JSON values allowed)")
    run.add_argument("--reset", action="store_true", help="session.reset first")
    run.add_argument("--render", default="", help="Also render a contact sheet to this path")
    run.add_argument("--tile", type=int, default=400)
    run.add_argument("--export", default="", help="Also export a GLB to this path")
    run.add_argument("--timeout", type=float, default=600)
    run.set_defaults(func=cmd_run)

    script = sub.add_parser("script", help="Run a JSON list of ops")
    script.add_argument("file")
    script.add_argument("--keep-going", action="store_true")
    script.set_defaults(func=cmd_script)

    make = sub.add_parser("make", help="Recipe to finished, validated, exported asset")
    make.add_argument("asset_id")
    make.add_argument("--recipe", required=True, help="e.g. prop.crate")
    make.add_argument("--param", action="append", default=[], help="key=value (repeatable)")
    make.add_argument("--profile", default="browser_webgpu")
    make.add_argument(
        "--asset-class", default="prop", choices=["prop", "character", "environment", "hero"]
    )
    make.add_argument(
        "--collision",
        default="convex",
        choices=["none", "box", "convex", "simplified", "cylinder", "sphere", "capsule"],
    )
    make.add_argument("--lods", type=int, default=0)
    make.add_argument("--engine", default="godot")
    make.add_argument("--export", action="store_true")
    make.add_argument("--prompt", default="", help="Recorded in the asset's provenance")
    make.add_argument("--timeout", type=float, default=900)
    make.set_defaults(func=cmd_make)

    cook = sub.add_parser(
        "cook", help="Compile a Recipe IR document (ADR 0017): cache, gates, proof capsule"
    )
    cook.add_argument("file", help="Path to the recipe JSON")
    cook.add_argument("--cache-dir", default=None, help="Override the content-addressed cache root")
    cook.add_argument("--no-cache", action="store_true", help="Rebuild even when a pass is cached")
    cook.add_argument(
        "--allow-unpinned",
        action="store_true",
        help="Permit a Blender other than blender-lock.toml's pin; results are never cached",
    )
    cook.set_defaults(func=cmd_cook)

    catalog = sub.add_parser("catalog", help="Show or regenerate the committed op catalog")
    catalog.add_argument("--refresh", action="store_true")
    catalog.add_argument("--reference", default="", help="Also write a markdown reference here")
    catalog.set_defaults(func=cmd_catalog)

    schema_cmd = sub.add_parser("schema", help="Export tool schemas for any LLM runtime")
    schema_cmd.add_argument(
        "--format",
        default="openai",
        choices=["openai", "anthropic", "mcp", "markdown", "raw"],
    )
    schema_cmd.set_defaults(func=cmd_schema)

    mcp = sub.add_parser("mcp", help="Run the MCP stdio server")
    mcp.add_argument("--tools", choices=["grouped", "full"], default="grouped")
    mcp.add_argument("--self-check", action="store_true")
    mcp.set_defaults(func=cmd_mcp)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
