from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, quote, unquote
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
# HONG CUNG TOI - RADAR V8
#
# DUAL RADAR:
#
# A. SOCIAL-FIRST
# Facebook social pages
# -> detect trend
# -> verify with trusted/official sources
#
# B. NEWS-FIRST
# Official websites + trusted newspapers
# -> discover fresh stories independently
# -> rule-based "worth editing" filter
#
# BOTH STREAMS
# -> EVENT CLUSTER
# -> SOURCE CHECK
# -> EDITOR QUEUE
# -> bao-chi-tu-link
#
# Social captions are NEVER factual confirmation.
# Original publisher URL is required before editor handoff.
# ============================================================


VERSION = "8.0"
PAGE_NAME = "Hóng Cùng Tôi"


# ============================================================
# FACEBOOK RADAR SOURCES
# ============================================================

FACEBOOK_SOURCES = {
    "Thông tin Chính phủ": {
        "page": "https://www.facebook.com/thongtinchinhphu",
        "mobile": "https://m.facebook.com/thongtinchinhphu",
        "tier": "OFFICIAL_FB",
    },

    "Bộ Công an": {
        "page": "https://www.facebook.com/mps.gov",
        "mobile": "https://m.facebook.com/mps.gov",
        "tier": "OFFICIAL_FB",
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
# NEWS-FIRST SOURCES
#
# These are searched independently of Facebook.
# ============================================================

NEWS_SOURCES = [
    {
        "name": "Cổng TTĐT Chính phủ",
        "domain": "chinhphu.vn",
        "tier": "OFFICIAL",
    },
    {
        "name": "Báo Chính phủ",
        "domain": "baochinhphu.vn",
        "tier": "OFFICIAL",
    },
    {
        "name": "Bộ Công an",
        "domain": "mps.gov.vn",
        "tier": "OFFICIAL",
    },

    {
        "name": "VnExpress",
        "domain": "vnexpress.net",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "Tuổi Trẻ",
        "domain": "tuoitre.vn",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "Thanh Niên",
        "domain": "thanhnien.vn",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "Dân Trí",
        "domain": "dantri.com.vn",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "VietnamNet",
        "domain": "vietnamnet.vn",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "VTV",
        "domain": "vtv.vn",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "VOV",
        "domain": "vov.vn",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "Lao Động",
        "domain": "laodong.vn",
        "tier": "TRUSTED_NEWS",
    },
    {
        "name": "Nhân Dân",
        "domain": "nhandan.vn",
        "tier": "TRUSTED_NEWS",
    },
]


OFFICIAL_DOMAINS = {
    item["domain"]
    for item in NEWS_SOURCES
    if item["tier"] == "OFFICIAL"
}

TRUSTED_DOMAINS = {
    item["domain"]
    for item in NEWS_SOURCES
    if item["tier"] == "TRUSTED_NEWS"
}


# ============================================================
# SETTINGS
# ============================================================

MAX_FB_POSTS_PER_SOURCE = 8
MAX_NEWS_PER_SOURCE = 2

FB_SCROLL_ROUNDS = 8
FB_SCROLL_WAIT_MS = 1800
FB_INITIAL_WAIT_MS = 5000

NEWS_LOOKBACK_DAYS = 2

MAX_HISTORY = 5000

SOCIAL_CLUSTER_THRESHOLD = 0.42

RESULT_FILE = "radar_results.json"
NEWS_FILE = "radar_news.json"
EVENT_FILE = "radar_events.json"
VERIFIED_FILE = "radar_verified.json"
EDITOR_QUEUE_FILE = "radar_editor_queue.json"
HISTORY_FILE = "radar_history.json"


# ============================================================
# LANGUAGE / FILTER RULES
# ============================================================

STOPWORDS = {
    "va", "la", "cua", "co", "cho", "voi", "mot",
    "nhung", "cac", "duoc", "dang", "da", "se",
    "khi", "thi", "ma", "tai", "trong", "sau",
    "truoc", "nay", "do", "ve", "theo", "tu",
    "den", "tren", "duoi", "lai", "ra", "vao",
    "van", "cung", "rat", "khong", "nguoi",
    "anh", "video", "clip", "facebook", "xem",
    "them", "noi", "cho", "mot",
}


# Words that by themselves should not establish "same event".
GENERIC_WORDS = {
    "nguoi", "con", "ong", "ba", "anh", "chi",
    "trung", "tam", "muc", "tieu", "phat", "trien",
    "thong", "tin", "moi", "hom", "nay", "sang",
    "toi", "tuoi", "roi", "vui", "buon", "khoc",
    "cuoi", "chuyen", "cau", "noi", "chia", "se",
    "su", "viec", "trang", "mang", "dan", "bat",
    "ngo", "gay", "chu", "dang", "thay", "nhieu",
}


# Generic institutional stories that normally should not enter
# the "hot story" queue unless they contain a concrete event.
ADMIN_PHRASES = [
    "hoi nghi",
    "hoi thao",
    "trien khai nhiem vu",
    "tong ket",
    "so ket",
    "giao ban",
    "quan triet",
    "phat huy tinh than",
    "day manh cong tac",
    "tang cuong cong tac",
    "thuc day phat trien",
    "phat trien ben vung",
    "ke hoach cong tac",
    "chuong trinh cong tac",
]


# Concrete event indicators.
EVENT_KEYWORDS = {
    "bat", "bat giu", "khoi to", "tam giu",
    "truy na", "dieu tra", "phat hien",
    "thu hoi", "cam", "dinh chi",
    "phat", "xu phat",

    "chay", "no", "sap", "tai nan",
    "mat tich", "tu vong", "cuu ho",
    "bao", "lu", "dong dat",

    "tang gia", "giam gia", "gia vang",
    "gia xang", "lai suat",

    "cong bo", "xac nhan", "thong bao",
    "quyet dinh", "ban hanh",

    "ly hon", "ket hon", "hen ho",
    "chia tay", "ra mat", "qua doi",

    "vo dich", "ky luc", "chien thang",
    "that bai", "bi loai",

    "lo du lieu", "su co", "loi",
    "trieu hoi", "ngung dich vu",
}


SOCIAL_FLUFF = {
    "ae", "anh em", "cac bac", "cac chu",
    "moi nguoi", "thay sao", "thay the nao",
    "di nha", "nha", "kkk", "haha", "hehe",
}


# ============================================================
# BASIC TEXT HELPERS
# ============================================================

def strip_accents(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFD", text)

    text = "".join(
        c for c in text
        if unicodedata.category(c) != "Mn"
    )

    return (
        text
        .replace("đ", "d")
        .replace("Đ", "D")
    )


def normalize_text(text):
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

    return "\n".join(output)[:7000]


def ordered_unique(items):
    result = []

    for item in items:
        if item not in result:
            result.append(item)

    return result


def significant_words(text):
    words = []

    for word in normalize_text(text).split():
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


def extract_numbers(text):
    return ordered_unique(
        re.findall(
            r"\b\d+(?:[.,]\d+)?\b",
            text or "",
        )
    )


def extract_proper_phrases(text):
    if not text:
        return []

    # Simple Vietnamese proper-name heuristic:
    # 2-4 consecutive capitalized words.
    matches = re.findall(
        r"\b(?:[A-ZÀ-ỸĐ][a-zà-ỹđ]+"
        r"(?:\s+[A-ZÀ-ỸĐ][a-zà-ỹđ]+){1,3})\b",
        text,
    )

    result = []

    for match in matches:
        normalized = normalize_text(
            match
        )

        if len(
            normalized.split()
        ) < 2:
            continue

        if normalized not in result:
            result.append(
                normalized
            )

    return result[:8]


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


def domain_matches(host, domain):
    return (
        host == domain
        or host.endswith(
            "." + domain
        )
    )


def trust_from_url(url):
    host = get_domain(url)

    for domain in OFFICIAL_DOMAINS:
        if domain_matches(
            host,
            domain,
        ):
            return "OFFICIAL"

    for domain in TRUSTED_DOMAINS:
        if domain_matches(
            host,
            domain,
        ):
            return "TRUSTED_NEWS"

    return "OTHER"


def source_config_from_domain(domain):
    for source in NEWS_SOURCES:
        if domain_matches(
            domain,
            source["domain"],
        ):
            return source

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

        if isinstance(data, dict):
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


def signal_history_key(
    signal_type,
    value,
):
    digest = hashlib.sha1(
        value.encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        f"{signal_type}:"
        f"{digest}"
    )


# ============================================================
# FACEBOOK URL HELPERS
# ============================================================

FB_POST_MARKERS = (
    "/posts/",
    "/videos/",
    "/reel/",
    "/reels/",
    "/watch/",
    "/permalink/",
    "/photo/",
    "story.php",
    "photo.php",
    "permalink.php",
)


def normalize_fb_url(url):
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
            query = parse_qs(
                parsed.query
            )

            if query.get("u"):
                url = query[
                    "u"
                ][0]

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


def is_fb_post_url(url):
    if not url:
        return False

    low = url.lower()

    if "facebook.com" not in low:
        return False

    return any(
        marker in low
        for marker in FB_POST_MARKERS
    )


def fb_post_id(url):
    if not url:
        return None

    patterns = [
        r"/posts/([^/?#]+)",
        r"/videos/([^/?#]+)",
        r"/reel(?:s)?/([^/?#]+)",
        r"/watch/([^/?#]+)",
        r"/permalink/([^/?#]+)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            url,
            re.I,
        )

        if match:
            return match.group(1)

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
            return match.group(0)

    return None


# ============================================================
# FACEBOOK EXTRACTION
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
            article = articles.nth(
                index
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

            links = article.locator(
                "a"
            )

            link_count = links.count()

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

                    if is_fb_post_url(
                        href
                    ):
                        post_url = href
                        break

                except Exception:
                    continue

            if not post_url:
                continue

            post_id = fb_post_id(
                post_url
            )

            if not post_id:
                continue

            found[
                post_id
            ] = {
                "post_id":
                    post_id,

                "url":
                    post_url,

                "text":
                    text,

                "time":
                    get_time_text(
                        raw_text
                    ),

                "extractor":
                    "role_article",
            }

        except Exception:
            continue

    return found


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
        min(
            count,
            700,
        )
    ):
        try:
            anchor = links.nth(
                index
            )

            href = (
                anchor.get_attribute(
                    "href"
                )
            )

            href = normalize_fb_url(
                href
            )

            if not is_fb_post_url(
                href
            ):
                continue

            post_id = fb_post_id(
                href
            )

            if not post_id:
                continue

            candidate_text = ""

            for level in (
                2,
                3,
                4,
                5,
                6,
            ):
                try:
                    node = anchor.locator(
                        "/.." * level
                    )

                    text = clean_text(
                        node.inner_text(
                            timeout=900
                        )
                    )

                    if (
                        20
                        <= len(text)
                        <= 7000
                    ):
                        if (
                            len(text)
                            > len(
                                candidate_text
                            )
                        ):
                            candidate_text = text

                except Exception:
                    continue

            if len(
                candidate_text
            ) < 12:
                continue

            found[
                post_id
            ] = {
                "post_id":
                    post_id,

                "url":
                    href,

                "text":
                    candidate_text,

                "time":
                    get_time_text(
                        candidate_text
                    ),

                "extractor":
                    "link_fallback",
            }

        except Exception:
            continue

    return found


def extract_fb_posts(page):
    found = {}

    for batch in (
        extract_role_articles(
            page
        ),
        extract_fallback_links(
            page
        ),
    ):
        for key, post in (
            batch.items()
        ):
            if key not in found:
                found[key] = post
                continue

            if (
                len(
                    post.get(
                        "text",
                        "",
                    )
                )
                >
                len(
                    found[key].get(
                        "text",
                        "",
                    )
                )
            ):
                found[key] = post

    return found


def discover_fb_entry(
    page,
    url,
    label,
):
    discovered = {}

    print()
    print(
        "ENTRY:",
        label,
    )

    print(
        "URL:",
        url,
    )

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(
            FB_INITIAL_WAIT_MS
        )

        for selector in (
            '[aria-label="Close"]',
            '[aria-label="Đóng"]',
            'div[role="button"]:has-text("Not Now")',
            'div[role="button"]:has-text("Lúc khác")',
        ):
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=500):
                    button.click(timeout=1000)
                    page.wait_for_timeout(500)
            except Exception:
                pass

        print(
            "HTTP:",
            response.status
            if response
            else None,
        )

        # Diagnostic telemetry: distinguish a real public feed from a
        # login/challenge/limited shell returned to headless GitHub Actions.
        try:
            title = page.title()
        except Exception:
            title = ""

        try:
            body_text = clean_text(
                page.locator("body").inner_text(timeout=3000)
            )
        except Exception:
            body_text = ""

        try:
            article_count = page.locator('div[role="article"]').count()
        except Exception:
            article_count = -1

        try:
            href_count = page.locator("a[href]").count()
        except Exception:
            href_count = -1

        low_body = normalize_text(body_text)
        wall_terms = (
            "dang nhap",
            "log in",
            "login",
            "create new account",
            "tao tai khoan",
            "security check",
            "checkpoint",
            "confirm your identity",
        )
        wall_hits = [
            term for term in wall_terms
            if term in low_body
        ]

        print("  PAGE TITLE:", title[:180])
        print("  ROLE ARTICLES:", article_count)
        print("  HREF COUNT:", href_count)
        print("  WALL HITS:", ", ".join(wall_hits) if wall_hits else "none")
        print("  BODY SAMPLE:", repr(body_text[:500]))

        for round_no in range(
            FB_SCROLL_ROUNDS + 1
        ):
            batch = extract_fb_posts(
                page
            )

            for key, post in (
                batch.items()
            ):
                if key not in discovered:
                    discovered[
                        key
                    ] = post

                elif (
                    len(
                        post.get(
                            "text",
                            "",
                        )
                    )
                    >
                    len(
                        discovered[
                            key
                        ].get(
                            "text",
                            "",
                        )
                    )
                ):
                    discovered[
                        key
                    ] = post

            print(
                f"  round "
                f"{round_no + 1}: "
                f"{len(discovered)} posts"
            )

            if (
                len(discovered)
                >= MAX_FB_POSTS_PER_SOURCE
            ):
                break

            try:
                page.evaluate(
                    "window.scrollBy(0, Math.max(window.innerHeight * 2.5, 3200))"
                )
            except Exception:
                page.mouse.wheel(
                    0,
                    5000,
                )

            page.wait_for_timeout(
                FB_SCROLL_WAIT_MS
            )

    except Exception as exc:
        print(
            "FB ERROR:",
            exc,
        )

    return discovered


def collect_fb_source(
    page,
    source_name,
    config,
):
    print()
    print(
        "=" * 70
    )

    print(
        "FACEBOOK:",
        source_name,
        "[",
        config["tier"],
        "]",
    )

    combined = {}

    for label, url in (
        (
            "desktop",
            config["page"],
        ),
        (
            "mobile",
            config["mobile"],
        ),
    ):
        batch = discover_fb_entry(
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

            elif (
                len(
                    post.get(
                        "text",
                        "",
                    )
                )
                >
                len(
                    combined[
                        key
                    ].get(
                        "text",
                        "",
                    )
                )
            ):
                combined[
                    key
                ] = post

    posts = list(
        combined.values()
    )[
        :MAX_FB_POSTS_PER_SOURCE
    ]

    for post in posts:
        post[
            "source"
        ] = source_name

        post[
            "source_tier"
        ] = config[
            "tier"
        ]

        post[
            "signal_type"
        ] = "FACEBOOK"

    print(
        "FOUND:",
        len(posts),
    )

    return posts


# ============================================================
# WEB SEARCH HELPERS
# ============================================================

def decode_ddg_url(href):
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
                query[
                    "uddg"
                ][0]
            )

    except Exception:
        pass

    return href


def duckduckgo_search(
    query,
    max_results=8,
):
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
            "https://html.duckduckgo.com/html/",
            params={
                "q": query,
            },
            headers=headers,
            timeout=20,
        )

        response.raise_for_status()

    except Exception as exc:
        print(
            "DDG error:",
            exc,
        )

        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = []

    for anchor in soup.select(
        "a.result__a"
    )[
        :max_results
    ]:
        href = decode_ddg_url(
            anchor.get(
                "href"
            )
        )

        title = clean_text(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        if not href:
            continue

        if not href.startswith(
            "http"
        ):
            continue

        results.append({
            "title":
                title,

            "url":
                href,
        })

    return results


def google_news_search(
    query,
    limit=10,
):
    rss_url = (
        "https://news.google.com/"
        "rss/search?q="
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
            "Google News error:",
            exc,
        )

        return []

    output = []

    for entry in feed.entries[
        :limit
    ]:
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

        output.append({
            "title":
                clean_text(
                    entry.get(
                        "title",
                        "",
                    )
                ),

            "google_url":
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

    return output


# ============================================================
# SOCIAL DISCOVERY FALLBACK
# ============================================================

SOCIAL_SEARCH_ALIASES = {
    "BeatVN": ["Beatvn", "beatvn.network"],
    "Theanh28": ["Theanh28", "Theanh28 Entertainment"],
    "Top Comments": ["Top Comments", "topcomments.vn"],
    "Bí Mật Showbiz": ["Bí Mật Showbiz", "bmsb.vnn"],
}


def collect_social_search_fallback(source_name, config, existing_posts):
    """
    Discover indexed Facebook post URLs when the direct public page is
    login-walled. Search results are discovery signals only; downstream
    verification still requires an official/trusted news source.
    """
    if config.get("tier") != "SOCIAL_RADAR":
        return []

    needed = max(0, MAX_FB_POSTS_PER_SOURCE - len(existing_posts))
    if needed <= 0:
        return []

    aliases = SOCIAL_SEARCH_ALIASES.get(source_name, [source_name])
    queries = []
    for alias in aliases:
        queries.extend([
            f'site:facebook.com "{alias}" posts',
            f'site:facebook.com "{alias}" reel',
        ])

    found = {}
    for query in ordered_unique(queries):
        print("  FALLBACK QUERY:", query)
        for result in duckduckgo_search(query, max_results=12):
            url = normalize_fb_url(result.get("url"))
            if not is_fb_post_url(url):
                continue

            title = clean_text(result.get("title", ""))
            title_norm = normalize_text(title)
            alias_match = any(
                normalize_text(alias) in title_norm
                for alias in aliases
            )
            url_norm = normalize_text(url)
            handle_match = any(
                normalize_text(alias).replace(" ", "") in url_norm.replace(" ", "")
                for alias in aliases
            )
            if not (alias_match or handle_match):
                continue

            post_id = fb_post_id(url)
            if not post_id:
                continue

            found[post_id] = {
                "post_id": post_id,
                "url": url,
                "text": title or f"{source_name} social post",
                "time": None,
                "extractor": "search_fallback",
                "source": source_name,
                "source_tier": config["tier"],
                "signal_type": "FACEBOOK",
            }

            if len(found) >= needed:
                break

        if len(found) >= needed:
            break

    print("  FALLBACK FOUND:", len(found))
    return list(found.values())[:needed]


# ============================================================
# ORIGINAL ARTICLE RESOLVER
# ============================================================

def direct_redirect_resolve(url):
    if not url:
        return None

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent":
                    "Mozilla/5.0",
            },
            timeout=15,
            allow_redirects=True,
        )

        final_url = (
            response.url
        )

        host = get_domain(
            final_url
        )

        if not host:
            return None

        if (
            "google.com"
            in host
            or "googleusercontent"
            in host
        ):
            return None

        return final_url

    except Exception:
        return None


def resolve_by_exact_title(
    title,
    domain,
):
    if not title or not domain:
        return None

    normalized = normalize_text(
        title
    )

    words = (
        normalized.split()
    )

    phrase = " ".join(
        words[:14]
    )

    query = (
        f"site:{domain} "
        f"{phrase}"
    )

    results = duckduckgo_search(
        query,
        max_results=6,
    )

    best_url = None
    best_similarity = 0.0

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
                normalize_text(
                    title
                ),
                normalize_text(
                    result["title"]
                ),
            ).ratio()
        )

        if (
            score
            > best_similarity
        ):
            best_similarity = score
            best_url = (
                result["url"]
            )

    if (
        best_url
        and best_similarity >= 0.45
    ):
        return best_url

    return None


