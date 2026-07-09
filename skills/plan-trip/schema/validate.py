"""
Validate an itinerary JSON instance against itinerary.schema.json.

Usage:
    python validate.py                 # validates pnw_example.json
    python validate.py path/to/trip.json
"""
import json
import os
import sys
from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "itinerary.schema.json")


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(instance_path):
    schema = load(SCHEMA)
    instance = load(instance_path)

    Draft202012Validator.check_schema(schema)  # the schema itself is valid
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))

    name = os.path.basename(instance_path)
    if not errors:
        nd = len(instance.get("days", []))
        ns = len(instance.get("map", {}).get("stops", []))
        print(f"VALID  {name}  ({nd} day pages, {ns} map stops)")
        return 0

    print(f"INVALID  {name}  ({len(errors)} error(s)):")
    for e in errors:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        print(f"  - at {loc}: {e.message}")
    return 1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "pnw_example.json")
    sys.exit(main(target))
