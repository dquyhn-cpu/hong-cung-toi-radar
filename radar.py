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
# HONG CUNG TOI - RADAR V7.2
#
# OFFICIAL FACEBOOK SIGNALS
# + SOCIAL RADAR
# -> DEDUP
# -> EVENT CLUSTER
# -> STRICT NEWS VERIFICATION
# -> ORIGINAL ARTICLE
# -> EDITOR QUEUE
#
# IMPORTANT:
# SOCIAL_RADAR = trend signal only.
# OFFICIAL = official signal, but downstream editor still reads
# the original source before publication.
# ============================================================


PAGE_NAME = "Hóng Cùng Tôi"

SOURCES = {
    # --------------------------------------------------------
    # OFFICIAL SIGNALS
    # --------------------------------------------------------
    "Thông tin Chính phủ": {
        "page": "https://www.facebook.com/thongtinchinhphu",
        "mobile": "https://m.facebook.com/thongtinchinhphu",
        "tier": "OFFICIAL",
    },

    "Bộ Công an": {
        "page": "https://www.facebook.com/mps.gov",
        "mobile": "https://m.facebook.com/mps.gov",
        "tier": "OFFICIAL",
    },

    # --------------------------------------------------------
    # SOCIAL RADAR
    # --------------------------------------------------------
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


MAX_POSTS_PER_SOURCE = 3
SCROLL_ROUNDS = 3
SCROLL_WAIT_MS = 1200

RESULT_FILE = "radar_results.json"
EVENT_FILE = "radar_events.json"
VERIFIED_FILE = "radar_verified.json"
EDITOR_QUEUE_FILE = "radar_editor_queue.json"
HISTORY_FILE = "radar_history.json"

MAX_HISTORY = 3000
EVENT_SIMILARITY_THRESHOLD = 0.42


# ============================================================
# SOURCE TRUST
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
    "và", "là", "của", "có", "cho", "với", "một",
    "những", "các", "được", "đang", "đã", "sẽ",
    "khi", "thì", "mà", "tại", "trong", "sau",
    "trước", "này", "đó", "về", "theo", "từ",
    "đến", "trên", "dưới", "lại", "ra", "vào",
    "ở", "vẫn", "cũng", "rất", "không", "người",
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

    if (
        "story.php" not in low
        and "photo.php" not in low
    ):
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
        match = re.search(
            pattern,
            url,
            re.I,
        )

        if match:
            return match.group(1)

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        for key in (
            "story_fbid",
            "fbid",
        ):
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
                    href = (
                        links.nth(j)
                        .get_attribute("href")
                    )

                    href = normalize_url(
                        href
                    )

                    if is_post_url(href):
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
                "time": get_time_text(
                    raw_text
                ),
                "text": text,
            }

        except Exception:
            continue

    return found


def discover_entry(
    page,
    url,
    label,
):
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
            batch = extract_articles(
                page
            )

            for key, post in batch.items():
                if key not in discovered:
                    discovered[key] = post

                else:
                    old_text = (
                        discovered[key]
                        .get("text", "")
                    )

                    new_text = post.get(
                        "text",
                        "",
                    )

                    if (
                        len(new_text)
                        > len(old_text)
                    ):
                        discovered[key] = post

            print(
                f"  round {round_no + 1}: "
                f"{len(discovered)} candidate posts"
            )

            if (
                len(discovered)
                >= MAX_POSTS_PER_SOURCE
            ):
                break

            page.mouse.wheel(
                0,
                3500,
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
    print("=" * 78)
    print(
        "SOURCE:",
        source_name,
    )
    print(
        "TIER:",
        config["tier"],
    )
    print("=" * 78)

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

        for key, post in batch.items():
            if key not in combined:
                combined[key] = post

            else:
                old_text = (
                    combined[key]
                    .get("text", "")
                )

                new_text = post.get(
                    "text",
                    "",
                )

                if (
                    len(new_text)
                    > len(old_text)
                ):
                    combined[key] = post

    posts = list(
        combined.values()
    )

    posts = posts[
        :MAX_POSTS_PER_SOURCE
    ]

    for post in posts:
        post["source"] = source_name
        post["source_tier"] = (
            config["tier"]
        )

    print(
        f">>> {source_name}: "
        f"{len(posts)} POSTS"
    )

    return posts


# ============================================================
# MATCHING
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


def ordered_unique(items):
    result = []

    for item in items:
        if item not in result:
            result.append(item)

    return result


def keyword_set(text):
    return set(
        significant_words(text)
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
            a[:1500],
            b[:1500],
        ).ratio()
    )

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


