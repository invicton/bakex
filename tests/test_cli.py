# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""`bakex` CLI — the unique command users type.

CLI-01  `bakex version` prints the package version
CLI-02  `bakex serve` invokes uvicorn with the parsed host/port
CLI-03  `bakex serve --port/--host/--reload` are passed through
CLI-04  no command (or bad command) prints help and exits non-zero
CLI-05  `bakex validate` passes a real blueprint and exits 0
CLI-06  `bakex validate` fails an invalid/missing blueprint and exits 1
CLI-07  `bakex validate --json` emits machine-readable results
CLI-08  `bakex build <file>` loads the blueprint and drives run_build
CLI-09  `bakex build <unknown>` exits 1 without calling run_build
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bakex import __version__, cli

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VALID_BLUEPRINT = _REPO_ROOT / "profiles" / "templates" / "ubuntu22-cis-l1-aws.yaml"


def test_version_prints_version(capsys):
    rc = cli.main(["version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_serve_invokes_uvicorn_defaults():
    fake_uvicorn = MagicMock()
    with patch.dict("sys.modules", {"uvicorn": fake_uvicorn}):
        rc = cli.main(["serve"])
    assert rc == 0
    fake_uvicorn.run.assert_called_once()
    args, kwargs = fake_uvicorn.run.call_args
    assert args[0] == "bakex.main:app"
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8000


def test_serve_passes_through_host_port_reload():
    fake_uvicorn = MagicMock()
    with patch.dict("sys.modules", {"uvicorn": fake_uvicorn}):
        rc = cli.main(["serve", "--host", "127.0.0.1", "--port", "9000", "--reload"])
    assert rc == 0
    _, kwargs = fake_uvicorn.run.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9000
    assert kwargs["reload"] is True


def test_no_command_shows_help_nonzero(capsys):
    rc = cli.main([])
    assert rc != 0
    combined = capsys.readouterr()
    assert "bakex" in (combined.out + combined.err).lower()


def test_unknown_command_errors():
    with pytest.raises(SystemExit) as exc:
        cli.main(["frobnicate"])
    assert exc.value.code != 0


# --- validate ---------------------------------------------------------------


def test_validate_valid_blueprint_exits_zero(capsys):
    rc = cli.main(["validate", str(_VALID_BLUEPRINT)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "1/1" in out


def test_validate_missing_file_exits_one(capsys):
    rc = cli.main(["validate", "/no/such/blueprint.yaml"])
    assert rc == 1
    assert "file not found" in capsys.readouterr().out


def test_validate_invalid_blueprint_exits_one(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("kind: HardeningBlueprint\nmetadata:\n  name: broken\n")
    rc = cli.main(["validate", str(bad)])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().out


def test_validate_json_output(capsys):
    import json

    rc = cli.main(["validate", str(_VALID_BLUEPRINT), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["valid"] is True
    assert payload[0]["name"] == "ubuntu22-cis-l1-aws"


def test_validate_mixed_batch_exits_one(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: a blueprint\n")
    rc = cli.main(["validate", str(_VALID_BLUEPRINT), str(bad)])
    assert rc == 1


# --- build ------------------------------------------------------------------


def test_build_drives_run_build_and_maps_status(tmp_path):
    """`bakex build <file>` loads the blueprint and calls run_build; a COMPLETE
    job maps to exit 0. run_build is mocked — no real provisioning."""
    from bakex.core import builder as build_service

    def fake_run_build(profile, output_dir, job):
        job.status = build_service.BuildStatus.COMPLETE
        return job

    with patch.object(build_service, "run_build", new_callable=AsyncMock, side_effect=fake_run_build) as m:
        rc = cli.main(["build", str(_VALID_BLUEPRINT), "--output-dir", str(tmp_path)])

    assert rc == 0
    m.assert_called_once()
    called_profile = m.call_args.args[0]
    assert called_profile.metadata.name == "ubuntu22-cis-l1-aws"


def test_build_failed_job_exits_one(tmp_path):
    from bakex.core import builder as build_service

    def fake_run_build(profile, output_dir, job):
        job.status = build_service.BuildStatus.FAILED
        job.error = "provider boom"
        return job

    with patch.object(build_service, "run_build", new_callable=AsyncMock, side_effect=fake_run_build):
        rc = cli.main(["build", str(_VALID_BLUEPRINT), "--output-dir", str(tmp_path)])
    assert rc == 1


def test_build_unknown_blueprint_exits_one_without_building(capsys):
    from bakex.core import builder as build_service

    with patch.object(build_service, "run_build") as m:
        rc = cli.main(["build", "definitely-not-a-real-profile-name"])
    assert rc == 1
    m.assert_not_called()
    assert "not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Baking vocabulary — memorable aliases, nothing renamed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [("bake", "build"), ("proof", "validate"), ("pantry", "blueprints")],
)
def test_alias_maps_to_canonical(alias, canonical):
    assert cli._ALIASES[alias] == canonical


@pytest.mark.parametrize(("alias", "canonical"), [("proof", "validate"), ("pantry", "blueprints")])
def test_alias_dispatches_instead_of_falling_through_to_help(alias, canonical, capsys):
    """The regression the normalisation step exists to prevent.

    argparse reports the spelling the user typed, so dispatching on `args.command`
    directly sends an aliased invocation to the help text and exit code 2 — a
    silent no-op that looks like a usage error.
    """
    args = [alias] if alias == "pantry" else [alias, str(_VALID_BLUEPRINT)]
    rc = cli.main(args)
    assert rc == 0, f"`bakex {alias}` fell through instead of running {canonical}"
    assert capsys.readouterr().out.strip(), f"`bakex {alias}` produced no output"


def test_proof_and_validate_are_equivalent(capsys):
    rc_canonical = cli.main(["validate", str(_VALID_BLUEPRINT)])
    out_canonical = capsys.readouterr().out
    rc_alias = cli.main(["proof", str(_VALID_BLUEPRINT)])
    out_alias = capsys.readouterr().out
    assert rc_canonical == rc_alias == 0
    assert out_canonical == out_alias


def test_proof_reports_failure_like_validate(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("kind: NotABlueprint\n")
    assert cli.main(["validate", str(bad)]) == 1
    capsys.readouterr()
    assert cli.main(["proof", str(bad)]) == 1


def test_bake_reaches_the_build_path():
    """`bake` must invoke the builder, not the help text."""
    from bakex.core import builder as build_service

    with patch.object(build_service, "run_build") as m:
        rc = cli.main(["bake", "definitely-not-a-real-profile-name"])
    assert rc == 1  # unknown blueprint, but it got as far as resolution
    m.assert_not_called()


def test_help_advertises_the_aliases(capsys):
    """Aliases must be discoverable by reading --help, not by memorising a glossary."""
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for rendered in ("build (bake)", "validate (proof)", "blueprints (pantry)"):
        assert rendered in out


# ---------------------------------------------------------------------------
# profiles / pantry
# ---------------------------------------------------------------------------


def test_profiles_lists_bundled_blueprints(capsys):
    rc = cli.main(["blueprints"])
    assert rc == 0
    assert "bundled blueprint(s)" in capsys.readouterr().out


def test_profiles_json_is_machine_readable(capsys):
    import json

    rc = cli.main(["blueprints", "--json"])
    assert rc == 0
    entries = json.loads(capsys.readouterr().out)
    assert entries and all({"name", "os", "provider", "path"} <= e.keys() for e in entries)


def test_every_listed_name_is_buildable(capsys):
    """profiles and build must not drift — each printed name must resolve."""
    import json

    cli.main(["blueprints", "--json"])
    entries = json.loads(capsys.readouterr().out)
    for entry in entries:
        assert cli._resolve_blueprint(entry["name"]) is not None, (
            f"`bakex blueprints` lists {entry['name']!r} but `bakex build` cannot resolve it"
        )
