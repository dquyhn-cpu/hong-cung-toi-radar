import argparse
import json
from pathlib import Path

from draft_validator import validate_editorial_output


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Convert approved V8.2 editorial items into Facebook publisher queue"
    )
    parser.add_argument("--input", default="radar_editorial_context_v82.json")
    parser.add_argument("--output", default="facebook_publish_queue.json")
    args = parser.parse_args()

    payload = load_json(args.input)
    output_items = []
    rejected = []

    for item in payload.get("items", []):
        draft = item.get("output_schema") or {}
        if draft.get("approved") is not True:
            continue

        preflight = item.get("monetization_preflight") or {}
        publish_mode = preflight.get("recommended_publish_mode")
        if publish_mode not in {"POST", "POST_WITH_CAUTION"}:
            rejected.append({
                "event_id": item.get("event_id"),
                "errors": ["PREFLIGHT_NOT_PUBLISHABLE"],
                "warnings": [],
            })
            continue

        validation = validate_editorial_output(item)
        if not validation["ok"]:
            rejected.append({
                "event_id": item.get("event_id"),
                "errors": validation["errors"],
                "warnings": validation["warnings"],
            })
            continue

        if item.get("status") not in {"READY_FOR_DRAFT", "DRAFT_REVIEWED", "APPROVED"}:
            rejected.append({
                "event_id": item.get("event_id"),
                "errors": ["SOURCE_READ_NOT_READY"],
                "warnings": [],
            })
            continue

        main_post = (draft.get("main_post") or "").strip()
        comments = [
            c.strip()
            for c in (draft.get("comments") or [])
            if isinstance(c, str) and c.strip()
        ]

        source_note = (draft.get("source_note") or "").strip()
        if source_note and (not comments or comments[-1] != source_note):
            comments.append(source_note)

        output_items.append({
            "publish_id": item.get("event_id"),
            "event_id": item.get("event_id"),
            "enabled": True,
            "message": main_post,
            "comments": comments,
            "editorial_score": item.get("editorial_score", {}),
            "recommended_angle": item.get("recommended_angle"),
            "draft_validation": validation,
            "monetization_preflight": preflight,
        })

    save_json(
        args.output,
        {
            "generated_from": args.input,
            "approved_count": len(output_items),
            "rejected_count": len(rejected),
            "rejected": rejected,
            "items": output_items,
        },
    )

    print(
        f"FACEBOOK_QUEUE_READY: {len(output_items)} approved items; "
        f"{len(rejected)} rejected by validation"
    )


if __name__ == "__main__":
    main()
