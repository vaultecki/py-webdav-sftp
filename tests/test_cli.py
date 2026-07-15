import sys

import pytest

import cli


def test_parse_args_requires_host():
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_parse_args_defaults():
    args = cli.parse_args(["--host", "myserver"])
    assert args.host == "myserver"
    assert args.ssh_config == "~/.ssh/config"
    assert args.remote_path == "/tmp"
    assert args.port == 8080
    assert args.pool_size == 3
    assert args.connection_timeout == 10
    assert args.drive_letter is None
    assert args.log_level == "INFO"


def test_parse_args_custom_values():
    args = cli.parse_args([
        "--host", "myserver",
        "--ssh-config", "/tmp/config",
        "--remote-path", "/srv/data",
        "--port", "9090",
        "--pool-size", "5",
        "--connection-timeout", "30",
        "--drive-letter", "X",
        "--log-level", "DEBUG",
    ])
    assert args.host == "myserver"
    assert args.ssh_config == "/tmp/config"
    assert args.remote_path == "/srv/data"
    assert args.port == 9090
    assert args.pool_size == 5
    assert args.connection_timeout == 30
    assert args.drive_letter == "X"
    assert args.log_level == "DEBUG"


def test_parse_args_rejects_invalid_log_level():
    with pytest.raises(SystemExit):
        cli.parse_args(["--host", "myserver", "--log-level", "VERBOSE"])


def test_run_returns_error_code_for_broken_ssh_config(tmp_path):
    """run() darf bei einem Konfigurationsfehler nicht versuchen, einen
    Port zu binden - muss sofort mit Fehlercode zurueckkehren."""
    missing_config = tmp_path / "does-not-exist"
    args = cli.parse_args(["--host", "myserver", "--ssh-config", str(missing_config)])

    assert cli.run(args) == 1


def test_main_wires_parse_args_and_run(monkeypatch):
    captured = {}

    def fake_run(args):
        captured["host"] = args.host
        return 0

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["cli.py", "--host", "myserver"])

    assert cli.main() == 0
    assert captured["host"] == "myserver"
