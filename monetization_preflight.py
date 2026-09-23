import re
import unicodedata


# Heuristic preflight derived from the bao-chi-tu-link editorial/monetization rules.
# This is a conservative internal gate, not a guarantee of Meta eligibility.


HIGH_RISK_TERMS = {
    "tu sat": ("SELF_HARM", "HIGH"),
    "tu tu": ("SELF_HARM", "HIGH"),
    "hiep dam": ("SEXUAL_HARM", "HIGH"),
    "xam hai tinh duc": ("SEXUAL_HARM", "HIGH"),
    "xac chet": ("GRAPHIC_DEATH", "HIGH"),
    "thi the": ("GRAPHIC_DEATH", "HIGH"),
    "ma tuy": ("DRUGS", "HIGH"),
    "chat cam": ("DRUGS", "HIGH"),
}

MEDIUM_RISK_TERMS = {
    "tu vong": ("DEATH", "MEDIUM"),
    "chet": ("DEATH", "MEDIUM"),
    "thuong tich": ("INJURY", "MEDIUM"),
    "tai nan": ("ACCIDENT", "MEDIUM"),
    "chay": ("DISASTER", "MEDIUM"),
    "no": ("DISASTER", "MEDIUM"),
    "bao": ("DISASTER", "MEDIUM"),
    "lu": ("DISASTER", "MEDIUM"),
    "dong dat": ("DISASTER", "MEDIUM"),
    "bat giu": ("CRIME", "MEDIUM"),
    "khoi to": ("CRIME", "MEDIUM"),
    "dieu tra": ("CRIME", "MEDIUM"),
    "nghi pham": ("CRIME", "MEDIUM"),
    "tranh cai": ("CONTROVERSIAL_ISSUE", "MEDIUM"),
}

POLITICAL_OR_OFFICIAL_TERMS = {
    "chinh phu", "thu tuong", "quoc hoi", "bo truong", "chu tich",
    "bo cong an", "bo quoc phong", "uy ban", "chinh quyen",
}

MINOR_TERMS = {
    "tre em", "em be", "hoc sinh", "tre vi thanh nien", "be trai", "be gai",
}

COMMERCIAL_TERMS = {
    "tai tro", "quang cao", "affiliate", "lien ket mua hang", "ma giam gia",
}

SENSATIONAL_TERMS = {
    "kinh hoang", "ron nguoi", "soc nang", "chấn động", "chấn động",
    "máu me", "ghê rợn", "không ai ngờ", "cái kết khiến",
}


