import re
import unicodedata
from datetime import datetime, timezone

from monetization_preflight import monetization_preflight


HUMAN_INTEREST_KEYWORDS = {
    "tre em", "hoc sinh", "gia dinh", "nguoi gia", "em be", "cha me",
    "me con", "bo con", "cuu nguoi", "hy sinh", "doan tu", "mat tich",
    "benh nhan", "nan nhan", "nguoi lao dong", "sinh vien",
}

HIGH_IMPACT_KEYWORDS = {
    "gia vang", "gia xang", "lai suat", "thue", "luong", "bao", "lu",
    "dong dat", "tai nan", "chay", "no", "mat dien", "ngung dich vu",
    "cam", "thu hoi", "trieu hoi", "quyet dinh", "xu phat", "khoi to",
    "bat giu", "duong sat", "hang khong", "giao thong", "ngan hang",
}

SURPRISE_KEYWORDS = {
    "bat ngo", "lan dau", "ky luc", "hiem gap", "chua tung", "dot ngot",
    "gay xon xao", "gay chu y", "dao nguoc", "phat hien", "vo oa",
}

VISUAL_KEYWORDS = {
    "video", "clip", "hinh anh", "camera", "hien truong", "anh", "canh",
    "khoanh khac", "bien lua", "ngap", "sap", "va cham", "cuu ho",
}

DISCUSSION_KEYWORDS = {
    "tranh cai", "y kien trai chieu", "gay tranh luan", "de xuat",
    "quy dinh", "nen hay khong", "phat", "gia", "cam", "thu phi",
}

SENSITIVE_KEYWORDS = {
    "tu vong": "DEATH",
    "chet": "DEATH",
    "tu sat": "SELF_HARM",
    "tre em": "MINOR",
    "em be": "MINOR",
    "hoc sinh": "MINOR",
    "xam hai": "SEXUAL_HARM",
    "hiep dam": "SEXUAL_HARM",
    "ma tuy": "CRIME_DRUGS",
    "khoi to": "LEGAL_ALLEGATION",
    "bat giu": "LEGAL_ALLEGATION",
    "dieu tra": "LEGAL_ALLEGATION",
    "nghi pham": "LEGAL_ALLEGATION",
    "benh": "HEALTH",
    "dich benh": "HEALTH",
    "ung thu": "HEALTH",
    "bo truong": "POLITICAL_OR_OFFICIAL",
    "thu tuong": "POLITICAL_OR_OFFICIAL",
    "chu tich": "POLITICAL_OR_OFFICIAL",
    "quoc hoi": "POLITICAL_OR_OFFICIAL",
    "chinh phu": "POLITICAL_OR_OFFICIAL",
}


