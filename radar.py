from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qs,
    quote,
    unquote,
)
from difflib import SequenceMatcher
from bs4 import BeautifulSoup
import feedparser
import hashlib
import json
import os
import re
import requests
import unicodedata


# ============================================================
# HONG CUNG TOI - RADAR V7.3
#
# OFFICIAL FB + SOCIAL RADAR
#        ↓
# BETTER POST EXTRACTION
#        ↓
# DEDUP + EVENT CLUSTER
#        ↓
# EVENT QUALITY FILTER
#        ↓
# STRICT SAME-EVENT MATCHING
#        ↓
# GOOGLE NEWS + WEB SEARCH
#        ↓
# ORIGINAL PUBLISHER URL
#        ↓
# EDITOR QUEUE -> bao-chi-tu-link
#
# IMPORTANT:
# - Social pages are trend signals only.
# - Official Facebook pages are official signals.
# - Only original publisher URLs can enter editor queue.
# - Matching words alone never proves an event.
# ============================================================


VERSION = "7.3"
PAGE_NAME = "Hóng Cùng Tôi"


# ============================================================
# FACEBOOK SOURCES
# ============================================================

SOURCES = {
    "Thông tin Chính phủ": {
        "page": "https://www.facebook.com/thongtinchinhphu",
        "mobile": "https://m.facebook.com/thongtinchinhphu",
        "tier": "OFFICIAL",

        # Used when an official Facebook post is detected.
        "official_domains": [
            "chinhphu.vn",
            "baochinhphu.vn",
            "xaydungchinhsach.chinhphu.vn",
        ],
    },

    "Bộ Công an": {
        "page": "https://www.facebook.com/mps.gov",
        "mobile": "https://m.facebook.com/mps.gov",
        "tier": "OFFICIAL",

        "official_domains": [
            "mps.gov.vn",
        ],
    },

    "BeatVN": {
        "page": "https://www.facebook.com/beatvn.network",
        "mobile": "https://m.facebook.com/beatvn.network",
        "tier": "SOCIAL_RADAR",
    },

    "Theanh28": {
        "page": "https://www.facebook.com/Theanh28",
        "mobile": "https://m.facebook.com/Theanh28",
        "tier": "SOCIAL_RADAR",
    },

    "Top Comments": {
        "page": "https://www.facebook.com/topcomments.vn",
        "mobile": "https://m.facebook.com/topcomments.vn",
        "tier": "SOCIAL_RADAR",
    },

    "Bí Mật Showbiz": {
        "page": "https://www.facebook.com/bmsb.vnn",
        "mobile": "https://m.facebook.com/bmsb.vnn",
        "tier": "SOCIAL_RADAR",
    },
}


# ============================================================
# SETTINGS
# ============================================================

MAX_POSTS_PER_SOURCE = 3

SCROLL_ROUNDS = 4
SCROLL_WAIT_MS = 1300

MAX_HISTORY = 4000

EVENT_SIMILARITY_THRESHOLD = 0.42

RESULT_FILE = "radar_results.json"
EVENT_FILE = "radar_events.json"
VERIFIED_FILE = "radar_verified.json"
EDITOR_QUEUE_FILE = "radar_editor_queue.json"
HISTORY_FILE = "radar_history.json"


# ============================================================
# TRUSTED DOMAINS
# ============================================================

OFFICIAL_DOMAINS = {
    "chinhphu.vn",
    "baochinhphu.vn",
    "xaydungchinhsach.chinhphu.vn",
    "mps.gov.vn",
    "moh.gov.vn",
    "moet.gov.vn",
    "mod.gov.vn",
    "mof.gov.vn",
    "moit.gov.vn",
    "mofa.gov.vn",
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
    "vtcnews.vn",
}