def _strip_accents(text):
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def _norm(text):
    text = _strip_accents((text or "").lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains(text, phrase):
    return _norm(phrase) in _norm(text)


def _event_text(event):
    return " ".join([
        event.get("title", ""),
        event.get("context", ""),
        " ".join(x.get("text", "") for x in event.get("social_posts", [])),
        " ".join(x.get("title", "") for x in event.get("articles", [])),
    ])


def monetization_preflight(event):
    text = _event_text(event)
    flags = []
    reasons = []
    risk_rank = 0

    for phrase, (flag, level) in HIGH_RISK_TERMS.items():
        if _contains(text, phrase):
            flags.append(flag)
            reasons.append(f"Chủ đề nhạy cảm: {phrase}.")
            risk_rank = max(risk_rank, 3)

    for phrase, (flag, level) in MEDIUM_RISK_TERMS.items():
        if _contains(text, phrase):
            flags.append(flag)
            reasons.append(f"Chủ đề có thể bị hạn chế kiếm tiền: {phrase}.")
            risk_rank = max(risk_rank, 2)

    if any(_contains(text, term) for term in POLITICAL_OR_OFFICIAL_TERMS):
        flags.extend(["POLITICAL_OR_OFFICIAL", "NEUTRAL_LANGUAGE_REQUIRED"])
        reasons.append("Nội dung liên quan chính trị/công quyền: yêu cầu ngôn ngữ trung tính.")
        risk_rank = max(risk_rank, 1)

    if any(_contains(text, term) for term in MINOR_TERMS):
        flags.extend(["MINOR", "MINOR_PRIVACY_CHECK"])
        reasons.append("Có yếu tố trẻ em/vị thành niên: cần rà soát quyền riêng tư và cách mô tả.")
        risk_rank = max(risk_rank, 1)

    if any(_contains(text, term) for term in COMMERCIAL_TERMS):
        flags.append("COMMERCIAL_DISCLOSURE_CHECK")
        reasons.append("Có dấu hiệu nội dung thương mại/tài trợ: cần kiểm tra disclosure.")
        risk_rank = max(risk_rank, 1)

    if any(_contains(text, term) for term in SENSATIONAL_TERMS):
        flags.append("SENSATIONAL_WORDING_RISK")
        reasons.append("Có từ ngữ dễ dẫn tới giật gân/clickbait; cần biên tập lại trung tính.")
        risk_rank = max(risk_rank, 2)

    if "CRIME" in flags:
        flags.append("ATTRIBUTION_REQUIRED")
    if any(flag in flags for flag in ["DEATH", "GRAPHIC_DEATH", "SEXUAL_HARM", "SELF_HARM"]):
        flags.append("SENSITIVE_TONE_REQUIRED")

    articles = [
        a for a in event.get("articles", [])
        if a.get("url") or a.get("google_url")
    ]
    if not articles:
        flags.append("SOURCE_INTEGRITY_BLOCK")
        reasons.append("Chưa có bài nguồn đọc được; không đủ điều kiện biên soạn hoàn chỉnh.")
        risk_rank = max(risk_rank, 3)

    # Third-party newsroom material has an inherent originality/copyright concern.
    originality_risk = "MEDIUM" if articles else "HIGH"
    copyright_risk = "MEDIUM" if articles else "HIGH"

    if risk_rank >= 3:
        monetization_risk = "HIGH"
    elif risk_rank == 2:
        monetization_risk = "MEDIUM"
    else:
        monetization_risk = "LOW"

    publish_mode = "POST"
    if "SOURCE_INTEGRITY_BLOCK" in flags:
        publish_mode = "SKIP"
    elif monetization_risk in {"MEDIUM", "HIGH"}:
        publish_mode = "POST_WITH_CAUTION"

    checklist = {
        "community_standards_check": (
            "REVIEW_REQUIRED" if monetization_risk in {"MEDIUM", "HIGH"} else "NO_OBVIOUS_RISK"
        ),
        "monetization_check": monetization_risk,
        "originality_check": originality_risk,
        "copyright_check": copyright_risk,
        "engagement_bait_check": "MUST_VALIDATE_DRAFT",
        "source_integrity_check": (
            "PASS_SOURCE_SIGNAL_PRESENT" if articles else "BLOCK_NO_SOURCE"
        ),
    }

    return {
        "monetization_risk": monetization_risk,
        "monetization_reason": " ".join(reasons) or "Không phát hiện cờ rủi ro nổi bật ở bước tiền kiểm.",
        "originality_risk": originality_risk,
        "originality_note": (
            "Tóm tắt/ảnh bên thứ ba đơn thuần có rủi ro unoriginal content; "
            "cần giá trị biên tập thực chất và không bịa thêm dữ kiện."
        ),
        "copyright_risk": copyright_risk,
        "copyright_note": (
            "Ghi nguồn không đồng nghĩa có quyền tái sử dụng ảnh/video; "
            "ưu tiên tài sản do Page sở hữu hoặc có quyền sử dụng rõ ràng."
        ),
        "risk_flags": sorted(set(flags)),
        "checklist": checklist,
        "recommended_publish_mode": publish_mode,
        "policy_note": (
            "Đây là tiền kiểm nội bộ, không phải cam kết đủ điều kiện kiếm tiền. "
            "Chính sách Meta và quyết định thực tế có thể thay đổi."
        ),
    }