# ============================================================
# EVENT CLUSTERING
# ============================================================

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
            "bí mật showbiz",
            "thông tin chính phủ",
            "bộ công an",
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

            if event_best > best_score:
                best_score = event_best
                best_event = event

        if (
            best_event is not None
            and best_score
            >= EVENT_SIMILARITY_THRESHOLD
        ):
            best_event[
                "posts"
            ].append(post)

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
                    post["source_tier"]
                )

        else:
            event_hash = hashlib.sha1(
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
            ).hexdigest()[:12]

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
# NEWS SEARCH
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

    useful = words[:12]

    if len(useful) >= 3:
        return " ".join(
            useful
        )

    return title[:180]


def google_news_search(query):
    if not query:
        return []

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
            "News search error:",
            exc,
        )
        return []

    results = []

    for entry in feed.entries[:20]:
        title = clean_text(
            entry.get(
                "title",
                "",
            )
        )

        google_url = entry.get(
            "link",
            "",
        )

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

        published = entry.get(
            "published",
            "",
        )

        results.append({
            "title": title,
            "google_news_url":
                google_url,
            "source_name":
                source_name,
            "published":
                published,
        })

    return results


# ============================================================
# ORIGINAL ARTICLE RESOLUTION
# ============================================================

def resolve_original_article_url(
    google_url,
):
    if not google_url:
        return None

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
            google_url,
            headers=headers,
            timeout=20,
            allow_redirects=True,
        )

        final_url = response.url

        if not final_url:
            return None

        host = (
            urlparse(
                final_url
            )
            .netloc
            .lower()
        )

        if (
            "google.com" in host
            or "news.google" in host
        ):
            return None

        return final_url

    except Exception:
        return None


# ============================================================
# SOURCE CLASSIFICATION
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
        "nhân dân",
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
        host = (
            urlparse(url)
            .netloc
            .lower()
            .replace(
                "www.",
                "",
            )
        )

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
# STRICT MATCH V7.2
# ============================================================

def verification_match(
    event,
    article_title,
):
    event_title = event.get(
        "title",
        "",
    )

    event_words = ordered_unique(
        significant_words(
            event_title
        )
    )

    article_words = set(
        significant_words(
            article_title
        )
    )

    if (
        not event_words
        or not article_words
    ):
        return {
            "accepted": False,
            "score": 0,
            "matched_words": [],
            "coverage": 0,
        }

    matched = [
        word
        for word in event_words
        if word in article_words
    ]

    coverage = (
        len(matched)
        / len(event_words)
    )

    text_score = similarity(
        event_title,
        article_title,
    )

    event_word_count = len(
        event_words
    )

    accepted = False

    if event_word_count <= 3:
        accepted = (
            len(matched) >= 2
            and coverage >= 0.67
            and text_score >= 0.28
        )

    elif event_word_count <= 7:
        accepted = (
            len(matched) >= 3
            and coverage >= 0.40
            and text_score >= 0.22
        )

    else:
        accepted = (
            len(matched) >= 4
            and coverage >= 0.30
            and text_score >= 0.18
        )

    return {
        "accepted":
            accepted,

        "score":
            round(
                text_score,
                3,
            ),

        "matched_words":
            matched,

        "coverage":
            round(
                coverage,
                3,
            ),
    }


# ============================================================
# OFFICIAL FACEBOOK SIGNAL
# ============================================================

