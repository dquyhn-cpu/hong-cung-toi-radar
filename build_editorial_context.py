import json
from pathlib import Path

from source_reader import build_source_bundle


INPUT_FILE = "radar_editorial_v82.json"
OUTPUT_FILE = "radar_editorial_context_v82.json"


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, payload):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main():
    payload = load_json(INPUT_FILE)
    items = []

    for item in payload.get("items", []):
        enriched = dict(item)
        source_bundle = build_source_bundle(item)
        readable = [
            x for x in source_bundle
            if x.get("status") == "READ_OK"
        ]

        enriched["source_bundle"] = source_bundle
        enriched["source_read_status"] = {
            "attempted": len(source_bundle),
            "readable": len(readable),
            "primary_readable": bool(
                source_bundle
                and source_bundle[0].get("status") == "READ_OK"
            ),
        }

        if not readable:
            enriched["status"] = "SOURCE_READ_REQUIRED"
        elif enriched.get("status") == "NEEDS_EDITORIAL_DRAFT":
            enriched["status"] = "READY_FOR_DRAFT"

        items.append(enriched)

    save_json(
        OUTPUT_FILE,
        {
            "version": "8.2",
            "source_file": INPUT_FILE,
            "items": items,
        },
    )

    ready = sum(1 for x in items if x.get("status") == "READY_FOR_DRAFT")
    print(f"EDITORIAL_CONTEXT_V82: {len(items)} items, {ready} ready for draft")


if __name__ == "__main__":
    main()
