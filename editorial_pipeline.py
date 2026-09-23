import json
from pathlib import Path

from editorial_v82 import build_editorial_package, sort_editorial_queue


EVENT_FILE = "radar_events.json"
OUTPUT_FILE = "radar_editorial_v82.json"


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def choose_source(event):
    usable = [
        article
        for article in event.get("articles", [])
        if article.get("url")
        and article.get("source_tier") in {"OFFICIAL", "TRUSTED_NEWS"}
    ]
    for article in usable:
        if article.get("source_tier") == "OFFICIAL":
            return article
    return usable[0] if usable else None


def should_include_event(event, package):
    decision = event.get("decision")
    if decision == "CHUYEN_BAN_BIEN_TAP":
        return True

    # V8.2 is intentionally a second editorial decision layer.
    # A verified WATCH item should not be discarded before V8.2 can score it.
    # Keep only WATCH items that reach at least REVIEW tier.
    if decision == "THEO_DOI":
        score = (package.get("editorial_score") or {}).get("score", 0)
        return score >= 42

    return False


def main():
    payload = load_json(EVENT_FILE)
    events = payload.get("events", [])

    decision_counts = {}
    packages = []
    promoted_watch = 0

    for event in events:
        decision = event.get("decision") or "UNKNOWN"
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

        if decision not in {"CHUYEN_BAN_BIEN_TAP", "THEO_DOI"}:
            continue

        source = choose_source(event)
        if not source:
            continue

        package = build_editorial_package(event, source)
        if not should_include_event(event, package):
            continue

        if decision == "THEO_DOI":
            package["v82_promotion"] = "WATCH_PROMOTED_FOR_EDITORIAL_REVIEW"
            promoted_watch += 1

        packages.append(package)

    packages = sort_editorial_queue(packages)

    summary = {
        "priority": sum(1 for x in packages if x["editorial_score"]["tier"] == "PRIORITY"),
        "good": sum(1 for x in packages if x["editorial_score"]["tier"] == "GOOD"),
        "review": sum(1 for x in packages if x["editorial_score"]["tier"] == "REVIEW"),
        "low": sum(1 for x in packages if x["editorial_score"]["tier"] == "LOW"),
    }

    save_json(
        OUTPUT_FILE,
        {
            "version": "8.2",
            "source_event_file": EVENT_FILE,
            "queue_count": len(packages),
            "summary": summary,
            "input_decisions": decision_counts,
            "promoted_watch_count": promoted_watch,
            "selection_policy": {
                "purpose": "Ưu tiên tin đáng chiếm slot đăng, sau khi đã qua lớp xác minh nguồn.",
                "important_note": (
                    "Điểm editorial là mức ưu tiên nội dung, không phải mức độ đúng/sai. "
                    "Tin điểm cao vẫn phải đọc bài nguồn trước khi biên soạn. "
                    "Các tin THEO_DOI có nguồn hợp lệ được phép đi qua V8.2 nếu đạt tối thiểu REVIEW (42 điểm), "
                    "để tránh lớp V8 loại quá sớm các tin vẫn đáng cho biên tập viên xem."
                ),
                "tiers": {
                    "PRIORITY": "Ưu tiên biên tập trước.",
                    "GOOD": "Đáng biên tập.",
                    "REVIEW": "Cần biên tập viên xem thêm ngữ cảnh.",
                    "LOW": "Không ưu tiên, trừ khi có diễn biến mới.",
                },
            },
            "items": packages,
        },
    )

    print(f"EDITORIAL_V82: {len(packages)} items")
    print(json.dumps({
        "tiers": summary,
        "input_decisions": decision_counts,
        "promoted_watch_count": promoted_watch,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