# ============================================================
# NEWS-FIRST COLLECTOR
# ============================================================

def collect_news_first():
    all_articles = []
    stats = {}

    print()
    print(
        "=" * 70
    )
    print(
        "NEWS-FIRST RADAR"
    )
    print(
        "=" * 70
    )

    for source in NEWS_SOURCES:
        source_name = (
            source["name"]
        )

        domain = (
            source["domain"]
        )

        tier = source["tier"]

        query = (
            f"site:{domain} "
            f"when:{NEWS_LOOKBACK_DAYS}d"
        )

        print()
        print(
            "NEWS SOURCE:",
            source_name,
        )

        results = google_news_search(
            query,
            limit=(
                MAX_NEWS_PER_SOURCE
                * 3
            ),
        )

        source_articles = []

        for result in results:
            if (
                len(source_articles)
                >= MAX_NEWS_PER_SOURCE
            ):
                break

            title = (
                result["title"]
            )

            if not title:
                continue

            original_url = (
                direct_redirect_resolve(
                    result[
                        "google_url"
                    ]
                )
            )

            if (
                original_url
                and not domain_matches(
                    get_domain(
                        original_url
                    ),
                    domain,
                )
            ):
                original_url = None

            if not original_url:
                original_url = (
                    resolve_by_exact_title(
                        title,
                        domain,
                    )
                )

            article = {
                "signal_type":
                    "NEWS",

                "source":
                    source_name,

                "source_domain":
                    domain,

                "source_tier":
                    tier,

                "title":
                    title,

                "published":
                    result[
                        "published"
                    ],

                "google_url":
                    result[
                        "google_url"
                    ],

                "url":
                    original_url,
            }

            source_articles.append(
                article
            )

        stats[
            source_name
        ] = len(
            source_articles
        )

        all_articles.extend(
            source_articles
        )

        print(
            "FOUND:",
            len(
                source_articles
            ),
        )

    return (
        dedupe_news_articles(
            all_articles
        ),
        stats,
    )