def _strip_accents(text):
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def _norm(text):
    text = _strip_accents((text or "").lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_any(text, phrases):
    norm = _norm(text)
    return any(_norm(p) in norm for p in phrases)


def _count_sources(event):
    articles = [a for a in event.get("articles", []) if a.get("url")]
    publishers = {a.get("source") for a in articles if a.get("source")}
    official = sum(1 for a in articles if a.get("source_tier") == "OFFICIAL")
    trusted = sum(1 for a in articles if a.get("source_tier") == "TRUSTED_NEWS")
    return articles, publishers, official, trusted


def build_risk_flags(event):
    text = " ".join([
        event.get("title", ""),
        event.get("context", ""),
        " ".join(p.get("text", "") for p in event.get("social_posts", [])),
    ])
    norm = _norm(text)
    flags = []
    for phrase, flag in SENSITIVE_KEYWORDS.items():
        if _norm(phrase) in norm and flag not in flags:
            flags.append(flag)

    if "POLITICAL_OR_OFFICIAL" in flags:
        flags.append("NEUTRAL_LANGUAGE_REQUIRED")
    if "LEGAL_ALLEGATION" in flags:
        flags.append("ATTRIBUTION_REQUIRED")
    if "MINOR" in flags:
        flags.append("MINOR_PRIVACY_CHECK")
    if "DEATH" in flags or "SEXUAL_HARM" in flags or "SELF_HARM" in flags:
        flags.append("SENSITIVE_TONE_REQUIRED")

    return flags


def score_editorial_value(event):
    title = event.get("title", "")
    context = event.get("context", "")
    text = f"{title} {context}"

    articles, publishers, official_count, trusted_count = _count_sources(event)
    social_sources = event.get("social_sources", [])
    specificity = event.get("specificity") or {}

    score = 0
    breakdown = {}

    source_score = 0
    if official_count:
        source_score += 18
    if trusted_count:
        source_score += min(14, 7 * trusted_count)
    if len(publishers) >= 2:
        source_score += 8
    source_score = min(source_score, 30)
    score += source_score
    breakdown["source_strength"] = source_score

    freshness_score = 12 if any(
        p.get("is_new") for p in event.get("social_posts", [])
    ) or any(
        a.get("is_new") for a in event.get("articles", [])
    ) else 4
    score += freshness_score
    breakdown["freshness"] = freshness_score

    specificity_score = 0
    if specificity.get("proper_phrases"):
        specificity_score += 5
    if specificity.get("numbers"):
        specificity_score += 4
    if specificity.get("concrete_action"):
        specificity_score += 5
    specificity_score += min(4, max(0, specificity.get("distinctive_count", 0) - 3))
    specificity_score = min(specificity_score, 16)
    score += specificity_score
    breakdown["specificity"] = specificity_score

    impact_score = 12 if _has_any(text, HIGH_IMPACT_KEYWORDS) else 4
    score += impact_score
    breakdown["impact"] = impact_score

    human_score = 8 if _has_any(text, HUMAN_INTEREST_KEYWORDS) else 2
    score += human_score
    breakdown["human_interest"] = human_score

    discussion_score = 7 if _has_any(text, DISCUSSION_KEYWORDS) else 2
    score += discussion_score
    breakdown["discussion_potential"] = discussion_score

    visual_score = 6 if _has_any(text, VISUAL_KEYWORDS) or social_sources else 2
    score += visual_score
    breakdown["visual_potential"] = visual_score

    surprise_score = 5 if _has_any(text, SURPRISE_KEYWORDS) else 1
    score += surprise_score
    breakdown["surprise"] = surprise_score

    if event.get("hot_rule") == "GENERIC_ADMIN":
        score -= 20
        breakdown["generic_admin_penalty"] = -20

    if not articles:
        score -= 18
        breakdown["no_verified_article_penalty"] = -18

    risk_flags = build_risk_flags(event)
    if len(risk_flags) >= 4:
        score -= 4
        breakdown["risk_review_penalty"] = -4

    score = max(0, min(100, score))

    if score >= 72:
        tier = "PRIORITY"
    elif score >= 56:
        tier = "GOOD"
    elif score >= 42:
        tier = "REVIEW"
    else:
        tier = "LOW"

    return {
        "score": score,
        "tier": tier,
        "breakdown": breakdown,
        "risk_flags": risk_flags,
    }


def choose_editorial_angle(event, editorial):
    text = f"{event.get('title', '')} {event.get('context', '')}"
    if _has_any(text, HUMAN_INTEREST_KEYWORDS):
        return "CON_NGUOI"
    if _has_any(text, HIGH_IMPACT_KEYWORDS):
        return "ANH_HUONG_TRUC_TIEP"
    if _has_any(text, DISCUSSION_KEYWORDS):
        return "GOC_TRANH_LUAN_CAN_BANG"
    if _has_any(text, SURPRISE_KEYWORDS):
        return "DIEM_BAT_NGO"
    if event.get("social_sources"):
        return "SOCIAL_DANG_CHU_Y_DA_XAC_MINH"
    return "TIN_MOI_CAN_BIET"


def build_editorial_package(event, source):
    editorial = score_editorial_value(event)
    preflight = monetization_preflight(event)
    angle = choose_editorial_angle(event, editorial)

    source_urls = []
    for article in event.get("articles", []):
        if article.get("url"):
            source_urls.append({
                "source": article.get("source"),
                "title": article.get("title"),
                "url": article.get("url"),
                "tier": article.get("source_tier"),
            })

    return {
        "event_id": event.get("event_id"),
        "origin": event.get("origin", []),
        "page": "Hóng Cùng Tôi",
        "status": (
            "SKIP_PRECHECK"
            if preflight.get("recommended_publish_mode") == "SKIP"
            else "NEEDS_EDITORIAL_DRAFT"
        ),
        "editorial_score": editorial,
        "recommended_angle": angle,
        "monetization_preflight": preflight,
        "working_title": event.get("title"),
        "primary_source": {
            "source": source.get("source") if source else None,
            "title": source.get("title") if source else None,
            "url": source.get("url") if source else None,
            "tier": source.get("source_tier") if source else None,
        },
        "sources": source_urls,
        "social_sources": event.get("social_sources", []),
        "verification_status": event.get("verification_status"),
        "hot_rule": event.get("hot_rule"),
        "decision_reason": event.get("decision_reason"),
        "draft_contract": {
            "main_post": {
                "goal": (
                    "Nêu ngay dữ kiện quan trọng nhất, giải thích điều gì đã xảy ra, "
                    "vì sao đáng chú ý và thông tin nào đã được xác nhận."
                ),
                "required": [
                    "Không giấu dữ kiện cốt lõi xuống bình luận.",
                    "Không dùng caption social làm nguồn xác nhận sự kiện.",
                    "Mọi dữ kiện phải truy được về nguồn đã đọc.",
                    "Tách rõ dữ kiện đã xác nhận với nhận định/ý kiến.",
                    "Không dùng tiêu đề gây hiểu sai so với nội dung nguồn.",
                ],
                "style": [
                    "Mở bài ngắn, trực tiếp.",
                    "Đoạn ngắn, dễ đọc trên Facebook.",
                    "Ưu tiên chi tiết cụ thể thay cho tính từ cường điệu.",
                    "Nếu là chủ đề chính trị/công quyền, dùng ngôn ngữ trung tính và mô tả hành động/chính sách cụ thể.",
                ],
            },
            "comment_chain": {
                "goal": "Bổ sung diễn biến, bối cảnh, số liệu và nguồn sau khi bài chính đã đủ thông tin cốt lõi.",
                "rules": [
                    "Mỗi comment phải có giá trị thông tin độc lập.",
                    "Không chia nhỏ một dữ kiện thiết yếu chỉ để kéo người đọc bấm mở thêm.",
                    "Comment cuối có thể ghi nguồn/link nguồn.",
                    "Không engagement bait kiểu yêu cầu comment/chia sẻ để xem tiếp.",
                ],
            },
            "source_note": {
                "required": True,
                "format": "Nguồn: tên cơ quan/báo + URL gốc.",
            },
            "bao_chi_tu_link_contract": {
                "source_fidelity": "Mọi dữ kiện phải truy được về bài gốc đã đọc; không thêm suy đoán, động cơ, lời thoại hoặc kết luận ngoài nguồn.",
                "monetization": "Phân biệt được phép đăng với khả năng kiếm tiền; ưu tiên phiên bản trung tính hơn khi có rủi ro.",
                "originality": "Không coi chép lại/tóm tắt tối thiểu/đổi khung là đủ nguyên bản; cần giá trị biên tập thực chất.",
                "copyright": "Credit không thay thế quyền sử dụng ảnh/video; không xóa watermark.",
                "engagement": "Không engagement bait, watch bait hoặc giấu dữ kiện trọng yếu xuống comment.",
                "legal": "Phân biệt cáo buộc, điều tra và kết luận; quy nguồn rõ với thông tin pháp lý.",
            },
        },
        "output_schema": {
            "publish_id": event.get("event_id"),
            "approved": False,
            "main_post": "",
            "comments": [],
            "source_note": "",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def sort_editorial_queue(packages):
    tier_order = {"PRIORITY": 0, "GOOD": 1, "REVIEW": 2, "LOW": 3}
    return sorted(
        packages,
        key=lambda p: (
            tier_order.get(p.get("editorial_score", {}).get("tier"), 9),
            -p.get("editorial_score", {}).get("score", 0),
        ),
    )
