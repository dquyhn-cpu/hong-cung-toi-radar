from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
import json
import os
import re
import time
from urllib.parse import urljoin, urlparse, parse_qs

# =========================================================
# HONG CUNG TOI - SOCIAL RADAR V4
# =========================================================

SOURCES = {
    "BeatVN": "https://www.facebook.com/beatvn.network",
    "Theanh28": "https://www.facebook.com/Theanh28",
    "Top Comments": "https://www.facebook.com/topcomments.vn",
}

MAX_POSTS_PER_PAGE = 5
SCROLL_ROUNDS = 8
SCROLL_WAIT_MS = 1800

RESULT_FILE = "radar_results.json"
HISTORY_FILE = "radar_history.json"

POST_PATTERNS = [
    r"/posts/",
    r"/videos/",
    r"/reel/",
    r"/photo/",
    r"/permalink/",
]

IGNORE_TEXT = {
    "đăng nhập",
    "quên tài khoản",
    "xem thêm",
    "bình luận",
    "chia sẻ",
    "thích",
}


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

        return set()
    except Exception:
        return set()


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            sorted(list(history)),
            f,
            ensure_ascii=False,
            indent=2
        )


def clean_url(url):
    if not url:
        return None

    url = url.strip()

    if url.startswith("/"):
        url = urljoin("https://www.facebook.com", url)

    if not url.startswith("http"):
        return None

    # Decode Facebook redirect links if encountered
    try:
        parsed = urlparse(url)

        if "l.facebook.com" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "u" in qs and qs["u"]:
                url = qs["u"][0]
    except Exception:
        pass

    # Remove tracking/query/fragment
    url = url.split("?")[0]
    url = url.split("#")[0]

    return url.rstrip("/")


def looks_like_post_url(url):
    if not url:
        return False

    low = url.lower()

    if "facebook.com" not in low:
        return False

    for pattern in POST_PATTERNS:
        if re.search(pattern, low):
            return True

    # Story permalink form
    if "story.php" in low:
        return True

    # photo.php / watch links
    if "photo.php" in low or "/watch" in low:
        return True

    return False