def get_official_signal(event):
    official_posts = [
        post
        for post in event[
            "posts"
        ]
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
# VERIFY EVENT
# ============================================================

def verify_event(event):
    query = build_search_query(
        event
    )

    official_signal = (
        get_official_signal(
            event
        )
    )

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

    results = google_news_search(
        query
    )

    evidence = []

    for result in results:
        match = verification_match(
            event,
            result["title"],
        )

        if not match[
            "accepted"
        ]:
            continue

        level = (
            source_level_from_name(
                result[
                    "source_name"
                ]
            )
        )

        original_url = (
            resolve_original_article_url(
                result[
                    "google_news_url"
                ]
            )
        )

        if original_url:
            url_level = (
                source_level_from_url(
                    original_url
                )
            )

            if (
                url_level
                != "OTHER"
            ):
                level = (
                    url_level
                )

        evidence.append({
            "title":
                result["title"],

            "source_name":
                result[
                    "source_name"
                ],

            "published":
                result[
                    "published"
                ],

            "google_news_url":
                result[
                    "google_news_url"
                ],

            "original_article_url":
                original_url,

            "trust_level":
                level,

            "match_score":
                match[
                    "score"
                ],

            "keyword_coverage":
                match[
                    "coverage"
                ],

            "matched_words":
                match[
                    "matched_words"
                ],
        })

    trust_order = {
        "OFFICIAL_OR_PRIMARY": 3,
        "TRUSTED_NEWS": 2,
        "OTHER": 1,
    }

    evidence.sort(
        key=lambda item: (
            trust_order.get(
                item[
                    "trust_level"
                ],
                0,
            ),
            item[
                "keyword_coverage"
            ],
            item[
                "match_score"
            ],
        ),
        reverse=True,
    )

    editorial_candidates = [
        item
        for item in evidence
        if (
            item.get(
                "original_article_url"
            )
            and item[
                "trust_level"
            ] in {
                "OFFICIAL_OR_PRIMARY",
                "TRUSTED_NEWS",
            }
        )
    ]

    official_articles = [
        item
        for item
        in editorial_candidates
        if (
            item[
                "trust_level"
            ]
            == "OFFICIAL_OR_PRIMARY"
        )
    ]

    trusted_articles = [
        item
        for item
        in editorial_candidates
        if (
            item[
                "trust_level"
            ]
            == "TRUSTED_NEWS"
        )
    ]

    # --------------------------------------------------------
    # VERIFICATION STATUS
    #
    # An official Facebook post is strong evidence that the
    # official account published the statement, but it does
    # not automatically create an article URL for the editor.
    # --------------------------------------------------------

    if official_articles:
        status = (
            "CO_NGUON_CHINH_THONG_DOI_CHIEU"
        )

    elif (
        official_signal
        and len(
            trusted_articles
        ) >= 1
    ):
        status = (
            "CO_TIN_HIEU_CHINH_THUC_VA_BAO_DOI_CHIEU"
        )

    elif len(
        trusted_articles
    ) >= 2:
        status = (
            "CO_NHIEU_BAO_UY_TIN_DOI_CHIEU"
        )

    elif len(
        trusted_articles
    ) == 1:
        status = (
            "CO_MOT_NGUON_BAO_DOI_CHIEU"
        )

    elif official_signal:
        status = (
            "CO_TIN_HIEU_CHINH_THUC"
        )

    else:
        status = (
            "CHUA_XAC_MINH"
        )

    # --------------------------------------------------------
    # EDITORIAL SOURCE
    #
    # bao-chi-tu-link needs a real article URL.
    # Prefer official-domain article, then trusted press.
    # --------------------------------------------------------

    editorial_source = None

    if editorial_candidates:
        best = (
            editorial_candidates[0]
        )

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

            "match_score":
                best[
                    "match_score"
                ],

            "keyword_coverage":
                best[
                    "keyword_coverage"
                ],
        }

    event[
        "search_query"
    ] = query

    event[
        "official_signal"
    ] = official_signal

    event[
        "verification"
    ] = status

    event[
        "verification_evidence"
    ] = evidence[:5]

    event[
        "editorial_source"
    ] = editorial_source

    # Only send automatically to bao-chi-tu-link if
    # we actually have an original article URL.
    event[
        "send_to_editor"
    ] = (
        editorial_source
        is not None
    )

    return event


# ============================================================
# EDITORIAL FILTER
# ============================================================

def classify_event(event):
    source_count = len(
        event["sources"]
    )

    verification = (
        event.get(
            "verification",
            "CHUA_XAC_MINH",
        )
    )

    send_to_editor = (
        event.get(
            "send_to_editor",
            False,
        )
    )

    if (
        verification
        in {
            "CO_NGUON_CHINH_THONG_DOI_CHIEU",
            "CO_TIN_HIEU_CHINH_THUC_VA_BAO_DOI_CHIEU",
            "CO_NHIEU_BAO_UY_TIN_DOI_CHIEU",
        }
        and send_to_editor
    ):
        decision = (
            "CHUYEN_BAN_BIEN_TAP"
        )

        reason = (
            "Có bằng chứng nguồn đủ mạnh "
            "và đã lấy được URL bài báo gốc."
        )

    elif (
        verification
        == "CO_MOT_NGUON_BAO_DOI_CHIEU"
        and send_to_editor
    ):
        decision = (
            "THEO_DOI"
        )

        reason = (
            "Có một nguồn báo uy tín phù hợp "
            "và URL bài gốc; tiếp tục theo dõi."
        )

    elif (
        verification
        == "CO_TIN_HIEU_CHINH_THUC"
    ):
        decision = (
            "TIM_NGUON_GOC"
        )

        reason = (
            "Radar đã bắt được bài từ nguồn "
            "Facebook chính thức nhưng chưa "
            "lấy được bài báo/website gốc để "
            "giao cho bàn biên tập."
        )

    elif source_count >= 2:
        decision = (
            "CAN_XAC_MINH_GAP"
        )

        reason = (
            "Nhiều nguồn social cùng nhắc "
            "đến sự kiện nhưng chưa đủ "
            "nguồn xác minh."
        )

    else:
        decision = (
            "BO_QUA_TAM_THOI"
        )

        reason = (
            "Chưa có đủ bằng chứng nguồn "
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

            "editor_skill":
                "bao-chi-tu-link",

            "editorial_rule": (
                "Read the original article in full "
                "before writing. Social posts are "
                "trend signals only and must not be "
                "used to add factual details that "
                "are absent from the original article."
            ),
        })

    return queue


