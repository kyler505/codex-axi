import pytest
from openai_codex import InvalidParamsError, TransportClosedError

from codex_axi.errors import translate_runtime_error


def test_transport_loss_is_translated_without_raw_error():
    error = translate_runtime_error(RuntimeError("transport closed with secret backend detail"))
    assert error.code == "daemon_unavailable"
    assert "secret" not in error.message


def test_approval_block_has_safe_continuation():
    error = translate_runtime_error(RuntimeError("approval denied"))
    assert error.code == "approval_required"
    assert "interactively" in error.suggestion


@pytest.mark.parametrize(
    "message",
    [
        "thread not found",
        "thread not loaded: abc",
        "no rollout found for thread id abc",
    ],
)
def test_not_found_runtime_error_has_specific_code(message):
    error = translate_runtime_error(InvalidParamsError(-32602, message))
    assert error.code == "thread_not_found"
    assert error.exit_code == 1


def test_invalid_params_runtime_error_is_usage_error():
    error = translate_runtime_error(InvalidParamsError(-32602, "limit is invalid"))
    assert error.code == "invalid_request"
    assert error.exit_code == 2


def test_closed_transport_remains_runtime_failure():
    error = translate_runtime_error(TransportClosedError("closed"))
    assert error.code == "runtime_unavailable"
    assert error.exit_code == 1
