import argparse
import json
from pathlib import Path

DEFAULT_CONTEXT = "radar_editorial_context_v82.json"
DEFAULT_PACKETS = "radar_draft_packets_v82.json"
DEFAULT_JSON = "editorial_review_candidates_v83.json"
DEFAULT_MD = "editorial_review_candidates_v83.md"
DEFAULT_RADAR = "radar_results.json"

SOCIAL_RADAR_SOURCES = [
    "BeatVN",
    "Theanh28",
    "Top Comments",
    "Bí Mật Showbiz",
]

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
        if item.get("status") not in {"READY_FOR_DRAFT", "SOURCE_READ_REQUIRED"}:
            continue
        event_id = str(item.get("event_id"))
        packet = packet_map.get(event_id)
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
            "social_sources": item.get("social_sources") or [],
            "social_signals": item.get("social_signals") or [],
            "source_read_status": item.get("status"),
            "needs_source_resolution": item.get("status") == "SOURCE_READ_REQUIRED",
            "draft_prompt": packet.get("prompt") if packet else None,
        })
    candidates.sort(
        key=lambda x: (
            {"PRIORITY": 0, "GOOD": 1, "REVIEW": 2, "LOW": 3}.get(x.get("tier"), 9),
            -(x.get("score") or 0),
        )
    )
    return candidates[: max(limit, 0)]

def build_social_health(radar_payload):
    stats = (radar_payload or {}).get("facebook_stats") or {}
    output = []
    for source in SOCIAL_RADAR_SOURCES:
        count = int(stats.get(source) or 0)
        if count == 0:
            status = "DOWN_OR_BLOCKED"
        elif count == 1:
            status = "LOW_YIELD"
        else:
            status = "OK"
        output.append({
            "source": source,
            "count": count,
            "status": status,
        })
    return output


def build_markdown(candidates, social_health=None):
    lines = [
        "# Hóng Cùng Tôi — Editorial Review V8.3",
        "",
        "Danh sách tin đã qua Radar, xác minh tín hiệu nguồn, Editorial V8.2 và Monetization Preflight. Tin nào chưa đọc được bài gốc sẽ được đánh dấu để ChatGPT resolve/đọc lại trước khi biên tập.",
        "",
        "**Không có API AI nào được gọi ở bước này. Không có bài nào được tự động đăng Facebook.**",
        "",
        "Cách dùng: xem danh sách rồi nói trong ChatGPT: Biên tập tin số N hoặc Biên tập event_id ...",
        "",
    ]

    if social_health:
        lines.extend([
            "## Social Radar Health",
            "",
            "Số post Facebook đọc được ở lượt quét hiện tại. 0 = có khả năng bị chặn/không đọc được; 1 = sản lượng thấp bất thường với các page đăng dày.",
            "",
        ])
        for item in social_health:
            lines.append(
                f"- **{item.get('source')}:** {item.get('count')} post — {item.get('status')}"
            )
        lines.append("")

    if not candidates:
        lines.append("_Không có tin nào đủ điều kiện READY_FOR_DRAFT trong lượt chạy này._")
        return "\n".join(lines) + "\n"

    for index, item in enumerate(candidates, start=1):
        src = item.get("source") or {}
        flags = ", ".join(item.get("risk_flags") or []) or "Không có cờ nổi bật"
        social_sources = item.get("social_sources") or []
        social_signals = item.get("social_signals") or []
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
            f"- **Phát hiện từ social:** {', '.join(social_sources) if social_sources else 'Không có'}",
            f"- **Trạng thái nguồn:** {item.get('source_read_status')}",
            f"- **Cần resolve/đọc lại nguồn:** {'CÓ' if item.get('needs_source_resolution') else 'KHÔNG'}",
            f"- **Tiêu đề nguồn:** {src.get('title') or 'N/A'}",
            f"- **URL nguồn:** {src.get('url') or 'N/A'}",
        ])
        for signal in social_signals[:4]:
            lines.append(
                f"- **Social signal:** {signal.get('source') or 'N/A'} — {signal.get('url') or 'N/A'}"
            )
        lines.append("")

    lines.extend([
        "---",
        "",
        "### Quy tắc duyệt",
        "",
        "1. Tin được chọn bắt buộc phải được ChatGPT resolve URL gốc và đọc/đối chiếu bài gốc trước khi biên tập; SOURCE_READ_REQUIRED chỉ là candidate, chưa được phép soạn bài.",
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
    parser.add_argument("--radar-results", default=DEFAULT_RADAR)
    args = parser.parse_args()

    context_payload = load_json(args.context)
    packets_payload = load_json(args.packets)
    radar_payload = load_json(args.radar_results) if Path(args.radar_results).exists() else {}
    social_health = build_social_health(radar_payload)
    candidates = build_candidates(context_payload, packets_payload, args.limit)

    save_json(args.json_output, {
        "version": "8.3-manual",
        "candidate_count": len(candidates),
        "social_health": social_health,
        "items": candidates,
    })
    save_text(args.md_output, build_markdown(candidates, social_health))
    print(f"MANUAL_REVIEW_V83: {len(candidates)} candidates")

if __name__ == "__main__":
    main()
