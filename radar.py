from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, quote
from difflib import SequenceMatcher
import feedparser
import hashlib
import json
import os
import re
import requests

# ============================================================
# HONG CUNG TOI - RADAR V7
#
# SOCIAL
#   -> POST DEDUP
#   -> EVENT CLUSTER
#   -> GOOGLE NEWS DISCOVERY
#   -> TRUSTED / OFFICIAL VERIFICATION
#   -> EDITORIAL DECISION
#
# IMPORTANT:
# Social sources are SIGNALS only.
# They are NOT treated as factual confirmation.
# ============================================================

SOURCES = {
    "BeatVN": {
        "page": "https://www.facebook.com/beatvn.network",
        "mobile": "https://m.facebook.com/beatvn.network",
    },
    "Theanh28": {
        "page": "https://www.facebook.com/Theanh28",
        "mobile": "https://m.facebook.com/Theanh28",
    },
    "Top Comments": {
        "page": "https://www.facebook.com/topcomments.vn",
        "mobile": "https://m.facebook.com/topcomments.vn",
    },
}

MAX_POSTS_PER_SOURCE = 3
SCROLL_ROUNDS = 3
SCROLL_WAIT_MS = 1200

RESULT_FILE = "radar_results.json"
EVENT_FILE = "radar_events.json"
VERIFIED_FILE = "radar_verified.json"
HISTORY_FILE = "radar_history.json"

MAX_HISTORY = 3000

EVENT_SIMILARITY_THRESHOLD = 0.42
VERIFY_SIMILARITY_THRESHOLD = 0.18

# ------------------------------------------------------------
# SOURCE TRUST LEVELS
# ------------------------------------------------------------

OFFICIAL_DOMAINS = {
    "chinhphu.vn",
    "mps.gov.vn",
    "moh.gov.vn",
    "moet.gov.vn",
    "mod.gov.vn",
    "mof.gov.vn",
    "moit.gov.vn",
    "mt.gov.vn",
    "mic.gov.vn",
    "mofa.gov.vn",
    "xaydungchinhsach.chinhphu.vn",
}

TRUSTED_NEWS_DOMAINS = {
    "vnexpress.net",
    "tuoitre.vn",
    "thanhnien.vn",
    "dantri.com.vn",
    "vietnamnet.vn",
    "vtv.vn",
    "vov.vn",
    "laodong.vn",
    "nhandan.vn",
    "vietnamplus.vn",
    "plo.vn",
    "tienphong.vn",
    "baochinhphu.vn",
}

POST_MARKERS = (
    "/posts/",
    "/videos/",
    "/reel/",
    "/permalink/",
    "/photo/",
    "story.php",
    "photo.php",
)

STOPWORDS = {
    "và", "là", "của", "có", "cho", "với", "một", "những",
    "các", "được", "đang", "đã", "sẽ", "khi", "thì", "mà",
    "tại", "trong", "sau", "trước", "này", "đó", "về",
    "theo", "từ", "đến", "trên", "dưới", "lại", "ra",
    "vào", "ở", "vẫn", "cũng", "rất", "không", "người",
    "facebook", "ảnh", "video", "clip", "xem", "thêm",
}

# ============================================================
# HISTORY
# ============================================================

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

        if isinstance(data, list):
            return {
                str(item): {
                    "first_seen": None,
                    "last_seen": None,
                }
                for item in data
            }

    except Exception as exc:
        print("History load warning:", exc)

    return {}


