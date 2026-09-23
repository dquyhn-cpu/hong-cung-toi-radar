import json
from pathlib import Path


INPUT_FILE = "radar_editorial_context_v82.json"
OUTPUT_FILE = "radar_draft_packets_v82.json"


BASE_RULES = [
    "Chỉ dùng dữ kiện có trong source_bundle. Không suy đoán và không bổ sung chi tiết từ trí nhớ.",
    "Bài chính phải chứa dữ kiện cốt lõi; không giấu thông tin thiết yếu xuống comment.",
    "Mở bài trực tiếp, tránh clickbait gây hiểu sai.",
    "Phân biệt dữ kiện đã xác nhận với nhận định/ý kiến được nguồn dẫn lại.",
    "Không dùng caption social làm bằng chứng xác nhận.",
    "Comment dùng cho bối cảnh, số liệu, diễn biến phụ và nguồn; không engagement bait.",
    "Nếu có nội dung chính trị/công quyền, chỉ mô tả trung tính các hành động, phát biểu, chính sách và dữ kiện được nguồn xác nhận; không kêu gọi ủng hộ/phản đối và không xếp hạng.",
    "Nếu có cáo buộc pháp lý, phải quy nguồn rõ ràng và tránh khẳng định vượt quá trạng thái pháp lý được nguồn nêu.",
    "Với trẻ em, tử vong, tự hại hoặc xâm hại: dùng giọng điệu tiết chế, không giật gân.",
]


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, payload):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _source_excerpt(record, max_chars=7000):
    article = record.get("article") or {}
    text = (article.get("text") or "").strip()
    return text[:max_chars]


def build_prompt(item):
    score = item.get("editorial_score") or {}
    preflight = item.get("monetization_preflight") or {}
    risk_flags = sorted(set((score.get("risk_flags") or []) + (preflight.get("risk_flags") or [])))
    angle = item.get("recommended_angle")

    readable_sources = [
        source for source in item.get("source_bundle", [])
        if source.get("status") == "READ_OK"
    ]

    source_sections = []
    for index, source in enumerate(readable_sources, start=1):
        article = source.get("article") or {}
        source_sections.append(
            "\n".join([
                f"[NGUỒN {index}] {source.get('source')} ({source.get('tier')})",
                f"Tiêu đề: {article.get('title') or source.get('declared_title')}",
                f"URL: {article.get('canonical_url') or source.get('url')}",
                "Nội dung đọc được:",
                _source_excerpt(source),
            ])
        )

    rules = "\n".join(f"- {rule}" for rule in BASE_RULES)
    sources_text = "\n\n".join(source_sections)

    return f"""Bạn là biên tập viên cho Page Hóng Cùng Tôi.

MỤC TIÊU
Biên soạn một bản tin Facebook có giá trị thông tin, dễ đọc, giữ chân tự nhiên nhưng không đánh đổi độ chính xác.

GÓC ĐỀ XUẤT
{angle}

ĐIỂM ƯU TIÊN
{score.get('score')} / 100 — {score.get('tier')}

MONETIZATION PREFLIGHT\n- Risk: {preflight.get("monetization_risk")}\n- Publish mode: {preflight.get("recommended_publish_mode")}\n- Originality risk: {preflight.get("originality_risk")}\n- Copyright risk: {preflight.get("copyright_risk")}\n- Reason: {preflight.get("monetization_reason")}\n\nRISK FLAGS\n{', '.join(risk_flags) if risk_flags else 'Không có cờ đặc biệt'}\n\nQUY TẮC BẮT BUỘC
{rules}

CẤU TRÚC ĐẦU RA
Trả về JSON hợp lệ đúng schema:
{{
  "publish_id": "{item.get('event_id')}",
  "approved": false,
  "caption_a": "...",
  "caption_b": "...",
  "summary_a": "...",
  "summary_b": "...",
  "source_comment": "Nguồn: ...\nĐọc bài báo gốc tại đây: https://...",
  "selected_variant": "",
  "main_post": "",
  "comments": [],
  "source_note": "Nguồn: ... https://..."
}}

YÊU CẦU BIÊN SOẠN THEO @bao-chi-tu-link
- caption_a: phương án trực diện, ngắn, đúng nguồn.
- caption_b: phương án gợi tò mò nhưng không giấu dữ kiện trọng yếu và không clickbait gây hiểu sai.
- summary_a: 2-3 đoạn ngắn, mạch lạc, viết lại bằng lời mới.
- summary_b: bản tóm tắt dạng gạch đầu dòng về sự việc, địa điểm/thời gian, chi tiết chính và tình trạng xử lý nếu nguồn có nêu.
- source_comment: bắt buộc có tên báo và URL bài gốc đã đọc; nếu có credit ảnh trong nguồn thì ghi riêng.
- selected_variant, main_post, comments để trống ở bước tạo nháp. Review sau đó mới chọn phương án và chuẩn hóa thành bài đăng cuối.
- main_post cuối cùng phải đủ để người đọc hiểu sự việc ngay cả khi không mở comment.
- comments cuối cùng chỉ thêm bối cảnh/chi tiết có ích; 0-4 comment.
- source_note: ít nhất 1 URL nguồn gốc đã đọc.
- approved luôn để false ở bước nháp; chỉ chuyển true sau bước review.

SOURCE BUNDLE
{sources_text}
"""


def main():
    payload = load_json(INPUT_FILE)
    packets = []

    for item in payload.get("items", []):
        if item.get("status") != "READY_FOR_DRAFT":
            continue

        packets.append({
            "event_id": item.get("event_id"),
            "monetization_preflight": item.get("monetization_preflight"),
            "editorial_score": item.get("editorial_score"),
            "recommended_angle": item.get("recommended_angle"),
            "prompt": build_prompt(item),
            "output_schema": item.get("output_schema"),
        })

    save_json(
        OUTPUT_FILE,
        {
            "version": "8.2",
            "source_file": INPUT_FILE,
            "packet_count": len(packets),
            "items": packets,
        },
    )
    print(f"DRAFT_PACKETS_V82: {len(packets)}")


if __name__ == "__main__":
    main()
