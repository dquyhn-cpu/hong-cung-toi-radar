import argparse
import json
from pathlib import Path

from draft_validator import validate_editorial_output


DEFAULT_CONTEXT = "radar_editorial_context_v82.json"
DEFAULT_DRAFTS = "radar_drafts_v83.json"
DEFAULT_DECISIONS = "editorial_review_decisions.json"
DEFAULT_OUTPUT = "radar_reviewed_v83.json"


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def by_event_id(items):
    return {str(item.get("event_id")): item for item in items if item.get("event_id")}


def normalize_variant(value):
    value = str(value or "").strip().upper()
    if value not in {"A", "B"}:
        raise ValueError("selected_variant must be A or B")
    return value


def assemble_final_post(draft, variant):
    suffix = variant.lower()
    caption = (draft.get(f"caption_{suffix}") or "").strip()
    summary = (draft.get(f"summary_{suffix}") or "").strip()
    source_comment = (draft.get("source_comment") or "").strip()

    if not caption or not summary:
        raise ValueError(f"Variant {variant} is incomplete")
    if "http" not in source_comment:
        raise ValueError("source_comment must contain a source URL")

    main_post = f"{caption}\n\n{summary}".strip()
    comments = [source_comment]

    return main_post, comments, source_comment


def main():
    parser = argparse.ArgumentParser(description="Apply human review decisions to V8.3 drafts")
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--drafts", default=DEFAULT_DRAFTS)
    parser.add_argument("--decisions", default=DEFAULT_DECISIONS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    context_payload = load_json(args.context)
    drafts_payload = load_json(args.drafts)
    decisions_payload = load_json(args.decisions)

    context_map = by_event_id(context_payload.get("items", []))
    draft_map = by_event_id(drafts_payload.get("items", []))
    decisions = decisions_payload.get("decisions", [])

    reviewed = []
    errors = []

    for decision in decisions:
        event_id = str(decision.get("event_id") or "").strip()
        if not event_id:
            errors.append({"event_id": None, "error": "MISSING_EVENT_ID"})
            continue

        context_item = context_map.get(event_id)
        draft_record = draft_map.get(event_id)

        if not context_item:
            errors.append({"event_id": event_id, "error": "CONTEXT_NOT_FOUND"})
            continue
        if not draft_record or draft_record.get("status") != "DRAFT_READY_FOR_REVIEW":
            errors.append({"event_id": event_id, "error": "DRAFT_NOT_READY"})
            continue

        item = dict(context_item)
        draft = dict(draft_record.get("output_schema") or {})
        approve = bool(decision.get("approve"))

        if not approve:
            draft["approved"] = False
            item["output_schema"] = draft
            item["status"] = "REJECTED_BY_REVIEW"
            item["review"] = {
                "approve": False,
                "note": decision.get("note"),
            }
            reviewed.append(item)
            continue

        try:
            variant = normalize_variant(decision.get("selected_variant"))
            main_post, comments, source_note = assemble_final_post(draft, variant)

            draft["selected_variant"] = variant
            draft["main_post"] = main_post
            draft["comments"] = comments
            draft["source_note"] = source_note
            draft["approved"] = True

            item["output_schema"] = draft
            item["status"] = "APPROVED"
            item["review"] = {
                "approve": True,
                "selected_variant": variant,
                "note": decision.get("note"),
            }

            validation = validate_editorial_output(item)
            item["draft_validation"] = validation

            if not validation["ok"]:
                item["status"] = "REVIEW_VALIDATION_FAILED"
                draft["approved"] = False
                errors.append({
                    "event_id": event_id,
                    "error": "VALIDATION_FAILED",
                    "details": validation,
                })

            reviewed.append(item)
        except Exception as exc:
            errors.append({"event_id": event_id, "error": str(exc)})

    save_json(
        args.output,
        {
            "version": "8.3",
            "context_source": args.context,
            "draft_source": args.drafts,
            "decision_source": args.decisions,
            "approved_count": sum(
                1 for item in reviewed if (item.get("output_schema") or {}).get("approved") is True
            ),
            "reviewed_count": len(reviewed),
            "error_count": len(errors),
            "errors": errors,
            "items": reviewed,
        },
    )

    print(
        f"REVIEW_V83: {len(reviewed)} reviewed; "
        f"{sum(1 for item in reviewed if (item.get('output_schema') or {}).get('approved') is True)} approved; "
        f"{len(errors)} errors"
    )


if __name__ == "__main__":
    main()
