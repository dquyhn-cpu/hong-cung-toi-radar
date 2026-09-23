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


def main():
    payload = load_json(EVENT_FILE)
    events = payload.get("events", [])

    packages = []
    for event in events:
        if event.get("decision") != "CHUYEN_BAN_BIEN_TAP":
            continue
        source = choose_source(event)
        if not source:
            continue
        packages.append(build_editorial_package(event, source))

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
            "selection_policy": {
                "purpose": "Ưu tiên tin đáng chiếm slot đăng, sau khi đã qua lớp xác minh nguồn.",
                "important_note": (
                    "Điểm editorial là mức ưu tiên nội dung, không phải mức độ đúng/sai. "
                    "Tin điểm cao vẫn phải đọc bài nguồn trước khi biên soạn."
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
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
