# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""The `bakex` command-line interface.

A thin, dependency-light (stdlib argparse) entry point so operators — and AI
agents driving BakeX over a shell — have a first-class command:

    bakex serve                 Run the app + API
    bakex version               Print the build
    bakex validate <file...>    Validate blueprint YAML against the schema
    bakex build <file|name>     Build a hardened image from a blueprint
    bakex blueprints            List the bundled blueprints `build` accepts by name

`validate` is deliberately cheap (pydantic + YAML only, no server deps) so it is
safe to run in CI and fast for agents to poll. `build` defers its heavier imports
until invoked.

Baking vocabulary
-----------------
Pre-configuring an image at build time is *baking*; configuring it at boot is
*frying*. That is the industry's own term for what BakeX does, so the CLI answers
to it — `bake`, `proof`, and `pantry` are aliases for `build`, `validate`, and
`blueprints`. Nothing is renamed: the plain verbs stay canonical and are what the
docs use, because a name in someone's CI log should not require knowing the
metaphor. The aliases appear in `--help` as `build (bake)`, so they are found by
reading, not by memorising a glossary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bakex import __version__

#: Memorable alias -> canonical command. argparse reports the string the user
#: actually typed, so dispatch must resolve through this or an aliased invocation
#: falls through to the help text and exits 2.
_ALIASES = {"bake": "build", "proof": "validate", "pantry": "blueprints"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bakex",
        description="BakeX — bake a hardened, CIS/STIG-benchmarked golden image from a YAML blueprint.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_serve = sub.add_parser("serve", help="Run the BakeX web app + API")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p_serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev)")

    sub.add_parser("version", help="Print the BakeX version")

    p_blueprints = sub.add_parser(
        "blueprints",
        aliases=["pantry"],
        help="List the bundled blueprints that `build` accepts by name",
    )
    p_blueprints.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON (for CI / agents)",
    )

    p_validate = sub.add_parser(
        "validate",
        aliases=["proof"],
        help="Validate one or more blueprint YAML files against the schema",
    )
    p_validate.add_argument("files", nargs="+", metavar="FILE", help="Blueprint YAML file(s)")
    p_validate.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON results (for CI / agents)",
    )

    p_build = sub.add_parser(
        "build",
        aliases=["bake"],
        help="Build a hardened image from a blueprint file or a bundled blueprint name",
    )
    p_build.add_argument(
        "blueprint",
        metavar="FILE|NAME",
        help="Path to a blueprint YAML file, or the name of a bundled blueprint",
    )
    p_build.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/builds"),
        help="Directory for build artefacts (default: data/builds)",
    )
    p_build.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the final job record as JSON",
    )

    return parser


def _cmd_validate(files: list[str], as_json: bool) -> int:
    """Validate blueprint files. Exit 0 if all valid, 1 if any fail."""
    # Local imports keep `bakex version` free of pydantic/yaml import cost.
    import yaml  # noqa: PLC0415
    from pydantic import ValidationError  # noqa: PLC0415

    from bakex.core.blueprint import load_profile  # noqa: PLC0415

    results: list[dict[str, object]] = []
    ok = True
    for f in files:
        path = Path(f)
        entry: dict[str, object] = {"file": str(path), "valid": False, "error": None}
        try:
            profile = load_profile(path)
            entry["valid"] = True
            entry["name"] = profile.metadata.name
            entry["kind"] = profile.kind
        except FileNotFoundError:
            entry["error"] = "file not found"
            ok = False
        except (yaml.YAMLError, ValidationError, ValueError, TypeError) as exc:
            entry["error"] = str(exc)
            ok = False
        results.append(entry)

    if as_json:
        import json  # noqa: PLC0415

        print(json.dumps(results, indent=2))
    else:
        for entry in results:
            if entry["valid"]:
                print(f"OK    {entry['file']}  ({entry.get('kind')} '{entry.get('name')}')")
            else:
                print(f"ERROR {entry['file']}: {entry['error']}")
        total, passed = len(results), sum(1 for e in results if e["valid"])
        print(f"\n{passed}/{total} blueprint(s) valid.")

    return 0 if ok else 1


