# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""`bakex` CLI — the unique command users type.

CLI-01  `bakex version` prints the package version
CLI-02  `bakex serve` invokes uvicorn with the parsed host/port
CLI-03  `bakex serve --port/--host/--reload` are passed through
CLI-04  no command (or bad command) prints help and exits non-zero
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bakex import __version__, cli


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
