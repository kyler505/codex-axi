from codex_axi.output import preview, toon


def test_toon_renders_structured_values_without_trailing_newline():
    assert (
        toon({"status": "healthy", "values": [1, True, None]})
        == "status: healthy\nvalues[3]: 1,true,null"
    )


def test_toon_quotes_structural_strings():
    assert toon({"message": "needs: quoting"}) == 'message: "needs: quoting"'


def test_preview_reports_total_when_truncated():
    assert preview("abcdef", limit=3) == ("abc...", 6)


def test_toon_uses_tabular_form_for_uniform_objects():
    assert (
        toon({"tasks": [{"id": "1", "status": "open"}, {"id": "2", "status": "done"}]})
        == 'tasks[2]{id,status}:\n  "1",open\n  "2",done'
    )


def test_toon_quotes_numeric_strings_and_all_control_characters():
    assert toon({"id": "123", "control": "a\x01b"}) == 'id: "123"\ncontrol: "a\\u0001b"'


def test_toon_mixed_array_declares_count_and_places_first_object_field_inline():
    assert toon({"items": [{"id": "1", "nested": {"ok": True}}, "done"]}) == (
        'items[2]:\n  - id: "1"\n    nested:\n      ok: true\n  - done'
    )
