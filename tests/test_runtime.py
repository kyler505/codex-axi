import subprocess
import sys
import types

import pytest

from codex_axi.errors import AxiError
from codex_axi.runtime import (
    RuntimeCapabilities,
    open_proxy_connection,
    probe_runtime,
    read_rate_limits,
)


def completed(args, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, code, stdout, stderr)


def test_probe_reports_stopped_daemon_without_claiming_health():
    def run(args):
        if args[-1] == "version":
            return completed(args, 1, stderr="failed to connect: No such file or directory")
        return completed(args, stdout="codex-cli 0.144.3")

    result = probe_runtime(run=run, which=lambda _: "/bin/codex")
    assert result.daemon_state == "stopped"
    assert result.proxy_available is True
    assert result.shared_transport_available is False
    assert "direct stdio only" in result.shared_transport_detail
    assert result.detail == "managed daemon is not running"
    assert "No such file" not in result.detail
    assert result.authenticated is True


def test_probe_reports_unauthenticated_codex():
    def run(args):
        if tuple(args[-2:]) == ("login", "status"):
            return completed(args, 1, stderr="Not logged in")
        if args[-1] == "version":
            return completed(args, 1, stderr="failed to connect: No such file or directory")
        return completed(args, stdout="codex-cli 0.144.3")

    result = probe_runtime(run=run, which=lambda _: "/bin/codex")
    assert result.authenticated is False


def test_rate_limits_use_sdk_connection_and_normalize_windows(monkeypatch):
    class Client:
        class _client:
            @staticmethod
            def _request_raw(method, params):
                assert method == "account/rateLimits/read"
                assert params == {}
                return {
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 12,
                            "resetsAt": 1234,
                            "windowDurationMins": 300,
                        },
                        "secondary": {"usedPercent": 34},
                        "rateLimitReachedType": None,
                    }
                }

        def close(self):
            pass

    monkeypatch.setattr("codex_axi.runtime.open_connection", lambda _: Client())
    result = read_rate_limits(RuntimeCapabilities("/bin/codex", None, True, True, "healthy"))
    assert result == {
        "available": True,
        "primary": {"used_percent": 12, "resets_at": 1234, "window_duration_mins": 300},
        "secondary": {"used_percent": 34, "resets_at": None, "window_duration_mins": None},
        "reached": None,
    }


def test_rate_limits_do_not_connect_when_unauthenticated(monkeypatch):
    monkeypatch.setattr(
        "codex_axi.runtime.open_connection", lambda _: (_ for _ in ()).throw(AssertionError())
    )
    result = read_rate_limits(
        RuntimeCapabilities("/bin/codex", None, True, True, "healthy", authenticated=False)
    )
    assert result["available"] is False
    assert result["detail"] == "Codex is not authenticated."


def test_connection_uses_direct_sdk_when_shared_transport_is_unavailable(monkeypatch):
    captured = {}

    class Config:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

    class Codex:
        def __init__(self, config):
            captured["client_config"] = config

    monkeypatch.setitem(
        sys.modules, "openai_codex", types.SimpleNamespace(Codex=Codex, CodexConfig=Config)
    )
    client = open_proxy_connection(
        RuntimeCapabilities("/bin/codex", "codex-cli 0.144.3", True, True, "healthy")
    )
    assert isinstance(client, Codex)
    assert captured["config"] == {"codex_bin": "/bin/codex"}


def test_connection_uses_managed_proxy_only_when_shared_transport_is_available(monkeypatch):
    captured = {}

    class Config:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

    class Codex:
        def __init__(self, config):
            captured["client_config"] = config

    monkeypatch.setitem(
        sys.modules, "openai_codex", types.SimpleNamespace(Codex=Codex, CodexConfig=Config)
    )
    client = open_proxy_connection(
        RuntimeCapabilities(
            "/bin/codex",
            "codex-cli 0.144.3",
            True,
            True,
            "healthy",
            shared_transport_available=True,
        )
    )
    assert isinstance(client, Codex)
    assert captured["config"]["launch_args_override"] == ("/bin/codex", "app-server", "proxy")


def test_shared_connection_fails_before_launch_when_transport_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai_codex", None)
    capabilities = RuntimeCapabilities(
        "/bin/codex", "codex-cli 0.144.3", True, True, "healthy"
    )

    with pytest.raises(AxiError) as raised:
        open_proxy_connection(capabilities, require_shared=True)

    assert raised.value.code == "shared_transport_unavailable"


def test_version_mismatch_is_distinct():
    def run(args):
        if args[-1] == "version":
            return completed(args, stdout='{"cliVersion":"0.144.3","appServerVersion":"0.145.0"}')
        return completed(args, stdout="codex-cli 0.144.3")

    result = probe_runtime(run=run, which=lambda _: "/bin/codex")
    assert result.daemon_state == "version-mismatched"
    assert result.detail == "daemon and app-server versions do not match"


def test_starting_daemon_is_distinct():
    def run(args):
        if args[-1] == "version":
            return completed(args, 1, stderr="daemon is starting")
        return completed(args, stdout="codex-cli 0.144.3")

    result = probe_runtime(run=run, which=lambda _: "/bin/codex")
    assert result.daemon_state == "starting"


def test_daemon_version_is_the_authoritative_protocol_health_check():
    def run(args):
        if args[-1] == "version":
            return completed(args, stdout='{"cliVersion":"0.144.3","appServerVersion":"0.144.3"}')
        return completed(args, stdout="codex-cli 0.144.3")

    result = probe_runtime(run=run, which=lambda _: "/bin/codex")

    assert result.daemon_state == "healthy"
    assert result.detail == "managed daemon protocol handshake completed"
    assert result.shared_transport_available is False
    assert "Unix WebSocket attachment is unavailable" in result.shared_transport_detail
