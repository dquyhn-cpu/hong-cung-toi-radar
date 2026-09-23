import argparse
import json
import os
from pathlib import Path

from openai import OpenAI


DEFAULT_INPUT = "radar_draft_packets_v82.json"
DEFAULT_OUTPUT = "radar_drafts_v83.json"


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_json(text):
    text = (text or "").strip()
    if text.startswith("\`\`\`"):
        text = text.strip("\`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return json.loads(text)


def validate_draft_shape(draft, event_id):
    required = [
        "publish_id",
        "approved",
        "caption_a",
        "caption_b",
        "summary_a",
        "summary_b",
        "source_comment",
        "selected_variant",
        "main_post",
        "comments",
        "source_note",
    ]
    missing = [key for key in required if key not in draft]
    if missing:
        raise ValueError(f"{event_id}: missing fields: {missing}")
    if draft.get("publish_id") != event_id:
        raise ValueError(f"{event_id}: publish_id mismatch")
    if draft.get("approved") is not False:
        raise ValueError(f"{event_id}: model draft must keep approved=false")
    if draft.get("selected_variant"):
        raise ValueError(f"{event_id}: selected_variant must remain empty before review")
    if draft.get("main_post"):
        raise ValueError(f"{event_id}: main_post must remain empty before review")
    if draft.get("comments"):
        raise ValueError(f"{event_id}: comments must remain empty before review")
    if not draft.get("caption_a") or not draft.get("caption_b"):
        raise ValueError(f"{event_id}: both captions are required")
    if not draft.get("summary_a") or not draft.get("summary_b"):
        raise ValueError(f"{event_id}: both summaries are required")
    if "http" not in (draft.get("source_comment") or ""):
        raise ValueError(f"{event_id}: source_comment must contain source URL")


def generate_draft(client, model, packet):
    event_id = packet.get("event_id")
    prompt = packet.get("prompt") or ""
    if not prompt:
        raise ValueError(f"{event_id}: missing prompt")

    response = client.responses.create(
        model=model,
        input=prompt,
    )

    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise RuntimeError(f"{event_id}: empty model output")

    draft = extract_json(output_text)
    validate_draft_shape(draft, event_id)
    return draft


def main():
    parser = argparse.ArgumentParser(description="Generate V8.3 editorial drafts with OpenAI Responses API")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--model", default=os.getenv("OPENAI_DRAFT_MODEL", "gpt-5.6-terra"))
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required")

    payload = load_json(args.input)
    packets = payload.get("items", [])[: max(args.limit, 0)]

    client = OpenAI()
    items = []

    for packet in packets:
        event_id = packet.get("event_id")
        record = {
            "event_id": event_id,
            "editorial_score": packet.get("editorial_score"),
            "monetization_preflight": packet.get("monetization_preflight"),
            "recommended_angle": packet.get("recommended_angle"),
        }
        try:
            record["output_schema"] = generate_draft(client, args.model, packet)
            record["status"] = "DRAFT_READY_FOR_REVIEW"
        except Exception as exc:
            record["status"] = "DRAFT_FAILED"
            record["error"] = str(exc)
        items.append(record)

    save_json(
        args.output,
        {
            "version": "8.3",
            "model": args.model,
            "source_file": args.input,
            "draft_count": sum(1 for x in items if x.get("status") == "DRAFT_READY_FOR_REVIEW"),
            "failed_count": sum(1 for x in items if x.get("status") == "DRAFT_FAILED"),
            "items": items,
        },
    )

    print(
        f"DRAFT_GENERATOR_V83: "
        f"{sum(1 for x in items if x.get('status') == 'DRAFT_READY_FOR_REVIEW')} ready; "
        f"{sum(1 for x in items if x.get('status') == 'DRAFT_FAILED')} failed"
    )


if __name__ == "__main__":
    main()