def save_history(history):
    items = list(history.items())

    if len(items) > MAX_HISTORY:
        items = items[-MAX_HISTORY:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            dict(items),
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# FACEBOOK URL
# ============================================================

def normalize_url(url):
    if not url:
        return None

    url = url.strip()

    if url.startswith("/"):
        url = urljoin(
            "https://www.facebook.com",
            url,
        )

    if not url.startswith("http"):
        return None

    try:
        parsed = urlparse(url)

        if "l.facebook.com" in parsed.netloc:
            query = parse_qs(parsed.query)

            if query.get("u"):
                url = query["u"][0]

    except Exception:
        pass

    url = url.replace(
        "https://m.facebook.com/",
        "https://www.facebook.com/",
    )

    url = url.replace(
        "http://m.facebook.com/",
        "https://www.facebook.com/",
    )

    low = url.lower()

    if "story.php" not in low and "photo.php" not in low:
        url = url.split("?")[0]

    url = url.split("#")[0]

    return url.rstrip("/")


def is_post_url(url):
    if not url:
        return False

    low = url.lower()

    if "facebook.com" not in low:
        return False

    return any(
        marker in low
        for marker in POST_MARKERS
    )


def post_key(url):
    if not url:
        return None

    patterns = [
        r"/posts/([^/?#]+)",
        r"/videos/([^/?#]+)",
        r"/reel/([^/?#]+)",
        r"/permalink/([^/?#]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.I)

        if match:
            return match.group(1)

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        for key in ("story_fbid", "fbid"):
            if query.get(key):
                return f"{key}:{query[key][0]}"

    except Exception:
        pass

    return hashlib.sha1(
        url.encode("utf-8")
    ).hexdigest()


# ============================================================
# TEXT
# ============================================================

def clean_text(text):
    if not text:
        return ""

    blacklist = {
        "xem thêm",
        "thích",
        "bình luận",
        "chia sẻ",
        "đăng nhập",
        "tạo tài khoản mới",
    }

    output = []
    previous = None

    for raw in text.splitlines():
        line = re.sub(
            r"\s+",
            " ",
            raw,
        ).strip()

        if not line:
            continue

        if line.lower() in blacklist:
            continue

        if line == previous:
            continue

        output.append(line)
        previous = line

    return "\n".join(output)[:5000]


def get_time_text(text):
    if not text:
        return None

    patterns = [
        r"\bvừa xong\b",
        r"\b\d+\s*phút\b",
        r"\b\d+\s*giờ\b",
        r"\b\d+\s*ngày\b",
        r"\bhôm qua\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            return match.group(0)

    return None


# ============================================================
# FACEBOOK EXTRACTION
# ============================================================

def extract_articles(page):
    found = {}

    articles = page.locator(
        'div[role="article"]'
    )

    try:
        count = articles.count()
    except Exception:
        return found

    for index in range(count):
        try:
            article = articles.nth(index)

            raw_text = article.inner_text(
                timeout=2500
            )

            text = clean_text(raw_text)

            if len(text) < 10:
                continue

            links = article.locator("a")

            try:
                link_count = links.count()
            except Exception:
                link_count = 0

            post_url = None

            for j in range(link_count):
                try:
                    href = links.nth(j).get_attribute(
                        "href"
                    )

                    href = normalize_url(href)

                    if is_post_url(href):
                        post_url = href
                        break

                except Exception:
                    continue

            if not post_url:
                continue

            key = post_key(post_url)

            if not key:
                continue

            found[key] = {
                "post_id": key,
                "url": post_url,
                "time": get_time_text(raw_text),
                "text": text,
            }

        except Exception:
            continue

    return found


def discover_entry(page, url, label):
    print()
    print("ENTRY:", label)
    print("URL:", url)

    discovered = {}

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(3500)

        print(
            "HTTP:",
            response.status if response else None,
        )

        print("TITLE:", page.title())
        print("FINAL:", page.url)

        for round_no in range(
            SCROLL_ROUNDS + 1
        ):
            batch = extract_articles(page)

            for key, post in batch.items():
                if key not in discovered:
                    discovered[key] = post
                else:
                    old_text = discovered[key].get(
                        "text",
                        "",
                    )

                    new_text = post.get(
                        "text",
                        "",
                    )

                    if len(new_text) > len(old_text):
                        discovered[key] = post

            print(
                f"  round {round_no + 1}: "
                f"{len(discovered)} candidate posts"
            )

            if len(discovered) >= MAX_POSTS_PER_SOURCE:
                break

            page.mouse.wheel(
                0,
                3500,
            )

            page.wait_for_timeout(
                SCROLL_WAIT_MS
            )

    except Exception as exc:
        print("ENTRY ERROR:", exc)

    return discovered


def collect_source(
    page,
    source_name,
    config,
):
    print()
    print("=" * 78)
    print("SOURCE:", source_name)
    print("=" * 78)

    combined = {}

    entries = [
        ("desktop", config["page"]),
        ("mobile", config["mobile"]),
    ]

    for label, url in entries:
        batch = discover_entry(
            page,
            url,
            label,
        )

        for key, post in batch.items():
            if key not in combined:
                combined[key] = post
            else:
                old_text = combined[key].get(
                    "text",
                    "",
                )

                new_text = post.get(
                    "text",
                    "",
                )

                if len(new_text) > len(old_text):
                    combined[key] = post

    posts = list(combined.values())
    posts = posts[:MAX_POSTS_PER_SOURCE]

    print(
        f">>> {source_name}: "
        f"{len(posts)} POSTS"
    )

    return posts


# ============================================================
# EVENT CLUSTERING
# ============================================================

def normalize_for_matching(text):
    if not text:
        return ""

    text = text.lower()

    text = re.sub(
        r"https?://\S+",
        " ",
        text,
    )

    text = re.sub(
        r"[^\w\sÀ-ỹ]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def keyword_set(text):
    normalized = normalize_for_matching(text)
    words = normalized.split()

    result = set()

    for word in words:
        if len(word) < 3:
            continue

        if word in STOPWORDS:
            continue

        if word.isdigit():
            continue

        result.add(word)

    return result


def similarity(text_a, text_b):
    a = normalize_for_matching(text_a)
    b = normalize_for_matching(text_b)

    if not a or not b:
        return 0.0

    sequence_score = SequenceMatcher(
        None,
        a[:1500],
        b[:1500],
    ).ratio()

    words_a = keyword_set(a)
    words_b = keyword_set(b)

    if words_a and words_b:
        intersection = len(
            words_a & words_b
        )

        union = len(
            words_a | words_b
        )

        keyword_score = (
            intersection / union
            if union
            else 0
        )
    else:
        keyword_score = 0

    return (
        sequence_score * 0.35
        + keyword_score * 0.65
    )


def choose_event_title(text):
    if not text:
        return "Chưa xác định"

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for line in lines:
        low = line.lower()

        if len(line) < 15:
            continue

        if re.fullmatch(
            r"\d+\s*(phút|giờ|ngày)",
            low,
        ):
            continue

        if low in {
            "beatvn",
            "theanh28",
            "top comments",
        }:
            continue

        return line[:220]

    return (
        lines[0][:220]
        if lines
        else "Chưa xác định"
    )


def cluster_events(posts):
    events = []

    for post in posts:
        best_event = None
        best_score = 0.0

        for event in events:
            event_best = 0.0

            for existing in event["posts"]:
                score = similarity(
                    post.get("text", ""),
                    existing.get("text", ""),
                )

                event_best = max(
                    event_best,
                    score,
                )

            if event_best > best_score:
                best_score = event_best
                best_event = event

        if (
            best_event is not None
            and best_score
            >= EVENT_SIMILARITY_THRESHOLD
        ):
            best_event["posts"].append(
                post
            )

            if (
                post["source"]
                not in best_event["sources"]
            ):
                best_event["sources"].append(
                    post["source"]
                )

        else:
            events.append({
                "event_id": (
                    "event_"
                    + hashlib.sha1(
                        (
                            post.get("text", "")
                            + post.get("url", "")
                        ).encode("utf-8")
                    ).hexdigest()[:12]
                ),

                "title": choose_event_title(
                    post.get("text", "")
                ),

                "sources": [
                    post["source"]
                ],

                "posts": [
                    post
                ],
            })

    return events


# ============================================================
# VERIFICATION SEARCH
# ============================================================

def build_search_query(event):
    """
    Use event title plus useful keywords.
    Avoid sending the whole noisy Facebook caption.
    """

    title = event.get("title", "")
    words = list(keyword_set(title))

    # Keep query short enough for news search
    words = words[:10]

    if len(words) >= 3:
        return " ".join(words)

    # Fallback to beginning of title
    return title[:180]


def google_news_search(query):
    if not query:
        return []

    rss_url = (
        "https://news.google.com/rss/search"
        "?q="
        + quote(query)
        + "&hl=vi&gl=VN&ceid=VN:vi"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            rss_url,
            headers=headers,
            timeout=20,
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

    except Exception as exc:
        print(
            "News search error:",
            exc,
        )
        return []

    results = []

    for entry in feed.entries[:15]:
        title = clean_text(
            entry.get("title", "")
        )

        url = entry.get(
            "link",
            "",
        )

        source_name = ""

        if hasattr(entry, "source"):
            try:
                source_name = entry.source.get(
                    "title",
                    "",
                )
            except Exception:
                pass

        published = entry.get(
            "published",
            "",
        )

        results.append({
            "title": title,
            "url": url,
            "source_name": source_name,
            "published": published,
        })

    return results


# ============================================================
# TRUST CLASSIFICATION
# ============================================================

def source_level_from_name(name):
    if not name:
        return "OTHER"

    low = name.lower()

    official_names = (
        "chính phủ",
        "bộ công an",
        "bộ y tế",
        "bộ giáo dục",
        "bộ quốc phòng",
        "bộ ngoại giao",
        "nhân dân",
    )

    trusted_names = (
        "vnexpress",
        "tuổi trẻ",
        "thanh niên",
        "dân trí",
        "vietnamnet",
        "vtv",
        "vov",
        "lao động",
        "vietnamplus",
        "tiền phong",
        "pháp luật",
    )

    if any(
        item in low
        for item in official_names
    ):
        return "OFFICIAL_OR_PRIMARY"

    if any(
        item in low
        for item in trusted_names
    ):
        return "TRUSTED_NEWS"

    return "OTHER"


def source_level_from_url(url):
    if not url:
        return "OTHER"

    try:
        host = urlparse(url).netloc.lower()
        host = host.replace("www.", "")

        for domain in OFFICIAL_DOMAINS:
            if (
                host == domain
                or host.endswith(
                    "." + domain
                )
            ):
                return "OFFICIAL_OR_PRIMARY"

        for domain in TRUSTED_NEWS_DOMAINS:
            if (
                host == domain
                or host.endswith(
                    "." + domain
                )
            ):
                return "TRUSTED_NEWS"

    except Exception:
        pass

    return "OTHER"


# ============================================================
# EVENT VERIFICATION
# ============================================================

def verify_event(event):
    query = build_search_query(event)

    print()
    print(
        "VERIFY QUERY:",
        query,
    )

    results = google_news_search(
        query
    )

    evidence = []

    event_text = " ".join(
        [
            event.get("title", ""),
            *[
                post.get("text", "")
                for post in event["posts"]
            ],
        ]
    )

    for result in results:
        score = similarity(
            event_text,
            result["title"],
        )

        if score < VERIFY_SIMILARITY_THRESHOLD:
            continue

        level = source_level_from_name(
            result["source_name"]
        )

        # Google News RSS normally points to a Google
        # redirect URL, so source name is also used.
        if level == "OTHER":
            url_level = source_level_from_url(
                result["url"]
            )

            if url_level != "OTHER":
                level = url_level

        result["match_score"] = round(
            score,
            3,
        )

        result["trust_level"] = level

        evidence.append(
            result
        )

    # Best evidence first
    trust_order = {
        "OFFICIAL_OR_PRIMARY": 3,
        "TRUSTED_NEWS": 2,
        "OTHER": 1,
    }

    evidence.sort(
        key=lambda item: (
            trust_order.get(
                item["trust_level"],
                0,
            ),
            item["match_score"],
        ),
        reverse=True,
    )

    official = [
        item
        for item in evidence
        if item["trust_level"]
        == "OFFICIAL_OR_PRIMARY"
    ]

    trusted = [
        item
        for item in evidence
        if item["trust_level"]
        == "TRUSTED_NEWS"
    ]

    # --------------------------------------------------------
    # Verification classification
    #
    # IMPORTANT:
    # Search-title similarity is supporting evidence,
    # not proof that every detail in a social caption is true.
    # --------------------------------------------------------

    if official:
        status = "CO_NGUON_CHINH_THONG_DOI_CHIEU"

    elif len(trusted) >= 2:
        status = "CO_NHIEU_BAO_UY_TIN_DOI_CHIEU"

    elif len(trusted) == 1:
        status = "CO_MOT_NGUON_BAO_DOI_CHIEU"

    else:
        status = "CHUA_XAC_MINH"

    event["search_query"] = query
    event["verification"] = status

    event["verification_evidence"] = (
        evidence[:5]
    )

    return event


# ============================================================
# EDITORIAL FILTER
# ============================================================

def classify_event(event):
    source_count = len(
        event["sources"]
    )

    verification = event.get(
        "verification",
        "CHUA_XAC_MINH",
    )

    if verification == "CO_NGUON_CHINH_THONG_DOI_CHIEU":
        decision = "CO_THE_LAM_BAI"
        reason = (
            "Có nguồn chính thống/nguồn sơ cấp "
            "liên quan để đối chiếu. Vẫn cần viết "
            "đúng phạm vi thông tin nguồn xác nhận."
        )

    elif verification == "CO_NHIEU_BAO_UY_TIN_DOI_CHIEU":
        decision = "CO_THE_LAM_BAI"
        reason = (
            "Có ít nhất hai nguồn báo chí uy tín "
            "đưa nội dung liên quan."
        )

    elif (
        verification
        == "CO_MOT_NGUON_BAO_DOI_CHIEU"
    ):
        decision = "THEO_DOI"
        reason = (
            "Mới tìm được một nguồn báo chí "
            "liên quan; nên tiếp tục đối chiếu."
        )

    elif source_count >= 2:
        decision = "CAN_XAC_MINH_GAP"
        reason = (
            "Cùng sự kiện đang xuất hiện ở nhiều "
            "nguồn social nhưng chưa đủ nguồn "
            "xác minh."
        )

    else:
        decision = "BO_QUA_TAM_THOI"
        reason = (
            "Chỉ có một tín hiệu social và chưa "
            "tìm được nguồn đáng tin cậy để "
            "đối chiếu."
        )

    event["source_count"] = source_count
    event["decision"] = decision
    event["decision_reason"] = reason

    return event


# ============================================================
# MAIN
# ============================================================

def main():
    now = datetime.now(
        timezone.utc
    ).isoformat()

    print("=" * 78)
    print("HONG CUNG TOI - RADAR V7")
    print(
        "SOCIAL -> EVENT -> "
        "VERIFY -> FILTER"
    )
    print("TIME:", now)
    print("=" * 78)

    history = load_history()

    print(
        "HISTORY LOADED:",
        len(history),
    )

    all_posts = []
    source_results = {}

    # --------------------------------------------------------
    # SOCIAL COLLECTION
    # --------------------------------------------------------

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1280,
                "height": 1000,
            },
            locale="vi-VN",
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 "
                "Safari/537.36"
            ),
        )

        page = context.new_page()

        for source_name, config in SOURCES.items():
            posts = collect_source(
                page,
                source_name,
                config,
            )

            source_results[
                source_name
            ] = posts

            for post in posts:
                post["source"] = (
                    source_name
                )

                all_posts.append(
                    post
                )

        browser.close()

    # --------------------------------------------------------
    # POST DEDUP
    # --------------------------------------------------------

    unique_posts = {}

    for post in all_posts:
        key = post.get(
            "post_id"
        )

        if not key:
            continue

        if key not in unique_posts:
            unique_posts[key] = post

        else:
            old_text = unique_posts[
                key
            ].get(
                "text",
                "",
            )

            new_text = post.get(
                "text",
                "",
            )

            if len(new_text) > len(old_text):
                unique_posts[
                    key
                ] = post

    # --------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------

    new_posts = []
    seen_posts = []

    for key, post in unique_posts.items():
        if key in history:
            seen_posts.append(
                post
            )

            history[key][
                "last_seen"
            ] = now

        else:
            new_posts.append(
                post
            )

            history[key] = {
                "source": post.get(
                    "source"
                ),
                "url": post.get(
                    "url"
                ),
                "first_seen": now,
                "last_seen": now,
            }

    save_history(
        history
    )

    # --------------------------------------------------------
    # EVENT CLUSTER
    # --------------------------------------------------------

    current_posts = list(
        unique_posts.values()
    )

    events = cluster_events(
        current_posts
    )

    print()
    print(
        "EVENTS TO VERIFY:",
        len(events),
    )

    # --------------------------------------------------------
    # VERIFY
    # --------------------------------------------------------

    verified_events = []

    for index, event in enumerate(
        events,
        start=1,
    ):
        print()
        print(
            f"VERIFY EVENT {index}/"
            f"{len(events)}"
        )

        print(
            "TOPIC:",
            event["title"],
        )

        event = verify_event(
            event
        )

        event = classify_event(
            event
        )

        verified_events.append(
            event
        )

    # Most actionable first
    decision_order = {
        "CO_THE_LAM_BAI": 4,
        "CAN_XAC_MINH_GAP": 3,
        "THEO_DOI": 2,
        "BO_QUA_TAM_THOI": 1,
    }

    verified_events.sort(
        key=lambda event: (
            decision_order.get(
                event["decision"],
                0,
            ),
            event["source_count"],
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # OUTPUT FILES
    # --------------------------------------------------------

    result_output = {
        "generated_at": now,

        "source_stats": {
            source: len(posts)
            for source, posts
            in source_results.items()
        },

        "collected": len(
            all_posts
        ),

        "unique": len(
            unique_posts
        ),

        "new": len(
            new_posts
        ),

        "already_seen": len(
            seen_posts
        ),

        "new_posts": new_posts,
    }

    with open(
        RESULT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            result_output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    event_output = {
        "generated_at": now,
        "event_count": len(
            verified_events
        ),
        "events": verified_events,
    }

    with open(
        EVENT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            event_output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    actionable = [
        event
        for event in verified_events
        if event["decision"]
        in {
            "CO_THE_LAM_BAI",
            "CAN_XAC_MINH_GAP",
            "THEO_DOI",
        }
    ]

    verified_output = {
        "generated_at": now,
        "actionable_count": len(
            actionable
        ),
        "events": actionable,
    }

    with open(
        VERIFIED_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            verified_output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # CONSOLE
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print("FINAL RADAR RESULT")
    print("=" * 78)

    print(
        "SOURCE STATS:",
        result_output[
            "source_stats"
        ],
    )

    print(
        "COLLECTED:",
        result_output[
            "collected"
        ],
    )

    print(
        "UNIQUE:",
        result_output[
            "unique"
        ],
    )

    print(
        "NEW:",
        result_output[
            "new"
        ],
    )

    print(
        "ALREADY SEEN:",
        result_output[
            "already_seen"
        ],
    )

    print(
        "EVENTS:",
        len(
            verified_events
        ),
    )

    print(
        "ACTIONABLE:",
        len(
            actionable
        ),
    )

    print()
    print("=" * 78)
    print("VERIFICATION RADAR")
    print("=" * 78)

    for index, event in enumerate(
        verified_events,
        start=1,
    ):
        print()
        print(
            f"EVENT #{index}"
        )

        print(
            "TOPIC:",
            event["title"],
        )

        print(
            "SOCIAL SOURCES:",
            " + ".join(
                event["sources"]
            ),
        )

        print(
            "VERIFICATION:",
            event[
                "verification"
            ],
        )

        print(
            "DECISION:",
            event[
                "decision"
            ],
        )

        print(
            "REASON:",
            event[
                "decision_reason"
            ],
        )

        print(
            "SEARCH:",
            event[
                "search_query"
            ],
        )

        evidence = event.get(
            "verification_evidence",
            [],
        )

        print(
            "CONFIRMING SOURCES:",
            len(evidence),
        )

        for item in evidence[:5]:
            print(
                " -",
                f'[{item["trust_level"]}]',
                item["source_name"],
                "|",
                item["title"][:180],
            )

    print()
    print("Saved:", RESULT_FILE)
    print("Events:", EVENT_FILE)
    print("Verified:", VERIFIED_FILE)
    print("History:", HISTORY_FILE)
    print("HISTORY SIZE:", len(history))

    print(
        "=== RADAR V7 FINISHED ==="
    )


if __name__ == "__main__":
    main()
