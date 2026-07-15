from codex_axi.errors import translate_runtime_error


def test_transport_loss_is_translated_without_raw_error():
    error = translate_runtime_error(RuntimeError("transport closed with secret backend detail"))
    assert error.code == "daemon_unavailable"
    assert "secret" not in error.message


def test_approval_block_has_safe_continuation():
    error = translate_runtime_error(RuntimeError("approval denied"))
    assert error.code == "approval_required"
    assert "interactively" in error.suggestion
