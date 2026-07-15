import subprocess
import sys
import types

from codex_axi.runtime import RuntimeCapabilities, open_proxy_connection, probe_runtime


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


def test_connection_uses_sdk_with_managed_proxy(monkeypatch):
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
    assert captured["config"]["launch_args_override"] == ("/bin/codex", "app-server", "proxy")


def test_version_mismatch_is_distinct():
    def run(args):
        if args[-1] == "version":
            return completed(args, stdout='{"cliVersion":"0.144.3","appServerVersion":"0.145.0"}')
        return completed(args, stdout="codex-cli 0.144.3")

    result = probe_runtime(run=run, which=lambda _: "/bin/codex")
    assert result.daemon_state == "version-mismatched"


def test_starting_daemon_is_distinct():
    def run(args):
        if args[-1] == "version":
            return completed(args, 1, stderr="daemon is starting")
        return completed(args, stdout="codex-cli 0.144.3")

    result = probe_runtime(run=run, which=lambda _: "/bin/codex")
    assert result.daemon_state == "starting"