# ============================================================
# MAIN
# ============================================================

def main():
    now = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    print("=" * 78)
    print(
        "HONG CUNG TOI - RADAR V7.2"
    )
    print(
        "OFFICIAL + SOCIAL -> EVENT -> "
        "VERIFY -> ORIGINAL ARTICLE -> EDITOR"
    )
    print(
        "TIME:",
        now,
    )
    print("=" * 78)

    history = load_history()

    print(
        "HISTORY LOADED:",
        len(history),
    )

    all_posts = []
    source_results = {}

    # --------------------------------------------------------
    # COLLECT FACEBOOK
    # --------------------------------------------------------

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

            posts = collect_source(
                page,
                source_name,
                config,
            )

            source_results[
                source_name
            ] = posts

            all_posts.extend(
                posts
            )

        browser.close()

    # --------------------------------------------------------
    # DEDUP
    # --------------------------------------------------------

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
                unique_posts[key]
                .get(
                    "text",
                    "",
                )
            )

            new_text = post.get(
                "text",
                "",
            )

            if (
                len(new_text)
                > len(old_text)
            ):
                unique_posts[
                    key
                ] = post

    # --------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------

    new_posts = []
    seen_posts = []

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

    # --------------------------------------------------------
    # EVENTS
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
            f"{index}/{len(events)}"
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

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # RESULT JSON
    # --------------------------------------------------------

    result_output = {
        "generated_at":
            now,

        "version":
            "7.2",

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

    # --------------------------------------------------------
    # EVENT JSON
    # --------------------------------------------------------

    event_output = {
        "generated_at":
            now,

        "version":
            "7.2",

        "event_count":
            len(
                verified_events
            ),

        "events":
            verified_events,
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

    # --------------------------------------------------------
    # VERIFIED JSON
    # --------------------------------------------------------

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
            "7.2",

        "actionable_count":
            len(
                actionable
            ),

        "events":
            actionable,
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
    # EDITOR QUEUE JSON
    # --------------------------------------------------------

    queue_output = {
        "generated_at":
            now,

        "version":
            "7.2",

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

    with open(
        EDITOR_QUEUE_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            queue_output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # CONSOLE SUMMARY
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "FINAL RADAR RESULT"
    )
    print("=" * 78)

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

    print(
        "EDITOR QUEUE:",
        len(
            editor_queue
        ),
    )

    # --------------------------------------------------------
    # VERIFICATION REPORT
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "VERIFICATION RADAR V7.2"
    )
    print("=" * 78)

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
            "MATCHED NEWS:",
            len(
                evidence
            ),
        )

        for item in evidence:
            print(
                " -",
                "["
                + item[
                    "trust_level"
                ]
                + "]",
                item[
                    "source_name"
                ],
                "| coverage:",
                item[
                    "keyword_coverage"
                ],
                "|",
                item[
                    "title"
                ][:160],
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

    # --------------------------------------------------------
    # EDITOR QUEUE REPORT
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "EDITOR QUEUE -> bao-chi-tu-link"
    )
    print("=" * 78)

    if not editor_queue:
        print(
            "No event currently has "
            "an original article URL "
            "ready for the editor."
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

        if item[
            "official_signal"
        ]:
            print(
                "OFFICIAL SIGNAL:",
                item[
                    "official_signal"
                ][
                    "source"
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
        "=== RADAR V7.2 FINISHED ==="
    )


if __name__ == "__main__":
    main()