# Publisher name -> likely original domain.
PUBLISHER_DOMAIN_HINTS = {
    "vnexpress": "vnexpress.net",
    "tuổi trẻ": "tuoitre.vn",
    "tuoi tre": "tuoitre.vn",
    "thanh niên": "thanhnien.vn",
    "thanh nien": "thanhnien.vn",
    "dân trí": "dantri.com.vn",
    "dan tri": "dantri.com.vn",
    "vietnamnet": "vietnamnet.vn",
    "vtv": "vtv.vn",
    "vov": "vov.vn",
    "lao động": "laodong.vn",
    "lao dong": "laodong.vn",
    "nhân dân": "nhandan.vn",
    "nhan dan": "nhandan.vn",
    "vietnamplus": "vietnamplus.vn",
    "tiền phong": "tienphong.vn",
    "tien phong": "tienphong.vn",
    "pháp luật": "plo.vn",
    "phap luat": "plo.vn",
    "vtc news": "vtcnews.vn",
    "báo chính phủ": "baochinhphu.vn",
    "bao chinh phu": "baochinhphu.vn",
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


# ============================================================
# LANGUAGE FILTERS
# ============================================================

STOPWORDS = {
    "va",
    "la",
    "cua",
    "co",
    "cho",
    "voi",
    "mot",
    "nhung",
    "cac",
    "duoc",
    "dang",
    "da",
    "se",
    "khi",
    "thi",
    "ma",
    "tai",
    "trong",
    "sau",
    "truoc",
    "nay",
    "do",
    "ve",
    "theo",
    "tu",
    "den",
    "tren",
    "duoi",
    "lai",
    "ra",
    "vao",
    "van",
    "cung",
    "rat",
    "khong",
    "facebook",
    "anh",
    "video",
    "clip",
    "xem",
    "them",
}


# Generic words should not prove that two stories are the same.
GENERIC_WORDS = {
    "nguoi",
    "con",
    "trung",
    "tam",
    "muc",
    "tieu",
    "phat",
    "trien",
    "thong",
    "tin",
    "moi",
    "hom",
    "nay",
    "vui",
    "buon",
    "khoc",
    "cuoi",
    "chuyen",
    "cau",
    "noi",
    "chia",
    "se",
    "dang",
    "duoc",
    "anh",
    "video",
    "su",
    "viec",
    "trang",
    "mang",
    "dan",
    "mang",
    "bat",
    "ngo",
    "gay",
    "chu",
    "y",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def strip_accents(text):
    if not text:
        return ""

    text = unicodedata.normalize(
        "NFD",
        text,
    )

    text = "".join(
        char
        for char in text
        if unicodedata.category(char)
        != "Mn"
    )

    return (
        text
        .replace("đ", "d")
        .replace("Đ", "D")
    )


def normalize_for_matching(text):
    if not text:
        return ""

    text = strip_accents(
        text.lower()
    )

    text = re.sub(
        r"https?://\S+",
        " ",
        text,
    )

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


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

    return "\n".join(output)[:6000]


def ordered_unique(items):
    result = []

    for item in items:
        if item not in result:
            result.append(item)

    return result


def significant_words(text):
    normalized = normalize_for_matching(
        text
    )

    words = []

    for word in normalized.split():
        if len(word) < 3:
            continue

        if word in STOPWORDS:
            continue

        if word.isdigit():
            continue

        words.append(word)

    return words


def distinctive_words(text):
    return [
        word
        for word in ordered_unique(
            significant_words(text)
        )
        if word not in GENERIC_WORDS
    ]


def get_domain(url):
    if not url:
        return ""

    try:
        host = (
            urlparse(url)
            .netloc
            .lower()
        )

        if host.startswith("www."):
            host = host[4:]

        return host

    except Exception:
        return ""


def domain_matches(
    host,
    domain,
):
    return (
        host == domain
        or host.endswith(
            "." + domain
        )
    )


def trusted_level_from_url(url):
    host = get_domain(url)

    if not host:
        return "OTHER"

    for domain in OFFICIAL_DOMAINS:
        if domain_matches(
            host,
            domain,
        ):
            return "OFFICIAL"

    for domain in TRUSTED_NEWS_DOMAINS:
        if domain_matches(
            host,
            domain,
        ):
            return "TRUSTED_NEWS"

    return "OTHER"


def publisher_domain(
    source_name,
):
    low = normalize_for_matching(
        source_name
    )

    for name, domain in (
        PUBLISHER_DOMAIN_HINTS.items()
    ):
        if (
            normalize_for_matching(name)
            in low
        ):
            return domain

    return None


# ============================================================
# HISTORY
# ============================================================

def load_history():
    if not os.path.exists(
        HISTORY_FILE
    ):
        return {}

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if isinstance(
            data,
            dict,
        ):
            return data

    except Exception as exc:
        print(
            "History load warning:",
            exc,
        )

    return {}


def save_history(history):
    items = list(
        history.items()
    )

    if len(items) > MAX_HISTORY:
        items = items[
            -MAX_HISTORY:
        ]

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            dict(items),
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# FACEBOOK URL HELPERS
# ============================================================

def normalize_fb_url(url):
    if not url:
        return None

    url = url.strip()

    if url.startswith("/"):
        url = urljoin(
            "https://www.facebook.com",
            url,
        )

    if not url.startswith(
        "http"
    ):
        return None

    try:
        parsed = urlparse(url)

        if (
            "l.facebook.com"
            in parsed.netloc
        ):
            query = parse_qs(
                parsed.query
            )

            if query.get("u"):
                url = (
                    query["u"][0]
                )

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

    if (
        "story.php" not in low
        and "photo.php" not in low
    ):
        url = url.split(
            "?"
        )[0]

    return (
        url
        .split("#")[0]
        .rstrip("/")
    )


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
        match = re.search(
            pattern,
            url,
            re.I,
        )

        if match:
            return (
                match.group(1)
            )

    try:
        parsed = urlparse(url)
        query = parse_qs(
            parsed.query
        )

        for key in (
            "story_fbid",
            "fbid",
        ):
            if query.get(key):
                return (
                    f"{key}:"
                    f"{query[key][0]}"
                )

    except Exception:
        pass

    return hashlib.sha1(
        url.encode("utf-8")
    ).hexdigest()


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
        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            return (
                match.group(0)
            )

    return None


# ============================================================
# FACEBOOK EXTRACTION - STANDARD
# ============================================================

def extract_role_articles(page):
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
            article = (
                articles.nth(index)
            )

            raw_text = (
                article.inner_text(
                    timeout=2500
                )
            )

            text = clean_text(
                raw_text
            )

            if len(text) < 12:
                continue

            links = (
                article.locator("a")
            )

            link_count = (
                links.count()
            )

            post_url = None

            for j in range(
                link_count
            ):
                try:
                    href = (
                        links.nth(j)
                        .get_attribute(
                            "href"
                        )
                    )

                    href = (
                        normalize_fb_url(
                            href
                        )
                    )

                    if is_post_url(
                        href
                    ):
                        post_url = href
                        break

                except Exception:
                    continue

            if not post_url:
                continue

            key = post_key(
                post_url
            )

            if not key:
                continue

            found[key] = {
                "post_id": key,
                "url": post_url,
                "time": (
                    get_time_text(
                        raw_text
                    )
                ),
                "text": text,
                "extractor":
                    "role_article",
            }

        except Exception:
            continue

    return found


# ============================================================
# FACEBOOK EXTRACTION - FALLBACK
#
# Helps pages where Facebook does not expose role="article".
# It finds post/reel links then reads surrounding visible text.
# ============================================================

def extract_fallback_links(page):
    found = {}

    try:
        links = page.locator(
            "a[href]"
        )

        count = links.count()

    except Exception:
        return found

    for index in range(
        min(count, 600)
    ):
        try:
            anchor = links.nth(
                index
            )

            href = anchor.get_attribute(
                "href"
            )

            href = normalize_fb_url(
                href
            )

            if not is_post_url(
                href
            ):
                continue

            key = post_key(
                href
            )

            if not key:
                continue

            if key in found:
                continue

            candidate_text = ""

            # Move upward through Facebook's nested DOM.
            for level in (
                2,
                3,
                4,
                5,
                6,
            ):
                try:
                    node = anchor.locator(
                        "/.."
                        * level
                    )

                    text = clean_text(
                        node.inner_text(
                            timeout=1000
                        )
                    )

                    if (
                        20
                        <= len(text)
                        <= 6000
                    ):
                        if (
                            len(text)
                            > len(
                                candidate_text
                            )
                        ):
                            candidate_text = (
                                text
                            )

                except Exception:
                    continue

            if (
                len(candidate_text)
                < 12
            ):
                continue

            found[key] = {
                "post_id": key,
                "url": href,
                "time": (
                    get_time_text(
                        candidate_text
                    )
                ),
                "text":
                    candidate_text,
                "extractor":
                    "link_fallback",
            }

        except Exception:
            continue

    return found


def extract_posts(page):
    found = {}

    standard = (
        extract_role_articles(
            page
        )
    )

    fallback = (
        extract_fallback_links(
            page
        )
    )

    for source in (
        standard,
        fallback,
    ):
        for key, post in (
            source.items()
        ):
            if key not in found:
                found[key] = post

            else:
                current = (
                    found[key]
                    .get(
                        "text",
                        "",
                    )
                )

                incoming = (
                    post.get(
                        "text",
                        "",
                    )
                )

                if (
                    len(incoming)
                    > len(current)
                ):
                    found[key] = post

    return found


# ============================================================
# FACEBOOK SOURCE COLLECTION
# ============================================================

def discover_entry(
    page,
    url,
    label,
):
    print()
    print(
        "ENTRY:",
        label,
    )
    print(
        "URL:",
        url,
    )

    discovered = {}

    try:
        response = page.goto(
            url,
            wait_until=(
                "domcontentloaded"
            ),
            timeout=60000,
        )

        page.wait_for_timeout(
            3500
        )

        print(
            "HTTP:",
            response.status
            if response
            else None,
        )

        print(
            "TITLE:",
            page.title(),
        )

        print(
            "FINAL:",
            page.url,
        )

        for round_no in range(
            SCROLL_ROUNDS + 1
        ):
            batch = extract_posts(
                page
            )

            for key, post in (
                batch.items()
            ):
                if (
                    key
                    not in discovered
                ):
                    discovered[
                        key
                    ] = post

                else:
                    old_text = (
                        discovered[key]
                        .get(
                            "text",
                            "",
                        )
                    )

                    new_text = (
                        post.get(
                            "text",
                            "",
                        )
                    )

                    if (
                        len(new_text)
                        > len(old_text)
                    ):
                        discovered[
                            key
                        ] = post

            print(
                f"  round "
                f"{round_no + 1}: "
                f"{len(discovered)} "
                f"candidate posts"
            )

            if (
                len(discovered)
                >= MAX_POSTS_PER_SOURCE
            ):
                break

            page.mouse.wheel(
                0,
                4000,
            )

            page.wait_for_timeout(
                SCROLL_WAIT_MS
            )

    except Exception as exc:
        print(
            "ENTRY ERROR:",
            exc,
        )

    return discovered


def collect_source(
    page,
    source_name,
    config,
):
    print()
    print(
        "=" * 78
    )
    print(
        "SOURCE:",
        source_name,
    )
    print(
        "TIER:",
        config["tier"],
    )
    print(
        "=" * 78
    )

    combined = {}

    entries = [
        (
            "desktop",
            config["page"],
        ),
        (
            "mobile",
            config["mobile"],
        ),
    ]

    for label, url in entries:
        batch = discover_entry(
            page,
            url,
            label,
        )

        for key, post in (
            batch.items()
        ):
            if key not in combined:
                combined[
                    key
                ] = post

            else:
                old_text = (
                    combined[key]
                    .get(
                        "text",
                        "",
                    )
                )

                new_text = (
                    post.get(
                        "text",
                        "",
                    )
                )

                if (
                    len(new_text)
                    > len(old_text)
                ):
                    combined[
                        key
                    ] = post

    posts = list(
        combined.values()
    )[
        :MAX_POSTS_PER_SOURCE
    ]

    for post in posts:
        post[
            "source"
        ] = source_name

        post[
            "source_tier"
        ] = config["tier"]

    print(
        f">>> {source_name}: "
        f"{len(posts)} POSTS"
    )

    return posts


# ============================================================
# TEXT SIMILARITY
# ============================================================

def keyword_set(text):
    return set(
        significant_words(
            text
        )
    )


def similarity(
    text_a,
    text_b,
):
    a = normalize_for_matching(
        text_a
    )

    b = normalize_for_matching(
        text_b
    )

    if not a or not b:
        return 0.0

    sequence_score = (
        SequenceMatcher(
            None,
            a[:1800],
            b[:1800],
        ).ratio()
    )

    words_a = keyword_set(
        a
    )

    words_b = keyword_set(
        b
    )

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
        sequence_score * 0.30
        + keyword_score * 0.70
    )


# ============================================================
# EVENT TITLE QUALITY
# ============================================================

def line_information_score(line):
    normalized = (
        normalize_for_matching(
            line
        )
    )

    words = (
        normalized.split()
    )

    if len(words) < 3:
        return -100

    unique = set(
        significant_words(
            line
        )
    )

    distinctive = set(
        distinctive_words(
            line
        )
    )

    score = 0

    score += min(
        len(line),
        220,
    ) * 0.03

    score += (
        len(unique)
        * 1.2
    )

    score += (
        len(distinctive)
        * 2.0
    )

    if re.search(
        r"\d",
        line,
    ):
        score += 2

    if len(
        distinctive
    ) < 2:
        score -= 8

    generic_only = (
        len(distinctive) == 0
    )

    if generic_only:
        score -= 20

    return score


def choose_event_title(text):
    if not text:
        return "Chưa xác định"

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    blocked = {
        "beatvn",
        "theanh28",
        "top comments",
        "bí mật showbiz",
        "thông tin chính phủ",
        "bộ công an",
    }

    candidates = []

    for line in lines:
        low = line.lower()

        if low in blocked:
            continue

        if re.fullmatch(
            r"\d+\s*"
            r"(phút|giờ|ngày)",
            low,
        ):
            continue

        if len(line) < 12:
            continue

        candidates.append(
            (
                line_information_score(
                    line
                ),
                line,
            )
        )

    if not candidates:
        return (
            lines[0][:240]
            if lines
            else "Chưa xác định"
        )

    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    return (
        candidates[0][1][:240]
    )


# ============================================================
# EVENT CLUSTERING
# ============================================================

def cluster_events(posts):
    events = []

    for post in posts:
        best_event = None
        best_score = 0.0

        for event in events:
            event_best = 0.0

            for existing in (
                event["posts"]
            ):
                score = similarity(
                    post.get(
                        "text",
                        "",
                    ),
                    existing.get(
                        "text",
                        "",
                    ),
                )

                event_best = max(
                    event_best,
                    score,
                )

            if (
                event_best
                > best_score
            ):
                best_score = (
                    event_best
                )

                best_event = event

        if (
            best_event is not None
            and best_score
            >= EVENT_SIMILARITY_THRESHOLD
        ):
            best_event[
                "posts"
            ].append(
                post
            )

            if (
                post["source"]
                not in best_event[
                    "sources"
                ]
            ):
                best_event[
                    "sources"
                ].append(
                    post["source"]
                )

            if (
                post["source_tier"]
                not in best_event[
                    "source_tiers"
                ]
            ):
                best_event[
                    "source_tiers"
                ].append(
                    post[
                        "source_tier"
                    ]
                )

        else:
            event_hash = (
                hashlib.sha1(
                    (
                        post.get(
                            "text",
                            "",
                        )
                        + post.get(
                            "url",
                            "",
                        )
                    ).encode(
                        "utf-8"
                    )
                )
                .hexdigest()[:12]
            )

            events.append({
                "event_id":
                    "event_"
                    + event_hash,

                "title":
                    choose_event_title(
                        post.get(
                            "text",
                            "",
                        )
                    ),

                "sources": [
                    post["source"]
                ],

                "source_tiers": [
                    post[
                        "source_tier"
                    ]
                ],

                "posts": [
                    post
                ],
            })

    return events


# ============================================================
# EVENT QUALITY
# ============================================================

def event_quality(event):
    title = event.get(
        "title",
        "",
    )

    sig = ordered_unique(
        significant_words(
            title
        )
    )

    distinct = (
        distinctive_words(
            title
        )
    )

    official = (
        "OFFICIAL"
        in event.get(
            "source_tiers",
            []
        )
    )

    # Official signals are always worth attempting to source.
    if official:
        return {
            "valid": True,
            "reason":
                "official_signal",
        }

    if len(sig) < 3:
        return {
            "valid": False,
            "reason":
                "too_few_keywords",
        }

    if len(distinct) < 2:
        return {
            "valid": False,
            "reason":
                "too_generic",
        }

    if len(
        normalize_for_matching(
            title
        )
    ) < 15:
        return {
            "valid": False,
            "reason":
                "title_too_short",
        }

    return {
        "valid": True,
        "reason": "ok",
    }


# ============================================================
# SEARCH QUERY
# ============================================================

def build_search_query(event):
    title = clean_text(
        event.get(
            "title",
            "",
        )
    )

    words = ordered_unique(
        significant_words(
            title
        )
    )

    distinct = [
        word
        for word in words
        if word
        not in GENERIC_WORDS
    ]

    chosen = []

    # Prefer distinctive terms.
    for word in distinct:
        if word not in chosen:
            chosen.append(word)

        if len(chosen) >= 8:
            break

    # Fill with normal terms if needed.
    for word in words:
        if word not in chosen:
            chosen.append(word)

        if len(chosen) >= 10:
            break

    if chosen:
        return " ".join(
            chosen
        )

    return title[:180]


# ============================================================
# SAME-EVENT MATCH V7.3
#
# Core fix for false positives.
# ============================================================

def contiguous_phrase_match(
    event_words,
    article_text,
):
    article_norm = (
        normalize_for_matching(
            article_text
        )
    )

    if not event_words:
        return False

    # Short topics / names:
    # require the full phrase in order.
    if len(event_words) <= 4:
        phrase = " ".join(
            event_words
        )

        return (
            phrase in article_norm
        )

    # For longer events, a 3-word distinctive phrase
    # is a strong signal.
    for size in (
        4,
        3,
    ):
        if len(event_words) < size:
            continue

        for index in range(
            len(event_words)
            - size
            + 1
        ):
            phrase_words = (
                event_words[
                    index:
                    index + size
                ]
            )

            useful = [
                w
                for w in phrase_words
                if w
                not in GENERIC_WORDS
            ]

            if len(useful) < 2:
                continue

            phrase = " ".join(
                phrase_words
            )

            if (
                phrase
                in article_norm
            ):
                return True

    return False


def same_event_match(
    event,
    article_title,
):
    event_title = (
        event.get(
            "title",
            ""
        )
    )

    event_words = (
        ordered_unique(
            significant_words(
                event_title
            )
        )
    )

    article_words = set(
        significant_words(
            article_title
        )
    )

    event_distinctive = [
        word
        for word
        in event_words
        if word
        not in GENERIC_WORDS
    ]

    article_distinctive = {
        word
        for word
        in article_words
        if word
        not in GENERIC_WORDS
    }

    matched_all = [
        word
        for word
        in event_words
        if word
        in article_words
    ]

    matched_distinctive = [
        word
        for word
        in event_distinctive
        if word
        in article_distinctive
    ]

    total_distinctive = (
        len(
            event_distinctive
        )
    )

    distinctive_coverage = (
        len(
            matched_distinctive
        )
        / total_distinctive
        if total_distinctive
        else 0
    )

    text_similarity = (
        SequenceMatcher(
            None,
            normalize_for_matching(
                event_title
            ),
            normalize_for_matching(
                article_title
            ),
        ).ratio()
    )

    phrase_match = (
        contiguous_phrase_match(
            event_words,
            article_title,
        )
    )

    accepted = False

    # --------------------------------------------------------
    # Short title / possible name:
    # generic token overlap is NOT enough.
    # --------------------------------------------------------

    if len(event_words) <= 4:
        accepted = (
            phrase_match
            and len(
                matched_all
            ) >= min(
                3,
                len(
                    event_words
                ),
            )
        )

    # --------------------------------------------------------
    # Medium event
    # --------------------------------------------------------

    elif len(event_words) <= 8:
        accepted = (
            (
                phrase_match
                and len(
                    matched_distinctive
                ) >= 2
            )
            or
            (
                len(
                    matched_distinctive
                ) >= 3
                and distinctive_coverage
                >= 0.50
                and text_similarity
                >= 0.22
            )
        )

    # --------------------------------------------------------
    # Long descriptive event
    # --------------------------------------------------------

    else:
        accepted = (
            (
                phrase_match
                and len(
                    matched_distinctive
                ) >= 2
            )
            or
            (
                len(
                    matched_distinctive
                ) >= 4
                and distinctive_coverage
                >= 0.30
                and text_similarity
                >= 0.18
            )
        )

    # Extra protection:
    # if almost all overlap is generic words, reject.
    if (
        accepted
        and len(
            matched_distinctive
        ) < 2
        and not phrase_match
    ):
        accepted = False

    return {
        "accepted":
            accepted,

        "text_similarity":
            round(
                text_similarity,
                3,
            ),

        "matched_words":
            matched_all,

        "matched_distinctive":
            matched_distinctive,

        "distinctive_coverage":
            round(
                distinctive_coverage,
                3,
            ),

        "phrase_match":
            phrase_match,
    }


# ============================================================
# GOOGLE NEWS
# ============================================================

def google_news_search(query):
    if not query:
        return []

    # Recent news bias.
    search_query = (
        query
        + " when:7d"
    )

    rss_url = (
        "https://news.google.com/"
        "rss/search?q="
        + quote(
            search_query
        )
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
            "Google News error:",
            exc,
        )

        return []

    results = []

    for entry in (
        feed.entries[:15]
    ):
        source_name = ""

        try:
            if hasattr(
                entry,
                "source",
            ):
                source_name = (
                    entry.source.get(
                        "title",
                        "",
                    )
                )

        except Exception:
            pass

        results.append({
            "engine":
                "GOOGLE_NEWS",

            "title":
                clean_text(
                    entry.get(
                        "title",
                        "",
                    )
                ),

            "url":
                entry.get(
                    "link",
                    "",
                ),

            "source_name":
                source_name,

            "published":
                entry.get(
                    "published",
                    "",
                ),
        })

    return results


# ============================================================
# DUCKDUCKGO HTML SEARCH
#
# Gives direct publisher URLs, which solves the main V7.2
# Google News redirect problem.
# ============================================================

def decode_duckduckgo_url(
    href,
):
    if not href:
        return None

    if href.startswith("//"):
        href = (
            "https:"
            + href
        )

    try:
        parsed = urlparse(
            href
        )

        query = parse_qs(
            parsed.query
        )

        if query.get(
            "uddg"
        ):
            return unquote(
                query["uddg"][0]
            )

    except Exception:
        pass

    return href


def duckduckgo_search(
    query,
    max_results=12,
):
    if not query:
        return []

    url = (
        "https://html.duckduckgo.com/html/"
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
            url,
            params={
                "q": query,
            },
            headers=headers,
            timeout=20,
        )

        response.raise_for_status()

    except Exception as exc:
        print(
            "Web search error:",
            exc,
        )

        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = []

    anchors = soup.select(
        "a.result__a"
    )

    for anchor in (
        anchors[:max_results]
    ):
        title = clean_text(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        href = anchor.get(
            "href"
        )

        href = (
            decode_duckduckgo_url(
                href
            )
        )

        if (
            not href
            or not href.startswith(
                "http"
            )
        ):
            continue

        results.append({
            "engine":
                "WEB_SEARCH",

            "title":
                title,

            "url":
                href,

            "source_name":
                get_domain(
                    href
                ),

            "published":
                "",
        })

    return results


# ============================================================
# GOOGLE NEWS -> ORIGINAL URL RESOLVER
#
# Instead of trusting the Google URL, search the exact article
# title on the publisher's own domain.
# ============================================================

def resolve_google_news_candidate(
    candidate,
):
    source_name = (
        candidate.get(
            "source_name",
            ""
        )
    )

    title = (
        candidate.get(
            "title",
            ""
        )
    )

    domain = publisher_domain(
        source_name
    )

    if not domain:
        return None

    query_title = (
        normalize_for_matching(
            title
        )
    )

    words = (
        query_title.split()
    )

    # Enough of the headline to identify the article,
    # but not the whole long title.
    phrase = " ".join(
        words[:12]
    )

    search_query = (
        f"site:{domain} "
        f"{phrase}"
    )

    results = duckduckgo_search(
        search_query,
        max_results=6,
    )

    best_url = None
    best_score = 0.0

    for result in results:
        host = get_domain(
            result["url"]
        )

        if not domain_matches(
            host,
            domain,
        ):
            continue

        score = (
            SequenceMatcher(
                None,
                normalize_for_matching(
                    title
                ),
                normalize_for_matching(
                    result[
                        "title"
                    ]
                ),
            ).ratio()
        )

        if score > best_score:
            best_score = score
            best_url = (
                result["url"]
            )

    if best_score >= 0.45:
        return best_url

    return None


# ============================================================
# OFFICIAL FACEBOOK SIGNAL
# ============================================================

def get_official_signal(
    event,
):
    official_posts = [
        post
        for post
        in event["posts"]
        if (
            post.get(
                "source_tier"
            )
            == "OFFICIAL"
        )
    ]

    if not official_posts:
        return None

    best = official_posts[0]

    return {
        "source":
            best.get(
                "source"
            ),

        "facebook_url":
            best.get(
                "url"
            ),

        "text":
            best.get(
                "text"
            ),

        "time":
            best.get(
                "time"
            ),
    }


# ============================================================
# SEARCH OFFICIAL WEBSITES DIRECTLY
# ============================================================

def search_official_domains(
    event,
    official_signal,
):
    if not official_signal:
        return []

    source_name = (
        official_signal[
            "source"
        ]
    )

    config = SOURCES.get(
        source_name,
        {},
    )

    domains = config.get(
        "official_domains",
        [],
    )

    query = build_search_query(
        event
    )

    candidates = []

    for domain in domains:
        search_query = (
            f"site:{domain} "
            f"{query}"
        )

        results = (
            duckduckgo_search(
                search_query,
                max_results=8,
            )
        )

        for result in results:
            host = get_domain(
                result["url"]
            )

            if not domain_matches(
                host,
                domain,
            ):
                continue

            match = same_event_match(
                event,
                result["title"],
            )

            if not match[
                "accepted"
            ]:
                continue

            candidates.append({
                "title":
                    result["title"],

                "source_name":
                    domain,

                "original_article_url":
                    result["url"],

                "trust_level":
                    "OFFICIAL",

                "engine":
                    "OFFICIAL_WEB_SEARCH",

                "match":
                    match,
            })

    return candidates


# ============================================================
# SEARCH GENERAL WEB FOR DIRECT TRUSTED URL
# ============================================================

def search_direct_web(
    event,
):
    query = build_search_query(
        event
    )

    results = duckduckgo_search(
        query,
        max_results=15,
    )

    candidates = []

    for result in results:
        level = trusted_level_from_url(
            result["url"]
        )

        if level == "OTHER":
            continue

        match = same_event_match(
            event,
            result["title"],
        )

        if not match[
            "accepted"
        ]:
            continue

        candidates.append({
            "title":
                result["title"],

            "source_name":
                get_domain(
                    result["url"]
                ),

            "original_article_url":
                result["url"],

            "trust_level":
                level,

            "engine":
                "WEB_SEARCH",

            "match":
                match,
        })

    return candidates


# ============================================================
# SEARCH GOOGLE NEWS AND RESOLVE ORIGINAL URL
# ============================================================

def search_google_candidates(
    event,
):
    query = build_search_query(
        event
    )

    results = google_news_search(
        query
    )

    candidates = []

    for result in results:
        match = same_event_match(
            event,
            result["title"],
        )

        if not match[
            "accepted"
        ]:
            continue

        original_url = (
            resolve_google_news_candidate(
                result
            )
        )

        level = "OTHER"

        if original_url:
            level = (
                trusted_level_from_url(
                    original_url
                )
            )

        candidates.append({
            "title":
                result["title"],

            "source_name":
                result[
                    "source_name"
                ],

            "original_article_url":
                original_url,

            "google_news_url":
                result["url"],

            "published":
                result[
                    "published"
                ],

            "trust_level":
                level,

            "engine":
                "GOOGLE_NEWS",

            "match":
                match,
        })

    return candidates


# ============================================================
# EVIDENCE DEDUP
# ============================================================

def dedupe_evidence(
    candidates,
):
    result = []
    seen_urls = set()
    seen_titles = set()

    for item in candidates:
        url = item.get(
            "original_article_url"
        )

        title_key = (
            normalize_for_matching(
                item.get(
                    "title",
                    ""
                )
            )
        )

        if (
            url
            and url in seen_urls
        ):
            continue

        if (
            title_key
            and title_key
            in seen_titles
        ):
            continue

        if url:
            seen_urls.add(
                url
            )

        if title_key:
            seen_titles.add(
                title_key
            )

        result.append(
            item
        )

    return result


# ============================================================
# VERIFY EVENT
# ============================================================

def verify_event(event):
    quality = event_quality(
        event
    )

    event[
        "quality"
    ] = quality

    query = build_search_query(
        event
    )

    event[
        "search_query"
    ] = query

    official_signal = (
        get_official_signal(
            event
        )
    )

    event[
        "official_signal"
    ] = official_signal

    print()
    print(
        "VERIFY QUERY:",
        query,
    )

    if official_signal:
        print(
            "OFFICIAL FB SIGNAL:",
            official_signal[
                "source"
            ],
        )

    if not quality[
        "valid"
    ]:
        event[
            "verification"
        ] = "EVENT_QUALITY_LOW"

        event[
            "verification_evidence"
        ] = []

        event[
            "editorial_source"
        ] = None

        event[
            "send_to_editor"
        ] = False

        return event

    candidates = []

    # --------------------------------------------------------
    # 1. Official signal gets direct official-site search.
    # --------------------------------------------------------

    if official_signal:
        official_results = (
            search_official_domains(
                event,
                official_signal,
            )
        )

        candidates.extend(
            official_results
        )

    # --------------------------------------------------------
    # 2. Search direct web URLs.
    # --------------------------------------------------------

    direct_results = (
        search_direct_web(
            event
        )
    )

    candidates.extend(
        direct_results
    )

    # --------------------------------------------------------
    # 3. Google News discovery + publisher URL resolution.
    # --------------------------------------------------------

    google_results = (
        search_google_candidates(
            event
        )
    )

    candidates.extend(
        google_results
    )

    candidates = dedupe_evidence(
        candidates
    )

    trust_order = {
        "OFFICIAL": 4,
        "TRUSTED_NEWS": 3,
        "OTHER": 1,
    }

    candidates.sort(
        key=lambda item: (
            trust_order.get(
                item.get(
                    "trust_level",
                    "OTHER",
                ),
                0,
            ),
            item.get(
                "match",
                {}
            ).get(
                "distinctive_coverage",
                0,
            ),
            item.get(
                "match",
                {}
            ).get(
                "text_similarity",
                0,
            ),
        ),
        reverse=True,
    )

    # Only original URLs from trusted/official domains
    # can be used by bao-chi-tu-link.
    usable = [
        item
        for item
        in candidates
        if (
            item.get(
                "original_article_url"
            )
            and item.get(
                "trust_level"
            )
            in {
                "OFFICIAL",
                "TRUSTED_NEWS",
            }
        )
    ]

    official_articles = [
        item
        for item
        in usable
        if (
            item[
                "trust_level"
            ]
            == "OFFICIAL"
        )
    ]

    trusted_articles = [
        item
        for item
        in usable
        if (
            item[
                "trust_level"
            ]
            == "TRUSTED_NEWS"
        )
    ]

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    if official_articles:
        status = (
            "CO_NGUON_CHINH_THUC_GOC"
        )

    elif (
        official_signal
        and len(
            trusted_articles
        ) >= 1
    ):
        status = (
            "CO_TIN_HIEU_CHINH_THUC"
            "_VA_BAO_DOI_CHIEU"
        )

    elif len(
        trusted_articles
    ) >= 2:
        status = (
            "CO_NHIEU_BAO_UY_TIN"
            "_DOI_CHIEU"
        )

    elif len(
        trusted_articles
    ) == 1:
        status = (
            "CO_MOT_NGUON_BAO"
            "_DOI_CHIEU"
        )

    elif official_signal:
        status = (
            "CO_TIN_HIEU_CHINH_THUC"
            "_CHUA_CO_URL_GOC"
        )

    else:
        status = (
            "CHUA_XAC_MINH"
        )

    # --------------------------------------------------------
    # BEST SOURCE FOR EDITOR
    # --------------------------------------------------------

    editorial_source = None

    if usable:
        best = usable[0]

        editorial_source = {
            "source_name":
                best[
                    "source_name"
                ],

            "title":
                best[
                    "title"
                ],

            "url":
                best[
                    "original_article_url"
                ],

            "trust_level":
                best[
                    "trust_level"
                ],

            "engine":
                best[
                    "engine"
                ],

            "text_similarity":
                best[
                    "match"
                ][
                    "text_similarity"
                ],

            "distinctive_coverage":
                best[
                    "match"
                ][
                    "distinctive_coverage"
                ],

            "matched_distinctive":
                best[
                    "match"
                ][
                    "matched_distinctive"
                ],
        }

    event[
        "verification"
    ] = status

    event[
        "verification_evidence"
    ] = candidates[:8]

    event[
        "editorial_source"
    ] = editorial_source

    event[
        "send_to_editor"
    ] = (
        editorial_source
        is not None
    )

    return event


# ============================================================
# EDITORIAL DECISION
# ============================================================

def classify_event(event):
    verification = (
        event.get(
            "verification",
            "CHUA_XAC_MINH",
        )
    )

    source_count = len(
        event.get(
            "sources",
            []
        )
    )

    if verification in {
        "CO_NGUON_CHINH_THUC_GOC",
        "CO_TIN_HIEU_CHINH_THUC_VA_BAO_DOI_CHIEU",
        "CO_NHIEU_BAO_UY_TIN_DOI_CHIEU",
    }:
        decision = (
            "CHUYEN_BAN_BIEN_TAP"
        )

        reason = (
            "Đã tìm được URL bài gốc "
            "từ nguồn chính thức hoặc "
            "nhiều nguồn báo uy tín."
        )

    elif (
        verification
        == "CO_MOT_NGUON_BAO_DOI_CHIEU"
    ):
        decision = (
            "THEO_DOI"
        )

        reason = (
            "Đã tìm được một bài báo "
            "uy tín cùng sự kiện và URL gốc."
        )

    elif (
        verification
        == "CO_TIN_HIEU_CHINH_THUC_CHUA_CO_URL_GOC"
    ):
        decision = (
            "TIM_NGUON_GOC"
        )

        reason = (
            "Có bài từ Facebook chính thức "
            "nhưng chưa tìm được URL website "
            "gốc đủ chắc chắn."
        )

    elif (
        verification
        == "EVENT_QUALITY_LOW"
    ):
        decision = (
            "BO_QUA_TAM_THOI"
        )

        reason = (
            "Tiêu đề/tín hiệu quá chung chung "
            "để xác minh an toàn."
        )

    elif source_count >= 2:
        decision = (
            "CAN_XAC_MINH_GAP"
        )

        reason = (
            "Nhiều nguồn social cùng nói "
            "về sự kiện nhưng chưa tìm được "
            "nguồn xác minh đủ chắc."
        )

    else:
        decision = (
            "BO_QUA_TAM_THOI"
        )

        reason = (
            "Chưa có đủ bằng chứng "
            "đáng tin cậy."
        )

    event[
        "source_count"
    ] = source_count

    event[
        "decision"
    ] = decision

    event[
        "decision_reason"
    ] = reason

    return event


# ============================================================
# EDITOR QUEUE
# ============================================================

def build_editor_queue(events):
    queue = []

    for event in events:
        source = event.get(
            "editorial_source"
        )

        if not source:
            continue

        if not event.get(
            "send_to_editor",
            False,
        ):
            continue

        queue.append({
            "event_id":
                event[
                    "event_id"
                ],

            "page":
                PAGE_NAME,

            "editor_skill":
                "bao-chi-tu-link",

            "article_url":
                source[
                    "url"
                ],

            "article_source":
                source[
                    "source_name"
                ],

            "article_title":
                source[
                    "title"
                ],

            "article_trust":
                source[
                    "trust_level"
                ],

            "verification":
                event[
                    "verification"
                ],

            "decision":
                event[
                    "decision"
                ],

            "official_signal":
                event.get(
                    "official_signal"
                ),

            "social_sources": [
                post[
                    "source"
                ]
                for post
                in event[
                    "posts"
                ]
                if (
                    post.get(
                        "source_tier"
                    )
                    == "SOCIAL_RADAR"
                )
            ],

            "trend_context": [
                {
                    "source":
                        post[
                            "source"
                        ],

                    "tier":
                        post[
                            "source_tier"
                        ],

                    "url":
                        post.get(
                            "url"
                        ),

                    "time":
                        post.get(
                            "time"
                        ),
                }

                for post
                in event[
                    "posts"
                ]
            ],

            "editorial_rule": (
                "Đọc toàn bộ bài báo gốc trước "
                "khi biên tập. Không lấy dữ kiện "
                "từ caption social nếu dữ kiện đó "
                "không xuất hiện trong bài nguồn. "
                "Social chỉ dùng để xác định xu hướng."
            ),
        })

    return queue


# ============================================================
# SAVE JSON
# ============================================================

def save_json(
    path,
    data,
):
    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# MAIN
# ============================================================

def main():
    now = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    print(
        "=" * 78
    )
    print(
        "HONG CUNG TOI - "
        "RADAR V7.3"
    )
    print(
        "OFFICIAL + SOCIAL "
        "-> STRICT EVENT MATCH "
        "-> ORIGINAL URL "
        "-> EDITOR"
    )
    print(
        "TIME:",
        now,
    )
    print(
        "=" * 78
    )

    history = load_history()

    print(
        "HISTORY LOADED:",
        len(history),
    )

    all_posts = []
    source_results = {}

    # ========================================================
    # COLLECT
    # ========================================================

    with sync_playwright() as p:
        browser = (
            p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        )

        context = (
            browser.new_context(
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
        )

        page = (
            context.new_page()
        )

        for (
            source_name,
            config,
        ) in SOURCES.items():

            posts = (
                collect_source(
                    page,
                    source_name,
                    config,
                )
            )

            source_results[
                source_name
            ] = posts

            all_posts.extend(
                posts
            )

        browser.close()

    # ========================================================
    # DEDUP POSTS
    # ========================================================

    unique_posts = {}

    for post in all_posts:
        key = post.get(
            "post_id"
        )

        if not key:
            continue

        if key not in unique_posts:
            unique_posts[
                key
            ] = post

        else:
            old_text = (
                unique_posts[
                    key
                ].get(
                    "text",
                    "",
                )
            )

            new_text = (
                post.get(
                    "text",
                    "",
                )
            )

            if (
                len(new_text)
                > len(old_text)
            ):
                unique_posts[
                    key
                ] = post

    # ========================================================
    # HISTORY
    # ========================================================

    new_posts = []
    seen_posts = []
    new_post_ids = set()

    for (
        key,
        post,
    ) in unique_posts.items():

        if key in history:
            seen_posts.append(
                post
            )

            history[
                key
            ][
                "last_seen"
            ] = now

        else:
            new_posts.append(
                post
            )

            new_post_ids.add(
                key
            )

            history[
                key
            ] = {
                "source":
                    post.get(
                        "source"
                    ),

                "source_tier":
                    post.get(
                        "source_tier"
                    ),

                "url":
                    post.get(
                        "url"
                    ),

                "first_seen":
                    now,

                "last_seen":
                    now,
            }

    save_history(
        history
    )

    # ========================================================
    # CLUSTER EVENTS
    # ========================================================

    current_posts = list(
        unique_posts.values()
    )

    all_events = (
        cluster_events(
            current_posts
        )
    )

    # Only verify an event if at least one of its posts
    # is new. This avoids repeatedly searching the same story
    # every hourly run.
    if new_post_ids:
        events = [
            event
            for event
            in all_events
            if any(
                post.get(
                    "post_id"
                )
                in new_post_ids

                for post
                in event[
                    "posts"
                ]
            )
        ]

    else:
        events = []

    print()
    print(
        "EVENTS CLUSTERED:",
        len(all_events),
    )

    print(
        "NEW EVENTS TO VERIFY:",
        len(events),
    )

    # ========================================================
    # VERIFY
    # ========================================================

    verified_events = []

    for (
        index,
        event,
    ) in enumerate(
        events,
        start=1,
    ):
        print()
        print(
            f"VERIFY EVENT "
            f"{index}/"
            f"{len(events)}"
        )

        print(
            "TOPIC:",
            event[
                "title"
            ],
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

    # ========================================================
    # SORT
    # ========================================================

    decision_order = {
        "CHUYEN_BAN_BIEN_TAP": 6,
        "TIM_NGUON_GOC": 5,
        "CAN_XAC_MINH_GAP": 4,
        "THEO_DOI": 3,
        "BO_QUA_TAM_THOI": 1,
    }

    verified_events.sort(
        key=lambda event: (
            decision_order.get(
                event[
                    "decision"
                ],
                0,
            ),
            event[
                "source_count"
            ],
        ),
        reverse=True,
    )

    editor_queue = (
        build_editor_queue(
            verified_events
        )
    )

    # ========================================================
    # OUTPUT FILES
    # ========================================================

    result_output = {
        "generated_at":
            now,

        "version":
            VERSION,

        "source_stats": {
            source: {
                "tier":
                    SOURCES[
                        source
                    ][
                        "tier"
                    ],

                "posts":
                    len(posts),
            }

            for source, posts
            in source_results.items()
        },

        "collected":
            len(all_posts),

        "unique":
            len(
                unique_posts
            ),

        "new":
            len(
                new_posts
            ),

        "already_seen":
            len(
                seen_posts
            ),

        "new_posts":
            new_posts,
    }

    save_json(
        RESULT_FILE,
        result_output,
    )

    event_output = {
        "generated_at":
            now,

        "version":
            VERSION,

        "clustered_event_count":
            len(
                all_events
            ),

        "verified_new_event_count":
            len(
                verified_events
            ),

        "events":
            verified_events,
    }

    save_json(
        EVENT_FILE,
        event_output,
    )

    actionable = [
        event
        for event
        in verified_events
        if event[
            "decision"
        ] in {
            "CHUYEN_BAN_BIEN_TAP",
            "TIM_NGUON_GOC",
            "CAN_XAC_MINH_GAP",
            "THEO_DOI",
        }
    ]

    verified_output = {
        "generated_at":
            now,

        "version":
            VERSION,

        "actionable_count":
            len(
                actionable
            ),

        "events":
            actionable,
    }

    save_json(
        VERIFIED_FILE,
        verified_output,
    )

    queue_output = {
        "generated_at":
            now,

        "version":
            VERSION,

        "page":
            PAGE_NAME,

        "editor_skill":
            "bao-chi-tu-link",

        "queue_count":
            len(
                editor_queue
            ),

        "items":
            editor_queue,
    }

    save_json(
        EDITOR_QUEUE_FILE,
        queue_output,
    )

    # ========================================================
    # CONSOLE REPORT
    # ========================================================

    print()
    print(
        "=" * 78
    )
    print(
        "FINAL RADAR RESULT"
    )
    print(
        "=" * 78
    )

    print(
        "SOURCE STATS:"
    )

    for (
        source,
        data,
    ) in result_output[
        "source_stats"
    ].items():

        print(
            " -",
            source,
            "["
            + data[
                "tier"
            ]
            + "]",
            ":",
            data[
                "posts"
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
        "EVENTS CLUSTERED:",
        len(
            all_events
        ),
    )

    print(
        "NEW EVENTS VERIFIED:",
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

    print(
        "EDITOR QUEUE:",
        len(
            editor_queue
        ),
    )

    # ========================================================
    # VERIFICATION REPORT
    # ========================================================

    print()
    print(
        "=" * 78
    )
    print(
        "VERIFICATION RADAR V7.3"
    )
    print(
        "=" * 78
    )

    if not verified_events:
        print(
            "No new event requires "
            "verification this run."
        )

    for (
        index,
        event,
    ) in enumerate(
        verified_events,
        start=1,
    ):
        print()
        print(
            f"EVENT #{index}"
        )

        print(
            "TOPIC:",
            event[
                "title"
            ],
        )

        print(
            "SOURCES:",
            " + ".join(
                event[
                    "sources"
                ]
            ),
        )

        print(
            "TIERS:",
            " + ".join(
                event[
                    "source_tiers"
                ]
            ),
        )

        print(
            "QUALITY:",
            event.get(
                "quality"
            ),
        )

        official_signal = (
            event.get(
                "official_signal"
            )
        )

        if official_signal:
            print(
                "OFFICIAL SIGNAL:",
                official_signal[
                    "source"
                ],
            )

            print(
                "OFFICIAL FB URL:",
                official_signal[
                    "facebook_url"
                ],
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

        evidence = (
            event.get(
                "verification_evidence",
                [],
            )
        )

        print(
            "EVIDENCE:",
            len(
                evidence
            ),
        )

        for item in evidence:
            match = item.get(
                "match",
                {},
            )

            print(
                " -",
                "["
                + item.get(
                    "trust_level",
                    "OTHER",
                )
                + "]",
                item.get(
                    "source_name",
                    "",
                ),
                "| engine:",
                item.get(
                    "engine",
                    "",
                ),
                "| distinct:",
                match.get(
                    "matched_distinctive",
                    [],
                ),
                "| coverage:",
                match.get(
                    "distinctive_coverage",
                    0,
                ),
                "| phrase:",
                match.get(
                    "phrase_match",
                    False,
                ),
                "|",
                item.get(
                    "title",
                    "",
                )[:150],
            )

        editorial_source = (
            event.get(
                "editorial_source"
            )
        )

        print(
            "SEND TO EDITOR:",
            event.get(
                "send_to_editor",
                False,
            ),
        )

        if editorial_source:
            print(
                "EDITORIAL SOURCE:",
                editorial_source[
                    "source_name"
                ],
            )

            print(
                "ORIGINAL ARTICLE:",
                editorial_source[
                    "url"
                ],
            )

        else:
            print(
                "EDITORIAL SOURCE: NONE"
            )

    # ========================================================
    # EDITOR QUEUE REPORT
    # ========================================================

    print()
    print(
        "=" * 78
    )
    print(
        "EDITOR QUEUE -> bao-chi-tu-link"
    )
    print(
        "=" * 78
    )

    if not editor_queue:
        print(
            "No verified original article "
            "is ready for the editor."
        )

    for (
        index,
        item,
    ) in enumerate(
        editor_queue,
        start=1,
    ):
        print()
        print(
            f"QUEUE #{index}"
        )

        print(
            "PAGE:",
            item[
                "page"
            ],
        )

        print(
            "SOURCE:",
            item[
                "article_source"
            ],
        )

        print(
            "TITLE:",
            item[
                "article_title"
            ],
        )

        print(
            "ARTICLE URL:",
            item[
                "article_url"
            ],
        )

        print(
            "VERIFICATION:",
            item[
                "verification"
            ],
        )

        if item.get(
            "official_signal"
        ):
            print(
                "OFFICIAL SIGNAL:",
                item[
                    "official_signal"
                ][
                    "source"
                ],
            )

        if item.get(
            "social_sources"
        ):
            print(
                "SOCIAL SIGNAL:",
                " + ".join(
                    item[
                        "social_sources"
                    ]
                ),
            )

    print()
    print(
        "Saved:",
        RESULT_FILE,
    )

    print(
        "Events:",
        EVENT_FILE,
    )

    print(
        "Verified:",
        VERIFIED_FILE,
    )

    print(
        "Editor queue:",
        EDITOR_QUEUE_FILE,
    )

    print(
        "History:",
        HISTORY_FILE,
    )

    print(
        "HISTORY SIZE:",
        len(
            history
        ),
    )

    print(
        "=== RADAR V7.3 FINISHED ==="
    )


if __name__ == "__main__":
    main()
