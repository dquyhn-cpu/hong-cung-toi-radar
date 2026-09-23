import argparse
import json
from pathlib import Path

DEFAULT_CONTEXT = "radar_editorial_context_v82.json"
DEFAULT_PACKETS = "radar_draft_packets_v82.json"
DEFAULT_JSON = "editorial_review_candidates_v83.json"
DEFAULT_MD = "editorial_review_candidates_v83.md"

def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_text(path, text):
    Path(path).write_text(text, encoding="utf-8")

def first_source(item):
    bundle = item.get("source_bundle") or []
    for record in bundle:
        if record.get("status") == "READ_OK":
            article = record.get("article") or {}
            return {
                "source": record.get("source"),
                "tier": record.get("tier"),
                "title": article.get("title") or record.get("declared_title"),
                "url": article.get("canonical_url") or record.get("url"),
            }
    source = item.get("primary_source") or {}
    return {
        "source": source.get("source"),
        "tier": source.get("tier"),
        "title": source.get("title"),
        "url": source.get("url"),
    }

def build_candidates(context_payload, packets_payload, limit):
    packet_map = {
        str(x.get("event_id")): x
        for x in packets_payload.get("items", [])
        if x.get("event_id")
    }
    candidates = []
    for item in context_payload.get("items", []):
        if item.get("status") != "READY_FOR_DRAFT":
            continue
        event_id = str(item.get("event_id"))
        packet = packet_map.get(event_id)
        if not packet:
            continue
        score = item.get("editorial_score") or {}
        preflight = item.get("monetization_preflight") or {}
        source = first_source(item)
        candidates.append({
            "event_id": event_id,
            "working_title": item.get("working_title"),
            "score": score.get("score"),
            "tier": score.get("tier"),
            "recommended_angle": item.get("recommended_angle"),
            "monetization_risk": preflight.get("monetization_risk"),
            "recommended_publish_mode": preflight.get("recommended_publish_mode"),
            "risk_flags": preflight.get("risk_flags") or score.get("risk_flags") or [],
            "source": source,
            "draft_prompt": packet.get("prompt"),
        })
    candidates.sort(
        key=lambda x: (
            {"PRIORITY": 0, "GOOD": 1, "REVIEW": 2, "LOW": 3}.get(x.get("tier"), 9),
            -(x.get("score") or 0),
        )
    )
    return candidates[: max(limit, 0)]

def build_markdown(candidates):
    lines = [
        "# Hóng Cùng Tôi — Editorial Review V8.3",
        "",
        "Danh sách tin đã qua Radar, xác minh nguồn, Editorial V8.2, Monetization Preflight và đọc bài gốc.",
        "",
        "**Không có API AI nào được gọi ở bước này. Không có bài nào được tự động đăng Facebook.**",
        "",
        "Cách dùng: xem danh sách rồi nói trong ChatGPT: Biên tập tin số N hoặc Biên tập event_id ...",
        "",
    ]
    if not candidates:
        lines.append("_Không có tin nào đủ điều kiện READY_FOR_DRAFT trong lượt chạy này._")
        return "\n".join(lines) + "\n"

    for index, item in enumerate(candidates, start=1):
        src = item.get("source") or {}
        flags = ", ".join(item.get("risk_flags") or []) or "Không có cờ nổi bật"
        lines.extend([
            f"## Tin {index} — {item.get('working_title') or '(không có tiêu đề)'}",
            "",
            f"- **event_id:** {item.get('event_id')}",
            f"- **Ưu tiên:** {item.get('score')} / 100 — {item.get('tier')}",
            f"- **Góc đề xuất:** {item.get('recommended_angle')}",
            f"- **Rủi ro kiếm tiền:** {item.get('monetization_risk')}",
            f"- **Publish mode:** {item.get('recommended_publish_mode')}",
            f"- **Risk flags:** {flags}",
            f"- **Nguồn chính:** {src.get('source') or 'N/A'}",
            f"- **Tiêu đề nguồn:** {src.get('title') or 'N/A'}",
            f"- **URL nguồn:** {src.get('url') or 'N/A'}",
            "",
        ])

    lines.extend([
        "---",
        "",
        "### Quy tắc duyệt",
        "",
        "1. Tin được chọn vẫn phải được ChatGPT đọc/đối chiếu lại bài gốc trước khi biên tập.",
        "2. Bản nháp phải giữ dữ kiện cốt lõi trong bài chính; comment chỉ bổ sung bối cảnh/nguồn.",
        "3. Nội dung nhạy cảm, pháp lý, trẻ em hoặc công quyền phải tuân thủ risk flags.",
        "4. Chỉ sau khi anh nói rõ duyệt đăng thì mới được đưa nội dung vào facebook_publish_queue.json.",
        "5. Việc bấm workflow publisher thật vẫn là bước riêng.",
    ])
    return "\n".join(lines) + "\n"

def main():
    parser = argparse.ArgumentParser(description="Prepare manual ChatGPT editorial review package without API cost")
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--packets", default=DEFAULT_PACKETS)
    parser.add_argument("--json-output", default=DEFAULT_JSON)
    parser.add_argument("--md-output", default=DEFAULT_MD)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    context_payload = load_json(args.context)
    packets_payload = load_json(args.packets)
    candidates = build_candidates(context_payload, packets_payload, args.limit)

    save_json(args.json_output, {
        "version": "8.3-manual",
        "candidate_count": len(candidates),
        "items": candidates,
    })
    save_text(args.md_output, build_markdown(candidates))
    print(f"MANUAL_REVIEW_V83: {len(candidates)} candidates")

if __name__ == "__main__":
    main()