def extract_post_id(url):
    if not url:
        return None

    patterns = [
        r"/posts/([^/?#]+)",
        r"/videos/([^/?#]+)",
        r"/reel/([^/?#]+)",
        r"/photo/([^/?#]+)",
        r"/permalink/([^/?#]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.I)
        if match:
            return match.group(1)

    return url


def clean_text(text):
    if not text:
        return ""

    lines = []

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if line.lower() in IGNORE_TEXT:
            continue

        lines.append(line)

    text = "\n".join(lines)

    # Avoid gigantic Facebook blocks
    return text[:4000]


def get_engagement(text):
    reactions = None
    comments = None
    shares = None

    if not text:
        return {
            "reactions": reactions,
            "comments": comments,
            "shares": shares,
        }

    patterns = [
        (r"([\d.,KkMm]+)\s*(?:lượt\s*)?(?:thích|cảm xúc)", "reactions"),
        (r"([\d.,KkMm]+)\s*bình luận", "comments"),
        (r"([\d.,KkMm]+)\s*(?:lượt\s*)?chia sẻ", "shares"),
    ]

    values = {
        "reactions": None,
        "comments": None,
        "shares": None,
    }

    for pattern, key in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            values[key] = m.group(1)

    return values


def get_time_text(article_text):
    if not article_text:
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
        m = re.search(pattern, article_text, re.I)
        if m:
            return m.group(0)

    return None


def collect_articles(page):
    collected = {}

    # Facebook dynamically loads feed.
    # Scan current DOM + scroll several rounds.
    for round_no in range(SCROLL_ROUNDS + 1):

        articles = page.locator('div[role="article"]')

        try:
            article_count = articles.count()
        except Exception:
            article_count = 0

        print(
            f"  Scan round {round_no + 1}: "
            f"{article_count} article containers"
        )

        for i in range(article_count):
            if len(collected) >= MAX_POSTS_PER_PAGE:
                break

            try:
                article = articles.nth(i)

                text = clean_text(article.inner_text(timeout=3000))

                links = article.locator("a")
                link_count = links.count()

                candidate_urls = []

                for j in range(link_count):
                    try:
                        href = links.nth(j).get_attribute("href")

                        if not href:
                            continue

                        href = clean_url(href)

                        if looks_like_post_url(href):
                            candidate_urls.append(href)

                    except Exception:
                        continue

                # Prefer first valid unique permalink
                post_url = None

                for candidate in candidate_urls:
                    if candidate not in collected:
                        post_url = candidate
                        break

                if not post_url:
                    continue

                # Skip empty/near-empty blocks
                if len(text) < 10:
                    continue

                post_id = extract_post_id(post_url)

                collected[post_url] = {
                    "post_id": post_id,
                    "url": post_url,
                    "time": get_time_text(text),
                    "engagement": get_engagement(text),
                    "text": text,
                }

                print(
                    f"    + Captured {len(collected)}: "
                    f"{post_url[:100]}"
                )

            except Exception:
                continue

        if len(collected) >= MAX_POSTS_PER_PAGE:
            break

        # Scroll feed to trigger more articles
        page.mouse.wheel(0, 3500)
        page.wait_for_timeout(SCROLL_WAIT_MS)

    return list(collected.values())[:MAX_POSTS_PER_PAGE]


def collect_source(page, source_name, source_url):
    print("\n" + "=" * 75)
    print("SOURCE:", source_name)
    print("URL:", source_url)
    print("=" * 75)

    try:
        response = page.goto(
            source_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(4000)

        status = response.status if response else None

        print("HTTP:", status)
        print("TITLE:", page.title())
        print("FINAL URL:", page.url)

        posts = collect_articles(page)

        print(f"\n>>> {source_name}: {len(posts)} POSTS EXTRACTED")

        for index, post in enumerate(posts, start=1):
            print("\n" + "-" * 65)
            print("POST #" + str(index))
            print("POST ID:", post["post_id"])
            print("URL:", post["url"])
            print("TIME:", post["time"])
            print("ENGAGEMENT:", post["engagement"])
            print("TEXT:")
            print(post["text"][:1200])

        return posts

    except Exception as e:
        print(f"ERROR {source_name}: {e}")
        return []


def main():
    print("=" * 75)
    print("HONG CUNG TOI - SOCIAL RADAR V4")
    print("MULTI-POST + SCROLL + DEDUP")
    print("TIME:", datetime.now(timezone.utc).isoformat())
    print("=" * 75)

    old_history = load_history()

    results = {}
    all_posts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 1000},
            locale="vi-VN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for source_name, source_url in SOURCES.items():
            posts = collect_source(
                page,
                source_name,
                source_url,
            )

            results[source_name] = posts

            for post in posts:
                item = dict(post)
                item["source"] = source_name
                all_posts.append(item)

        browser.close()

    # -----------------------------------------
    # Cross-source deduplication
    # -----------------------------------------

    unique_posts = []
    current_seen = set()

    for post in all_posts:
        key = post["url"]

        if key in current_seen:
            continue

        current_seen.add(key)
        unique_posts.append(post)

    # -----------------------------------------
    # Compare with previous radar runs
    # -----------------------------------------

    new_posts = []
    already_seen = []

    for post in unique_posts:
        if post["url"] in old_history:
            already_seen.append(post)
        else:
            new_posts.append(post)

    updated_history = old_history | current_seen

    # Prevent history file from growing forever
    history_list = list(updated_history)

    if len(history_list) > 2000:
        history_list = history_list[-2000:]

    save_history(set(history_list))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_stats": {
            source: len(posts)
            for source, posts in results.items()
        },
        "collected": len(all_posts),
        "unique": len(unique_posts),
        "new": len(new_posts),
        "already_seen": len(already_seen),
        "posts": new_posts,
    }

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\n" + "=" * 75)
    print("FINAL RADAR RESULT")
    print("=" * 75)

    print(
        "SOURCE STATS:",
        output["source_stats"]
    )

    print("COLLECTED:", output["collected"])
    print("UNIQUE:", output["unique"])
    print("NEW:", output["new"])
    print("ALREADY SEEN:", output["already_seen"])

    if new_posts:
        print("\nNEW POSTS:")

        for post in new_posts:
            print(
                f'- [{post["source"]}] '
                f'{post["time"] or "unknown time"} | '
                f'{post["url"]}'
            )
    else:
        print("\nNO NEW POSTS THIS RUN")

    print("\nSaved:", RESULT_FILE)
    print("History:", HISTORY_FILE)
    print("=== RADAR V4 FINISHED ===")


if __name__ == "__main__":
    main()