def _resolve_blueprint(blueprint: str):
    """Resolve a build target to a loaded profile.

    Accepts either a path to a YAML file or the ``metadata.name`` of a profile
    bundled under ``settings.profiles_dir`` — mirroring the web API's lookup so
    both ``bakex build ./my.yaml`` and ``bakex build ubuntu22-cis-l1-aws`` work.
    """
    from bakex.core.blueprint import list_profiles, load_profile  # noqa: PLC0415

    path = Path(blueprint)
    if path.is_file():
        return load_profile(path)

    from bakex.config import settings  # noqa: PLC0415

    for p in list_profiles(settings.profiles_dir):
        try:
            profile = load_profile(p)
        except Exception:  # noqa: BLE001 — skip unparseable neighbours, keep searching
            continue
        if profile.metadata.name == blueprint:
            return profile
    return None


def _cmd_blueprints(as_json: bool) -> int:
    """List the bundled blueprints that ``build`` accepts by name.

    ``bakex build`` has always taken a bundled blueprint name as well as a path, but
    there was no way to discover those names — you had to already know one. This
    walks the same directory ``_resolve_blueprint`` searches, so the two cannot
    drift: every name printed here is a name ``build`` will accept.
    """
    import json  # noqa: PLC0415

    from bakex.config import settings  # noqa: PLC0415
    from bakex.core.blueprint import list_profiles, load_profile  # noqa: PLC0415

    entries: list[dict] = []
    for path in list_profiles(settings.profiles_dir):
        try:
            profile = load_profile(path)
        except Exception:  # noqa: BLE001 — mirror _resolve_blueprint: skip, keep going
            continue
        entries.append(
            {
                "name": profile.metadata.name,
                "os": profile.target.os,
                "provider": profile.target.provider,
                "description": (profile.metadata.description or "").strip().splitlines()[0]
                if profile.metadata.description
                else "",
                "path": str(path),
            }
        )

    entries.sort(key=lambda e: e["name"])

    if as_json:
        print(json.dumps(entries, indent=2))
        return 0

    if not entries:
        print(f"No bundled blueprints found under {settings.profiles_dir}")
        return 0

    width = max(len(e["name"]) for e in entries)
    for e in entries:
        print(f"{e['name']:<{width}}  {e['os']:<18} {e['provider']}")
    print(f"\n{len(entries)} bundled blueprint(s). Build one with: bakex build <name>")
    return 0


def _cmd_build(blueprint: str, output_dir: Path, as_json: bool) -> int:
    """Build an image from a blueprint. Exit 0 on COMPLETE, 1 otherwise."""
    import asyncio  # noqa: PLC0415

    from bakex.core import builder as build_service  # noqa: PLC0415

    profile = _resolve_blueprint(blueprint)
    if profile is None:
        print(
            f"bakex: blueprint '{blueprint}' not found (not a file, and no bundled blueprint has that name)",
            file=sys.stderr,
        )
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    job = build_service.BuildJob(
        profile_name=profile.metadata.name,
        provider_name=profile.target.provider,
    )
    if not as_json:
        print(f"Building '{profile.metadata.name}' ({profile.target.provider}) → job {job.id}")

    asyncio.run(build_service.run_build(profile, output_dir, job))

    if as_json:
        import json  # noqa: PLC0415

        print(
            json.dumps(
                {
                    "id": job.id,
                    "profile_name": job.profile_name,
                    "provider_name": job.provider_name,
                    "status": job.status.value,
                    "artifact_id": job.result.artifact_id if job.result else None,
                    "error": job.error,
                },
                indent=2,
            )
        )
    else:
        for line in job.log:
            print(line)
        print(f"\nStatus: {job.status.value}")
        if job.error:
            print(f"Error: {job.error}", file=sys.stderr)

    return 0 if job.status == build_service.BuildStatus.COMPLETE else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # argparse reports the spelling the user typed, so `bakex bake` arrives as
    # "bake". Resolve to the canonical name once, here, rather than teaching every
    # branch below about aliases.
    command = _ALIASES.get(args.command, args.command)

    if command == "version":
        print(f"bakex {__version__}")
        return 0

    if command == "serve":
        import uvicorn  # noqa: PLC0415 — deferred so `bakex version` needs no server deps

        uvicorn.run("bakex.main:app", host=args.host, port=args.port, reload=args.reload)
        return 0

    if command == "blueprints":
        return _cmd_blueprints(args.as_json)

    if command == "validate":
        return _cmd_validate(args.files, args.as_json)

    if command == "build":
        return _cmd_build(args.blueprint, args.output_dir, args.as_json)

    # No command given: show help, signal misuse.
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
