import re
from urllib.parse import urlparse


ENGAGEMENT_BAIT_PATTERNS = [
    r"comment\s+\w+\s+để",
    r"bình luận\s+\w+\s+để",
    r"chia sẻ.*để xem",
    r"tag\s+\w+",
    r"thả tim.*để",
    r"like.*để",
]

MISLEADING_TEASER_PATTERNS = [
    r"không ai ngờ",
    r"cái kết khiến",
    r"sự thật phía sau.*sẽ khiến",
    r"xem comment để biết",
    r"chi tiết ở comment",
]


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def _valid_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def validate_editorial_output(item):
    draft = item.get("output_schema") or {}
    main_post = _norm(draft.get("main_post"))
    comments = [
        _norm(x)
        for x in (draft.get("comments") or [])
        if isinstance(x, str) and _norm(x)
    ]
    source_note = _norm(draft.get("source_note"))

    errors = []
    warnings = []

    if not main_post:
        errors.append("MAIN_POST_EMPTY")
    elif len(main_post) < 80:
        warnings.append("MAIN_POST_VERY_SHORT")

    if len(main_post) > 6000:
        warnings.append("MAIN_POST_VERY_LONG")

    combined = " ".join([main_post] + comments).lower()

    for pattern in ENGAGEMENT_BAIT_PATTERNS:
        if re.search(pattern, combined, flags=re.I):
            errors.append("ENGAGEMENT_BAIT")
            break

    for pattern in MISLEADING_TEASER_PATTERNS:
        if re.search(pattern, combined, flags=re.I):
            warnings.append("MISLEADING_TEASER_RISK")
            break

    if not source_note:
        errors.append("SOURCE_NOTE_EMPTY")
    elif not re.search(r"https?://\S+", source_note):
        errors.append("SOURCE_NOTE_MISSING_URL")

    declared_sources = [
        s.get("url")
        for s in item.get("sources", [])
        if s.get("url")
    ]
    source_note_urls = re.findall(r"https?://\S+", source_note)
    if declared_sources and source_note_urls:
        if not any(url.rstrip(".,);]") in declared_sources for url in source_note_urls):
            warnings.append("SOURCE_NOTE_URL_NOT_IN_DECLARED_SOURCES")

    risk_flags = set(
        (item.get("editorial_score") or {}).get("risk_flags", [])
    )

    if "NEUTRAL_LANGUAGE_REQUIRED" in risk_flags:
        politically_loaded = [
            "phản quốc", "bán nước", "độc tài", "tay sai", "lũ",
            "bọn", "ngu xuẩn", "đáng bị",
        ]
        if any(term in main_post.lower() for term in politically_loaded):
            errors.append("NON_NEUTRAL_POLITICAL_LANGUAGE")

    if "ATTRIBUTION_REQUIRED" in risk_flags:
        attribution_markers = [
            "theo ", "cơ quan", "công an", "viện kiểm sát",
            "tòa án", "thông báo", "cho biết", "xác nhận",
        ]
        if not any(marker in main_post.lower() for marker in attribution_markers):
            warnings.append("LEGAL_CLAIM_ATTRIBUTION_NOT_DETECTED")

    if "MINOR_PRIVACY_CHECK" in risk_flags:
        warnings.append("REVIEW_MINOR_PRIVACY")

    if (
        "SENSITIVE_TONE_REQUIRED" in risk_flags
        and any(x in main_post.lower() for x in ["kinh hoàng", "rợn người", "máu me"])
    ):
        errors.append("SENSATIONAL_SENSITIVE_TONE")

    if comments and len(comments) > 6:
        warnings.append("COMMENT_CHAIN_TOO_LONG")

    for index, comment in enumerate(comments, start=1):
        if len(comment) > 1800:
            warnings.append(f"COMMENT_{index}_VERY_LONG")

    return {
        "ok": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "checked_fields": {
            "main_post_chars": len(main_post),
            "comment_count": len(comments),
            "source_note_present": bool(source_note),
        },
    }


def attach_validation(item):
    updated = dict(item)
    updated["draft_validation"] = validate_editorial_output(item)
    return updated
