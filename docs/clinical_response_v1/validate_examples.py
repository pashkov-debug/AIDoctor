"""Offline structural and JSON Schema validation of 24 synthetic scenarios."""
import json
from pathlib import Path

folder = Path(__file__).resolve().parent
schema = json.loads((folder / "clinical_response.v1.schema.json").read_text(encoding="utf-8"))
paths = sorted((folder / "examples").glob("*.json"))
assert len(paths) == 24, f"Expected 24, found {len(paths)}"
try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit("Install jsonschema to validate full constraints: pip install jsonschema") from exc
validator = Draft202012Validator(schema)
validator.check_schema(schema)
for path in paths:
    data = json.loads(path.read_text(encoding="utf-8"))
    validator.validate(data)
    assert data["workflow"]["auto_apply_orders"] is False
    assert data["workflow"]["auto_publish_history"] is False
    assert all(m["status"] == "pending_physician_approval" for m in data["medication_proposals"])
    assert all(a["dispatch"] == "proposed_not_sent" for a in data["alerts"])
print(f"OK: {len(paths)} schema-valid synthetic scenarios")
