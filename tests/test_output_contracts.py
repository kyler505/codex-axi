import json
from pathlib import Path

import jsonschema

from codex_axi.output import toon


def test_representative_contracts_encode_without_trailing_newline():
    path = Path(__file__).parent / "fixtures" / "output" / "documents.json"
    schema_path = Path(__file__).parents[1] / "compatibility" / "output-schema.json"
    schema = json.loads(schema_path.read_text())
    for document in json.loads(path.read_text()):
        jsonschema.validate(document, schema)
        encoded = toon(document)
        assert encoded
        assert not encoded.endswith("\n")


def test_event_contract_has_explicit_version_and_cursor():
    path = Path(__file__).parent / "fixtures" / "output" / "documents.json"
    event = json.loads(path.read_text())[-1]
    assert event["schema_version"] == 1
    assert event["sequence"] == 1


def test_command_goldens_validate_against_output_schema():
    root = Path(__file__).parents[1]
    schema = json.loads((root / "compatibility" / "output-schema.json").read_text())
    goldens = json.loads(
        (Path(__file__).parent / "fixtures" / "output" / "command-goldens.json").read_text()
    )
    for value in goldens.values():
        jsonschema.validate(value["document"], schema)
