from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs
import json
import os
import re
import hashlib

# ============================================================
# HONG CUNG TOI - SOCIAL RADAR V5
# Multi-entry discovery + persistent dedup
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

MAX_POSTS_PER_SOURCE = 8
SCROLL_ROUNDS = 5
SCROLL_WAIT_MS = 1400

RESULT_FILE = "radar_results.json"
HISTORY_FILE = "radar_history.json"
MAX_HISTORY = 3000

POST_MARKERS = (
    "/posts/",
    "/videos/",
    "/reel/",
    "/permalink/",
    "/photo/",
    "story.php",
    "photo.php",
)


# ------------------------------------------------------------
# HISTORY
# ------------------------------------------------------------

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

        # compatibility with old list format
        if isinstance(data, list):
            return {
                str(x): {
                    "first_seen": None
                }
                for x in data
            }

    except Exception as e:
        print("History load warning:", e)

    return {}


def save_history(history):
    # Keep newest records only
    items = list(history.items())

    if len(items) > MAX_HISTORY:
        items = items[-MAX_HISTORY:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            dict(items),
            f,
            ensure_ascii=False,
            indent=2
        )


# ------------------------------------------------------------
# URL NORMALIZATION
# ------------------------------------------------------------

def normalize_url(url):
    if not url:
        return None

    url = url.strip()

    if url.startswith("/"):
        url = urljoin("https://www.facebook.com", url)

    if not url.startswith("http"):
        return None

    try:
        parsed = urlparse(url)

        # Facebook redirect URL
        if "l.facebook.com" in parsed.netloc:
            qs = parse_qs(parsed.query)

            if qs.get("u"):
                url = qs["u"][0]

    except Exception:
        pass

    url = url.replace(
        "https://m.facebook.com/",
        "https://www.facebook.com/"
    )

    url = url.replace(
        "http://m.facebook.com/",
        "https://www.facebook.com/"
    )

    # Preserve query for story.php/photo.php because ID can live there
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

    return any(marker in low for marker in POST_MARKERS)


def post_key(url):
    """
    Generate stable key for deduplication.
    """

    if not url:
        return None

    patterns = [
        r"/posts/([^/?#]+)",
        r"/videos/([^/?#]+)",
        r"/reel/([^/?#]+)",
        r"/permalink/([^/?#]+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, url, re.I)

        if m:
            return m.group(1)

    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)

        for key in ("story_fbid", "fbid", "id"):
            if qs.get(key):
                return f"{key}:{qs[key][0]}"

    except Exception:
        pass

    return hashlib.sha1(
        url.encode("utf-8")
    ).hexdigest()


# ------------------------------------------------------------
# TEXT
# ------------------------------------------------------------

def clean_text(text):
    if not text:
        return ""

    lines = []

    blacklist = {
        "xem thêm",
        "thích",
        "bình luận",
        "chia sẻ",
        "đăng nhập",
        "tạo tài khoản mới",
    }

    for raw in text.splitlines():
        line = raw.strip()

        if not line:
            continue

        if line.lower() in blacklist:
            continue

        lines.append(line)

    return "\n".join(lines)[:5000]


def get_time(text):
    if not text:
        return None

    patterns = [
        r"\b\d+\s*phút\b",
        r"\b\d+\s*giờ\b",
        r"\b\d+\s*ngày\b",
        r"\b\d+\s*tuần\b",
        r"\bvừa xong\b",
        r"\bhôm qua\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)

        if m:
            return m.group(0)

    return None


def get_engagement(text):
    result = {
        "reactions": None,
        "comments": None,
        "shares": None,
    }

    if not text:
        return result

    patterns = {
        "comments": r"([\d.,KkMm]+)\s*bình luận",
        "shares": r"([\d.,KkMm]+)\s*(?:lượt\s*)?chia sẻ",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.I)

        if m:
            result[key] = m.group(1)

    return result


# ------------------------------------------------------------
# COLLECT LINKS FROM PAGE
# ------------------------------------------------------------

def collect_links_from_dom(page):
    found = {}

    links = page.locator("a")

    try:
        count = links.count()
    except Exception:
        return found

    for i in range(count):
        try:
            link = links.nth(i)

            href = link.get_attribute("href")

            if not href:
                continue

            url = normalize_url(href)

            if not is_post_url(url):
                continue

            key = post_key(url)

            if not key:
                continue

            # Try link text first
            try:
                text = clean_text(
                    link.inner_text(timeout=1000)
                )
            except Exception:
                text = ""

            found[key] = {
                "post_id": key,
                "url": url,
                "text": text,
            }

        except Exception:
            continue

    return found


def collect_articles(page):
    found = {}

    articles = page.locator('div[role="article"]')

    try:
        count = articles.count()
    except Exception:
        count = 0

    for i in range(count):
        try:
            article = articles.nth(i)

            text = clean_text(
                article.inner_text(timeout=2500)
            )

            links = article.locator("a")

            try:
                link_count = links.count()
            except Exception:
                link_count = 0

            post_url = None

            for j in range(link_count):
                try:
                    href = links.nth(j).get_attribute("href")

                    url = normalize_url(href)

                    if is_post_url(url):
                        post_url = url
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
                "time": get_time(text),
                "engagement": get_engagement(text),
                "text": text,
            }

        except Exception:
            continue

    return found