def dedupe_news_articles(
    articles,
):
    output = []

    seen_urls = set()
    seen_titles = set()

    for article in articles:
        url = article.get(
            "url"
        )

        title_key = (
            normalize_text(
                article.get(
                    "title",
                    "",
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

        output.append(
            article
        )

    return output


# ============================================================
# EVENT SIGNATURE
# ============================================================

def build_signature(text):
    return {
        "distinctive":
            distinctive_words(
                text
            )[:20],

        "numbers":
            extract_numbers(
                text
            )[:10],

        "proper_phrases":
            extract_proper_phrases(
                text
            )[:8],
    }


def line_information_score(line):
    distinct = (
        distinctive_words(
            line
        )
    )

    sig = (
        significant_words(
            line
        )
    )

    if len(sig) < 3:
        return -100

    score = (
        len(distinct)
        * 3
        + len(sig)
    )

    if re.search(
        r"\d",
        line,
    ):
        score += 4

    score += min(
        len(line),
        220,
    ) / 30

    return score


def choose_social_event_title(
    text,
):
    lines = [
        line.strip()
        for line in (
            text or ""
        ).splitlines()
        if line.strip()
    ]

    blocked = {
        normalize_text(
            source
        )
        for source
        in FACEBOOK_SOURCES
    }

    candidates = []

    for line in lines:
        norm = normalize_text(
            line
        )

        if norm in blocked:
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
        if lines:
            return lines[0][
                :240
            ]

        return (
            "Chưa xác định"
        )

    candidates.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )

    return (
        candidates[0][1][
            :240
        ]
    )


# ============================================================
# SAME-EVENT MATCHING
# ============================================================

def strict_event_match(
    text_a,
    text_b,
):
    distinct_a = (
        distinctive_words(
            text_a
        )
    )

    distinct_b = set(
        distinctive_words(
            text_b
        )
    )

    matched = [
        word
        for word in distinct_a
        if word in distinct_b
    ]

    proper_a = (
        extract_proper_phrases(
            text_a
        )
    )

    normalized_b = (
        normalize_text(
            text_b
        )
    )

    proper_match = any(
        phrase
        in normalized_b
        for phrase
        in proper_a
    )

    numbers_a = set(
        extract_numbers(
            text_a
        )
    )

    numbers_b = set(
        extract_numbers(
            text_b
        )
    )

    number_match = bool(
        numbers_a
        & numbers_b
    )

    sequence = (
        SequenceMatcher(
            None,
            normalize_text(
                text_a
            )[:500],
            normalize_text(
                text_b
            )[:500],
        ).ratio()
    )

    distinct_total = len(
        ordered_unique(
            distinct_a
        )
    )

    coverage = (
        len(
            set(matched)
        )
        / distinct_total
        if distinct_total
        else 0
    )

    accepted = False

    # Named person/place + another clue.
    if (
        proper_match
        and (
            len(
                set(matched)
            ) >= 1
            or number_match
        )
    ):
        accepted = True

    # Same number + meaningful keywords.
    elif (
        number_match
        and len(
            set(matched)
        ) >= 2
    ):
        accepted = True

    # Strong distinctive overlap.
    elif (
        len(
            set(matched)
        ) >= 3
        and coverage >= 0.35
        and sequence >= 0.16
    ):
        accepted = True

    return {
        "accepted":
            accepted,

        "matched_distinctive":
            ordered_unique(
                matched
            ),

        "coverage":
            round(
                coverage,
                3,
            ),

        "proper_match":
            proper_match,

        "number_match":
            number_match,

        "sequence":
            round(
                sequence,
                3,
            ),
    }


# ============================================================
# SOCIAL EVENT CLUSTERING
# ============================================================

def social_similarity(
    text_a,
    text_b,
):
    words_a = set(
        distinctive_words(
            text_a
        )
    )

    words_b = set(
        distinctive_words(
            text_b
        )
    )

    if not words_a or not words_b:
        return 0

    jaccard = (
        len(
            words_a
            & words_b
        )
        /
        len(
            words_a
            | words_b
        )
    )

    sequence = (
        SequenceMatcher(
            None,
            normalize_text(
                text_a
            )[:1000],
            normalize_text(
                text_b
            )[:1000],
        ).ratio()
    )

    return (
        jaccard * 0.7
        + sequence * 0.3
    )


def cluster_social_posts(
    posts,
):
    events = []

    for post in posts:
        best_event = None
        best_score = 0

        for event in events:
            for existing in (
                event[
                    "social_posts"
                ]
            ):
                score = (
                    social_similarity(
                        post[
                            "text"
                        ],
                        existing[
                            "text"
                        ],
                    )
                )

                if (
                    score
                    > best_score
                ):
                    best_score = score
                    best_event = event

        if (
            best_event
            and best_score
            >= SOCIAL_CLUSTER_THRESHOLD
        ):
            best_event[
                "social_posts"
            ].append(
                post
            )

            if (
                post["source"]
                not in best_event[
                    "social_sources"
                ]
            ):
                best_event[
                    "social_sources"
                ].append(
                    post[
                        "source"
                    ]
                )

        else:
            event_id = (
                "social_"
                + hashlib.sha1(
                    (
                        post[
                            "source"
                        ]
                        + post[
                            "url"
                        ]
                    ).encode(
                        "utf-8"
                    )
                ).hexdigest()[
                    :12
                ]
            )

            title = (
                choose_social_event_title(
                    post[
                        "text"
                    ]
                )
            )

            events.append({
                "event_id":
                    event_id,

                "origin":
                    [
                        "SOCIAL_FIRST"
                    ],

                "title":
                    title,

                "context":
                    post[
                        "text"
                    ],

                "social_posts":
                    [
                        post
                    ],

                "social_sources":
                    [
                        post[
                            "source"
                        ]
                    ],

                "articles":
                    [],
            })

    return events


# ============================================================
# NEWS EVENT CLUSTERING
# ============================================================

def news_cluster_match(text_a, text_b):
    """
    Stricter than strict_event_match because unrelated newsroom headlines
    often share generic policy/sports words. False merges inflate source
    counts and corrupt downstream editorial scoring.
    """
    match = strict_event_match(text_a, text_b)
    matched_count = len(set(match.get("matched_distinctive") or []))
    coverage = match.get("coverage", 0)
    sequence = match.get("sequence", 0)

    accepted = False

    if (
        match.get("proper_match")
        and matched_count >= 2
        and sequence >= 0.18
    ):
        accepted = True
    elif (
        match.get("number_match")
        and matched_count >= 3
        and sequence >= 0.20
    ):
        accepted = True
    elif (
        matched_count >= 4
        and coverage >= 0.45
        and sequence >= 0.22
    ):
        accepted = True

    return {
        **match,
        "accepted": accepted,
    }


def cluster_news_articles(
    articles,
):
    events = []

    for article in articles:
        attached = False

        for event in events:
            match = (
                news_cluster_match(
                    article[
                        "title"
                    ],
                    event[
                        "title"
                    ],
                )
            )

            if match[
                "accepted"
            ]:
                event[
                    "articles"
                ].append(
                    article
                )

                if (
                    article[
                        "source"
                    ]
                    not in event[
                        "news_sources"
                    ]
                ):
                    event[
                        "news_sources"
                    ].append(
                        article[
                            "source"
                        ]
                    )

                attached = True
                break

        if attached:
            continue

        event_id = (
            "news_"
            + hashlib.sha1(
                (
                    article[
                        "source"
                    ]
                    + article[
                        "title"
                    ]
                ).encode(
                    "utf-8"
                )
            ).hexdigest()[
                :12
            ]
        )

        events.append({
            "event_id":
                event_id,

            "origin":
                [
                    "NEWS_FIRST"
                ],

            "title":
                article[
                    "title"
                ],

            "context":
                article[
                    "title"
                ],

            "social_posts":
                [],

            "social_sources":
                [],

            "articles":
                [
                    article
                ],

            "news_sources":
                [
                    article[
                        "source"
                    ]
                ],
        })

    return events


# ============================================================
# MERGE SOCIAL + NEWS STREAMS
# ============================================================

def merge_dual_streams(
    social_events,
    news_events,
):
    unified = list(
        news_events
    )

    for social_event in (
        social_events
    ):
        merged = False

        for event in unified:
            match = (
                strict_event_match(
                    social_event[
                        "context"
                    ],
                    event[
                        "title"
                    ],
                )
            )

            if not match[
                "accepted"
            ]:
                continue

            event[
                "origin"
            ] = ordered_unique(
                event[
                    "origin"
                ]
                + [
                    "SOCIAL_FIRST"
                ]
            )

            event[
                "social_posts"
            ].extend(
                social_event[
                    "social_posts"
                ]
            )

            event[
                "social_sources"
            ] = ordered_unique(
                event[
                    "social_sources"
                ]
                + social_event[
                    "social_sources"
                ]
            )

            merged = True
            break

        if not merged:
            social_event[
                "news_sources"
            ] = []

            unified.append(
                social_event
            )

    return unified


# ============================================================
# EVENT QUALITY / NEWSWORTHINESS RULES
# ============================================================

def contains_event_keyword(
    text,
):
    norm = normalize_text(
        text
    )

    for keyword in (
        EVENT_KEYWORDS
    ):
        if (
            normalize_text(
                keyword
            )
            in norm
        ):
            return True

    return False


def is_generic_admin_story(
    title,
):
    norm = normalize_text(
        title
    )

    generic = any(
        phrase in norm
        for phrase
        in ADMIN_PHRASES
    )

    if not generic:
        return False

    # Concrete event overrides administrative wording.
    if contains_event_keyword(
        title
    ):
        return False

    if extract_numbers(
        title
    ):
        return False

    return True


def event_specificity(event):
    # Evaluate both the clustered context and the concrete headline.
    # Previously a non-empty but generic context completely hid the title,
    # causing clearly specific news stories to be marked non-specific.
    text = " ".join(
        part
        for part in [
            event.get("title", ""),
            event.get("context", ""),
        ]
        if part
    )

    signature = (
        build_signature(
            text
        )
    )

    proper = len(
        signature[
            "proper_phrases"
        ]
    )

    numbers = len(
        signature[
            "numbers"
        ]
    )

    distinctive = len(
        signature[
            "distinctive"
        ]
    )

    concrete_action = (
        contains_event_keyword(
            text
        )
    )

    specific = (
        proper > 0
        or numbers > 0
        or concrete_action
        or distinctive >= 5
    )

    return {
        "specific":
            specific,

        "proper_phrases":
            signature[
                "proper_phrases"
            ],

        "numbers":
            signature[
                "numbers"
            ],

        "distinctive_count":
            distinctive,

        "concrete_action":
            concrete_action,
    }


def apply_hot_filter(event):
    articles = [
        item
        for item in event[
            "articles"
        ]
        if item.get("url") or item.get("google_url")
    ]

    unique_publishers = (
        ordered_unique(
            [
                item[
                    "source"
                ]
                for item
                in articles
            ]
        )
    )

    official_articles = [
        item
        for item in articles
        if (
            item[
                "source_tier"
            ]
            == "OFFICIAL"
        )
    ]

    trusted_articles = [
        item
        for item in articles
        if (
            item[
                "source_tier"
            ]
            == "TRUSTED_NEWS"
        )
    ]

    social_count = len(
        event[
            "social_sources"
        ]
    )

    specificity = (
        event_specificity(
            event
        )
    )

    generic_admin = (
        is_generic_admin_story(
            event[
                "title"
            ]
        )
    )

    decision = (
        "BO_QUA_TAM_THOI"
    )

    reason = (
        "Chưa đủ tín hiệu để chuyển bàn biên tập."
    )

    rule = None

    # --------------------------------------------------------
    # RULE 1
    # Official source + concrete event.
    # --------------------------------------------------------

    if (
        official_articles
        and specificity[
            "specific"
        ]
        and not generic_admin
    ):
        decision = (
            "CHUYEN_BAN_BIEN_TAP"
        )

        rule = (
            "OFFICIAL_CONCRETE_EVENT"
        )

        reason = (
            "Nguồn chính thức có một sự kiện "
            "cụ thể, không phải bài hành chính chung."
        )

    # --------------------------------------------------------
    # RULE 2
    # Multiple trusted publishers on same event.
    # --------------------------------------------------------

    elif (
        len(
            unique_publishers
        ) >= 2
        and specificity[
            "specific"
        ]
        and not generic_admin
    ):
        decision = (
            "CHUYEN_BAN_BIEN_TAP"
        )

        rule = (
            "MULTI_SOURCE_EVENT"
        )

        reason = (
            "Có từ hai nguồn báo/chính thống "
            "cùng đưa về một sự kiện cụ thể."
        )

    # --------------------------------------------------------
    # RULE 3
    # Social signal + trusted article confirmation.
    # --------------------------------------------------------

    elif (
        social_count >= 1
        and (
            official_articles
            or trusted_articles
        )
        and specificity[
            "specific"
        ]
    ):
        decision = (
            "CHUYEN_BAN_BIEN_TAP"
        )

        rule = (
            "SOCIAL_PLUS_TRUSTED_SOURCE"
        )

        reason = (
            "Có tín hiệu social và nguồn báo/"
            "chính thống cùng sự kiện."
        )

    # --------------------------------------------------------
    # RULE 4
    # One trusted article, but clearly event-based and concrete.
    # --------------------------------------------------------

    elif (
        len(
            trusted_articles
        ) >= 1
        and specificity[
            "specific"
        ]
        and specificity[
            "concrete_action"
        ]
        and not generic_admin
    ):
        decision = (
            "CHUYEN_BAN_BIEN_TAP"
        )

        rule = (
            "SINGLE_TRUSTED_CONCRETE_EVENT"
        )

        reason = (
            "Một nguồn báo uy tín nhưng tiêu đề "
            "mô tả sự kiện mới và cụ thể."
        )

    elif (
        articles
        and specificity[
            "specific"
        ]
        and not generic_admin
    ):
        decision = (
            "THEO_DOI"
        )

        rule = (
            "WATCH"
        )

        reason = (
            "Có nguồn đáng tin nhưng chưa đủ "
            "điều kiện chuyển thẳng bàn biên tập."
        )

    # Safety net: a fresh item from an official/trusted source should still
    # reach the second editorial layer even if the specificity heuristic is
    # uncertain. V8.2 will decide whether it is worth surfacing.
    elif (
        (official_articles or trusted_articles)
        and not generic_admin
    ):
        decision = "THEO_DOI"
        rule = "VERIFIED_SOURCE_WATCH"
        reason = (
            "Có nguồn chính thức/báo uy tín nhưng lớp nhận diện sự kiện "
            "chưa đủ chắc; chuyển sang V8.2 để đánh giá tiếp thay vì loại sớm."
        )

    elif generic_admin:
        decision = (
            "BO_QUA_TAM_THOI"
        )

        rule = (
            "GENERIC_ADMIN"
        )

        reason = (
            "Nội dung mang tính hành chính/"
            "hội nghị chung, chưa có sự kiện cụ thể."
        )

    event[
        "specificity"
    ] = specificity

    event[
        "hot_rule"
    ] = rule

    event[
        "decision"
    ] = decision

    event[
        "decision_reason"
    ] = reason

    return event


# ============================================================
# SOCIAL-FIRST VERIFICATION
# ============================================================

def social_event_query(event):
    context = (
        event.get(
            "context",
            ""
        )
    )

    words = ordered_unique(
        distinctive_words(
            context
        )
    )

    numbers = (
        extract_numbers(
            context
        )
    )

    query_parts = (
        words[:8]
        + numbers[:2]
    )

    if not query_parts:
        return (
            event[
                "title"
            ][:180]
        )

    return " ".join(
        query_parts
    )


def resolve_source_domain_from_name(
    source_name,
):
    norm = normalize_text(
        source_name
    )

    aliases = {
        "vnexpress":
            "vnexpress.net",

        "tuoi tre":
            "tuoitre.vn",

        "thanh nien":
            "thanhnien.vn",

        "dan tri":
            "dantri.com.vn",

        "vietnamnet":
            "vietnamnet.vn",

        "vtv":
            "vtv.vn",

        "vov":
            "vov.vn",

        "lao dong":
            "laodong.vn",

        "nhan dan":
            "nhandan.vn",

        "bao chinh phu":
            "baochinhphu.vn",

        "chinh phu":
            "chinhphu.vn",

        "bo cong an":
            "mps.gov.vn",
    }

    for key, domain in (
        aliases.items()
    ):
        if key in norm:
            return domain

    return None


def verify_social_event(
    event,
):
    if event[
        "articles"
    ]:
        return event

    query = (
        social_event_query(
            event
        )
    )

    event[
        "verification_query"
    ] = query

    # Weak/teaser-only social post:
    # do not waste search calls.
    specificity = (
        event_specificity(
            event
        )
    )

    if (
        not specificity[
            "specific"
        ]
    ):
        event[
            "verification_status"
        ] = (
            "SOCIAL_SIGNAL_TOO_VAGUE"
        )

        return event

    results = (
        google_news_search(
            query
            + " when:7d",
            limit=12,
        )
    )

    matched_articles = []

    for result in results:
        match = strict_event_match(
            event[
                "context"
            ],
            result[
                "title"
            ],
        )

        if not match[
            "accepted"
        ]:
            continue

        domain = (
            resolve_source_domain_from_name(
                result[
                    "source_name"
                ]
            )
        )

        if not domain:
            continue

        source_cfg = (
            source_config_from_domain(
                domain
            )
        )

        if not source_cfg:
            continue

        original_url = (
            direct_redirect_resolve(
                result[
                    "google_url"
                ]
            )
        )

        if (
            original_url
            and not domain_matches(
                get_domain(
                    original_url
                ),
                domain,
            )
        ):
            original_url = None

        if not original_url:
            original_url = (
                resolve_by_exact_title(
                    result[
                        "title"
                    ],
                    domain,
                )
            )

        if not original_url:
            continue

        matched_articles.append({
            "signal_type":
                "NEWS",

            "source":
                source_cfg[
                    "name"
                ],

            "source_domain":
                domain,

            "source_tier":
                source_cfg[
                    "tier"
                ],

            "title":
                result[
                    "title"
                ],

            "published":
                result[
                    "published"
                ],

            "url":
                original_url,

            "google_url":
                result[
                    "google_url"
                ],

            "verification_match":
                match,
        })

    event[
        "articles"
    ].extend(
        dedupe_news_articles(
            matched_articles
        )
    )

    event[
        "news_sources"
    ] = ordered_unique(
        event.get(
            "news_sources",
            []
        )
        + [
            item[
                "source"
            ]
            for item
            in event[
                "articles"
            ]
        ]
    )

    if event[
        "articles"
    ]:
        event[
            "verification_status"
        ] = (
            "SOURCE_MATCH_FOUND"
        )

    else:
        event[
            "verification_status"
        ] = (
            "NO_TRUSTED_MATCH"
        )

    return event


# ============================================================
# EVENT HISTORY / NEW SIGNAL CHECK
# ============================================================

def apply_history(
    facebook_posts,
    news_articles,
    history,
    now,
):
    new_fb = 0
    seen_fb = 0

    for post in facebook_posts:
        key = (
            "fb:"
            + post[
                "post_id"
            ]
        )

        is_new = (
            key not in history
        )

        post[
            "is_new"
        ] = is_new

        if is_new:
            new_fb += 1

            history[key] = {
                "type":
                    "facebook",

                "source":
                    post[
                        "source"
                    ],

                "url":
                    post[
                        "url"
                    ],

                "first_seen":
                    now,

                "last_seen":
                    now,
            }

        else:
            seen_fb += 1

            history[
                key
            ][
                "last_seen"
            ] = now

    new_news = 0
    seen_news = 0

    for article in news_articles:
        identity = (
            article.get(
                "url"
            )
            or (
                article[
                    "source"
                ]
                + "|"
                + normalize_text(
                    article[
                        "title"
                    ]
                )
            )
        )

        key = (
            signal_history_key(
                "news",
                identity,
            )
        )

        is_new = (
            key not in history
        )

        article[
            "is_new"
        ] = is_new

        if is_new:
            new_news += 1

            history[key] = {
                "type":
                    "news",

                "source":
                    article[
                        "source"
                    ],

                "url":
                    article.get(
                        "url"
                    ),

                "title":
                    article[
                        "title"
                    ],

                "first_seen":
                    now,

                "last_seen":
                    now,
            }

        else:
            seen_news += 1

            history[
                key
            ][
                "last_seen"
            ] = now

    return {
        "new_fb":
            new_fb,

        "seen_fb":
            seen_fb,

        "new_news":
            new_news,

        "seen_news":
            seen_news,
    }


def event_has_new_signal(
    event,
):
    if any(
        post.get(
            "is_new"
        )
        for post
        in event[
            "social_posts"
        ]
    ):
        return True

    if any(
        article.get(
            "is_new"
        )
        for article
        in event[
            "articles"
        ]
    ):
        return True

    return False


# ============================================================
# EDITOR QUEUE
# ============================================================

def choose_editor_source(
    event,
):
    usable = [
        article
        for article
        in event[
            "articles"
        ]
        if (
            article.get(
                "url"
            )
            and article[
                "source_tier"
            ]
            in {
                "OFFICIAL",
                "TRUSTED_NEWS",
            }
        )
    ]

    if not usable:
        return None

    # Prefer official original source if available.
    for article in usable:
        if (
            article[
                "source_tier"
            ]
            == "OFFICIAL"
        ):
            return article

    return usable[0]


def build_editor_queue(
    events,
):
    queue = []

    for event in events:
        if (
            event[
                "decision"
            ]
            != "CHUYEN_BAN_BIEN_TAP"
        ):
            continue

        source = (
            choose_editor_source(
                event
            )
        )

        if not source:
            continue

        queue.append({
            "event_id":
                event[
                    "event_id"
                ],

            "origin":
                event[
                    "origin"
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
                    "source"
                ],

            "article_title":
                source[
                    "title"
                ],

            "article_trust":
                source[
                    "source_tier"
                ],

            "hot_rule":
                event[
                    "hot_rule"
                ],

            "decision_reason":
                event[
                    "decision_reason"
                ],

            "social_sources":
                event[
                    "social_sources"
                ],

            "news_sources":
                ordered_unique(
                    [
                        article[
                            "source"
                        ]
                        for article
                        in event[
                            "articles"
                        ]
                    ]
                ),

            "editorial_rule": (
                "Đọc toàn bộ bài báo gốc trước khi biên tập. "
                "Không dùng caption social để thêm dữ kiện. "
                "Mọi dữ kiện trong caption, headline và bản tin "
                "phải truy được về bài nguồn đã đọc."
            ),
        })

    return queue


# ============================================================
# JSON
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
        "HONG CUNG TOI - RADAR V8"
    )

    print(
        "DUAL RADAR: "
        "SOCIAL-FIRST + NEWS-FIRST"
    )

    print(
        "TIME:",
        now,
    )

    print(
        "=" * 78
    )

    history = (
        load_history()
    )

    print(
        "HISTORY:",
        len(history),
    )

    # ========================================================
    # STREAM A - FACEBOOK
    # ========================================================

    facebook_posts = []
    fb_stats = {}

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

        storage_state_path = os.getenv(
            "FB_STORAGE_STATE_PATH",
            "",
        ).strip()

        context_kwargs = {
            "viewport": {
                "width": 1280,
                "height": 1000,
            },
            "locale": "vi-VN",
            "user_agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 "
                "Safari/537.36"
            ),
        }

        if storage_state_path and os.path.exists(storage_state_path):
            context_kwargs["storage_state"] = storage_state_path
            print("FACEBOOK SESSION: authenticated storage state loaded")
        else:
            print("FACEBOOK SESSION: anonymous")

        context = browser.new_context(
            **context_kwargs
        )

        page = (
            context.new_page()
        )

        for (
            source_name,
            config,
        ) in (
            FACEBOOK_SOURCES.items()
        ):
            posts = (
                collect_fb_source(
                    page,
                    source_name,
                    config,
                )
            )

            if (
                config.get("tier") == "SOCIAL_RADAR"
                and len(posts) < MAX_FB_POSTS_PER_SOURCE
            ):
                fallback_posts = collect_social_search_fallback(
                    source_name,
                    config,
                    posts,
                )

                existing_ids = {
                    post.get("post_id")
                    for post in posts
                }

                for fallback_post in fallback_posts:
                    if fallback_post.get("post_id") not in existing_ids:
                        posts.append(fallback_post)
                        existing_ids.add(fallback_post.get("post_id"))

            fb_stats[
                source_name
            ] = len(posts)

            facebook_posts.extend(
                posts
            )

        browser.close()

    # FB dedup
    fb_unique = {}

    for post in facebook_posts:
        post_id = post[
            "post_id"
        ]

        if (
            post_id
            not in fb_unique
        ):
            fb_unique[
                post_id
            ] = post

        elif (
            len(
                post[
                    "text"
                ]
            )
            >
            len(
                fb_unique[
                    post_id
                ][
                    "text"
                ]
            )
        ):
            fb_unique[
                post_id
            ] = post

    facebook_posts = list(
        fb_unique.values()
    )

    # ========================================================
    # STREAM B - NEWS FIRST
    # ========================================================

    (
        news_articles,
        news_stats,
    ) = collect_news_first()

    # ========================================================
    # HISTORY
    # ========================================================

    history_stats = (
        apply_history(
            facebook_posts,
            news_articles,
            history,
            now,
        )
    )

    save_history(
        history
    )

    # ========================================================
    # BUILD EVENTS
    # ========================================================

    social_events = (
        cluster_social_posts(
            facebook_posts
        )
    )

    news_events = (
        cluster_news_articles(
            news_articles
        )
    )

    events = (
        merge_dual_streams(
            social_events,
            news_events,
        )
    )

    # Only newly changed events need expensive verification in normal runs.
    # Manual diagnostic runs can rescan the current collected set without
    # clearing history by setting RADAR_RESCAN_ALL=1.
    rescan_all = os.getenv("RADAR_RESCAN_ALL", "").strip().lower() in {
        "1", "true", "yes", "on"
    }

    if rescan_all:
        active_events = list(events)
    else:
        active_events = [
            event
            for event in events
            if event_has_new_signal(
                event
            )
        ]

    print()
    print(
        "SOCIAL EVENTS:",
        len(
            social_events
        ),
    )

    print(
        "NEWS EVENTS:",
        len(
            news_events
        ),
    )

    print(
        "UNIFIED EVENTS:",
        len(events),
    )

    print(
        "ACTIVE NEW EVENTS:",
        len(
            active_events
        ),
    )

    print(
        "RESCAN ALL:",
        rescan_all,
    )

    # ========================================================
    # VERIFY SOCIAL-ONLY EVENTS
    # ========================================================

    processed_events = []

    for (
        index,
        event,
    ) in enumerate(
        active_events,
        start=1,
    ):
        print()
        print(
            f"PROCESS EVENT "
            f"{index}/"
            f"{len(active_events)}"
        )

        print(
            "TOPIC:",
            event[
                "title"
            ],
        )

        if (
            not event[
                "articles"
            ]
        ):
            event = (
                verify_social_event(
                    event
                )
            )

        else:
            event[
                "verification_status"
            ] = (
                "NEWS_SOURCE_ALREADY_PRESENT"
            )

        event = (
            apply_hot_filter(
                event
            )
        )

        processed_events.append(
            event
        )

    # ========================================================
    # EDITOR QUEUE
    # ========================================================

    editor_queue = (
        build_editor_queue(
            processed_events
        )
    )

    actionable = [
        event
        for event
        in processed_events
        if event[
            "decision"
        ] in {
            "CHUYEN_BAN_BIEN_TAP",
            "THEO_DOI",
        }
    ]

    # ========================================================
    # SAVE OUTPUT
    # ========================================================

    save_json(
        RESULT_FILE,
        {
            "generated_at":
                now,

            "version":
                VERSION,

            "facebook_stats":
                fb_stats,

            "history_stats":
                history_stats,

            "facebook_posts":
                facebook_posts,
        },
    )

    save_json(
        NEWS_FILE,
        {
            "generated_at":
                now,

            "version":
                VERSION,

            "source_stats":
                news_stats,

            "article_count":
                len(
                    news_articles
                ),

            "articles":
                news_articles,
        },
    )

    save_json(
        EVENT_FILE,
        {
            "generated_at":
                now,

            "version":
                VERSION,

            "social_event_count":
                len(
                    social_events
                ),

            "news_event_count":
                len(
                    news_events
                ),

            "unified_event_count":
                len(events),

            "active_event_count":
                len(
                    processed_events
                ),

            "events":
                processed_events,
        },
    )

    save_json(
        VERIFIED_FILE,
        {
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
        },
    )

    save_json(
        EDITOR_QUEUE_FILE,
        {
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
        },
    )

    # ========================================================
    # CONSOLE REPORT
    # ========================================================

    print()
    print(
        "=" * 78
    )

    print(
        "DUAL RADAR V8 RESULT"
    )

    print(
        "=" * 78
    )

    print()
    print(
        "FACEBOOK RADAR:"
    )

    for source, count in (
        fb_stats.items()
    ):
        print(
            " -",
            source,
            ":",
            count,
        )

    print()
    print(
        "NEWS-FIRST RADAR:"
    )

    for source, count in (
        news_stats.items()
    ):
        print(
            " -",
            source,
            ":",
            count,
        )

    print()
    print(
        "FB NEW:",
        history_stats[
            "new_fb"
        ],
    )

    print(
        "FB SEEN:",
        history_stats[
            "seen_fb"
        ],
    )

    print(
        "NEWS NEW:",
        history_stats[
            "new_news"
        ],
    )

    print(
        "NEWS SEEN:",
        history_stats[
            "seen_news"
        ],
    )

    print(
        "SOCIAL EVENTS:",
        len(
            social_events
        ),
    )

    print(
        "NEWS EVENTS:",
        len(
            news_events
        ),
    )

    print(
        "ACTIVE EVENTS:",
        len(
            processed_events
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
    # EVENT REPORT
    # ========================================================

    print()
    print(
        "=" * 78
    )

    print(
        "EVENT RADAR"
    )

    print(
        "=" * 78
    )

    for (
        index,
        event,
    ) in enumerate(
        processed_events,
        start=1,
    ):
        print()
        print(
            f"EVENT #{index}"
        )

        print(
            "ORIGIN:",
            " + ".join(
                event[
                    "origin"
                ]
            ),
        )

        print(
            "TOPIC:",
            event[
                "title"
            ],
        )

        print(
            "SOCIAL:",
            (
                " + ".join(
                    event[
                        "social_sources"
                    ]
                )
                or "NONE"
            ),
        )

        print(
            "NEWS:",
            (
                " + ".join(
                    ordered_unique(
                        [
                            article[
                                "source"
                            ]
                            for article
                            in event[
                                "articles"
                            ]
                        ]
                    )
                )
                or "NONE"
            ),
        )

        print(
            "VERIFICATION:",
            event.get(
                "verification_status",
                "N/A",
            ),
        )

        print(
            "SPECIFICITY:",
            json.dumps(event.get("specificity", {}), ensure_ascii=False),
        )

        print(
            "HOT RULE:",
            event.get(
                "hot_rule"
            ),
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
            "ARTICLES:",
            len(
                event[
                    "articles"
                ]
            ),
        )

        for article in (
            event[
                "articles"
            ][
                :5
            ]
        ):
            print(
                " -",
                "["
                + article[
                    "source_tier"
                ]
                + "]",
                article[
                    "source"
                ],
                "|",
                article[
                    "title"
                ][
                    :150
                ],
            )

            if article.get(
                "url"
            ):
                print(
                    "   URL:",
                    article[
                        "url"
                    ],
                )

    # ========================================================
    # EDITOR QUEUE
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
            "No story is ready "
            "for editor handoff."
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
            "ORIGIN:",
            " + ".join(
                item[
                    "origin"
                ]
            ),
        )

        print(
            "RULE:",
            item[
                "hot_rule"
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

        if item[
            "social_sources"
        ]:
            print(
                "SOCIAL SIGNAL:",
                " + ".join(
                    item[
                        "social_sources"
                    ]
                ),
            )

        print(
            "NEWS SOURCES:",
            " + ".join(
                item[
                    "news_sources"
                ]
            ),
        )

    print()
    print(
        "Saved:",
        RESULT_FILE,
    )

    print(
        "News:",
        NEWS_FILE,
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

    print()
    print(
        "=== RADAR V8 FINISHED ==="
    )


if __name__ == "__main__":
    main()
