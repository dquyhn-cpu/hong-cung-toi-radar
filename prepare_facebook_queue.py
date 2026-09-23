import argparse
import json
from pathlib import Path


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
    parser.add_argument("--input", default="radar_editorial_v82.json")
    parser.add_argument("--output", default="facebook_publish_queue.json")
    args = parser.parse_args()

    payload = load_json(args.input)
    output_items = []

    for item in payload.get("items", []):
        draft = item.get("output_schema") or {}
        if draft.get("approved") is not True:
            continue

        main_post = (draft.get("main_post") or "").strip()
        if not main_post:
            raise ValueError(
                f"Approved item {item.get('event_id')} has empty main_post"
            )

        comments = [
            c.strip()
            for c in (draft.get("comments") or [])
            if isinstance(c, str) and c.strip()
        ]

        source_note = (draft.get("source_note") or "").strip()
        if source_note:
            if not comments or comments[-1] != source_note:
                comments.append(source_note)

        output_items.append({
            "publish_id": item.get("event_id"),
            "event_id": item.get("event_id"),
            "enabled": True,
            "message": main_post,
            "comments": comments,
            "editorial_score": item.get("editorial_score", {}),
            "recommended_angle": item.get("recommended_angle"),
        })

    save_json(
        args.output,
        {
            "generated_from": args.input,
            "items": output_items,
        },
    )
    print(f"FACEBOOK_QUEUE_READY: {len(output_items)} approved items")


if __name__ == "__main__":
    main()