# ------------------------------------------------------------
# DISCOVERY
# ------------------------------------------------------------

def discover(page, url, label):
    print("\nENTRY:", label)
    print("URL:", url)

    discovered = {}

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3500)

        print(
            "HTTP:",
            response.status if response else None
        )

        print("TITLE:", page.title())
        print("FINAL:", page.url)

        for round_no in range(SCROLL_ROUNDS + 1):

            # Strategy A: article containers
            articles = collect_articles(page)

            for key, item in articles.items():
                discovered[key] = item

            # Strategy B: every post-looking hyperlink
            links = collect_links_from_dom(page)

            for key, item in links.items():

                if key not in discovered:
                    discovered[key] = item

                elif (
                    not discovered[key].get("text")
                    and item.get("text")
                ):
                    discovered[key]["text"] = item["text"]

            print(
                f"  round {round_no + 1}: "
                f"{len(discovered)} candidate posts"
            )

            if len(discovered) >= MAX_POSTS_PER_SOURCE:
                break

            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(SCROLL_WAIT_MS)

    except Exception as e:
        print("ENTRY ERROR:", e)

    return discovered


# ------------------------------------------------------------
# SOURCE COLLECTION
# ------------------------------------------------------------

def collect_source(page, name, config):

    print("\n" + "=" * 78)
    print("SOURCE:", name)
    print("=" * 78)

    combined = {}

    entries = [
        ("desktop", config["page"]),
        ("mobile", config["mobile"]),
    ]

    for label, url in entries:

        batch = discover(
            page,
            url,
            label
        )

        for key, item in batch.items():

            if key not in combined:
                combined[key] = item

            else:
                # Prefer version containing more text
                old_text = combined[key].get("text", "")
                new_text = item.get("text", "")

                if len(new_text) > len(old_text):
                    combined[key] = item

        if len(combined) >= MAX_POSTS_PER_SOURCE:
            break

    posts = list(combined.values())

    # Prefer posts with useful text
    posts.sort(
        key=lambda x: len(x.get("text", "")),
        reverse=True
    )

    posts = posts[:MAX_POSTS_PER_SOURCE]

    print(
        f">>> {name}: "
        f"{len(posts)} UNIQUE POSTS DISCOVERED"
    )

    return posts


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    now = datetime.now(timezone.utc).isoformat()

    print("=" * 78)
    print("HONG CUNG TOI - SOCIAL RADAR V5")
    print("MULTI ENTRY + PERMALINK DISCOVERY + PERSISTENT DEDUP")
    print("TIME:", now)
    print("=" * 78)

    history = load_history()

    print(
        "HISTORY LOADED:",
        len(history),
        "posts"
    )

    source_results = {}
    all_posts = []

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
                "height": 1000
            },
            locale="vi-VN",
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for name, config in SOURCES.items():

            posts = collect_source(
                page,
                name,
                config
            )

            source_results[name] = posts

            for post in posts:

                post["source"] = name

                all_posts.append(post)

        browser.close()

    # --------------------------------------------------------
    # Global dedup
    # --------------------------------------------------------

    unique = {}

    for post in all_posts:

        key = post.get("post_id")

        if not key:
            continue

        if key not in unique:
            unique[key] = post

        else:
            old_text = unique[key].get("text", "")
            new_text = post.get("text", "")

            if len(new_text) > len(old_text):
                unique[key] = post

    # --------------------------------------------------------
    # Compare against persistent history
    # --------------------------------------------------------

    new_posts = []
    old_posts = []

    for key, post in unique.items():

        if key in history:

            old_posts.append(post)

            history[key]["last_seen"] = now

        else:

            new_posts.append(post)

            history[key] = {
                "source": post.get("source"),
                "url": post.get("url"),
                "first_seen": now,
                "last_seen": now,
            }

    save_history(history)

    output = {
        "generated_at": now,

        "source_stats": {
            name: len(posts)
            for name, posts in source_results.items()
        },

        "collected": len(all_posts),

        "unique": len(unique),

        "new": len(new_posts),

        "already_seen": len(old_posts),

        "posts": new_posts,
    }

    with open(
        RESULT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("\n" + "=" * 78)
    print("FINAL RADAR RESULT")
    print("=" * 78)

    print(
        "SOURCE STATS:",
        output["source_stats"]
    )

    print(
        "COLLECTED:",
        output["collected"]
    )

    print(
        "UNIQUE:",
        output["unique"]
    )

    print(
        "NEW:",
        output["new"]
    )

    print(
        "ALREADY SEEN:",
        output["already_seen"]
    )

    print("\nNEW POSTS:")

    for post in new_posts:

        print(
            f'- [{post["source"]}] '
            f'{post.get("time") or "?"} | '
            f'{post["url"]}'
        )

    print("\nSaved:", RESULT_FILE)
    print("History:", HISTORY_FILE)

    print(
        "HISTORY SIZE:",
        len(history)
    )

    print(
        "=== RADAR V5 FINISHED ==="
    )


if __name__ == "__main__":
    main()
