from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
import re
import json
import os
import hashlib

# ============================================================
# HONG CUNG TOI - SOCIAL RADAR V3
# 5 newest posts/source + dedup + event-ready output
# ============================================================

SOURCES = {
    "BeatVN": "https://www.facebook.com/beatvn.network",
    "Theanh28": "https://www.facebook.com/theanh28",
    "Top Comments": "https://www.facebook.com/topcomments.vn",
}

MAX_POSTS_PER_PAGE = 5
MAX_ARTICLES_TO_SCAN = 20

RESULT_FILE = "radar_results.json"
HISTORY_FILE = "radar_history.json"

IGNORE_EXACT = {
    "Đăng nhập",
    "Bạn quên tài khoản ư?",
    "Xem thêm",
    "Xem thêm bình luận",
    "Thích",
    "Bình luận",
    "Chia sẻ",
    "Tất cả cảm xúc:",
    "Ảnh",
    "Video",
    "Reels",
    "Bài viết",
    "Giới thiệu",
    "Đang hoạt động",
    "Chỉ báo trạng thái online",
}


def clean_line(line):
    return re.sub(r"\s+", " ", line or "").strip()


def clean_text(text, source_name=""):
    if not text:
        return ""

    output = []
    previous = None

    for raw in text.splitlines():
        line = clean_line(raw)

        if not line:
            continue

        if line in IGNORE_EXACT:
            continue

        if source_name and line.lower() == source_name.lower():
            continue

        # Loại các dòng chỉ chứa số/tương tác đơn lẻ
        if re.fullmatch(r"[\d,.]+\s*[KkMm]?", line):
            continue

        # Loại dòng thời gian đơn lẻ
        if re.fullmatch(
            r"(Vừa xong|Hôm qua|\d+\s*(phút|giờ|ngày))",
            line,
            re.IGNORECASE,
        ):
            continue

        if line == previous:
            continue

        output.append(line)
        previous = line

    return "\n".join(output)


def normalize_url(url):
    if not url:
        return ""

    url = url.replace("&amp;", "&")

    if url.startswith("/"):
        url = "https://www.facebook.com" + url

    # Với URL dạng /posts/... query tracking không cần thiết
    if "/posts/" in url or "/videos/" in url or "/reel/" in url:
        parts = urlsplit(url)
        url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, "", "")
        )

    return url


def post_id_from_url(url):
    if not url:
        return ""

    patterns = [
        r"/posts/([^/?#]+)",
        r"/videos/([^/?#]+)",
        r"/reel/([^/?#]+)",
        r"[?&]story_fbid=([^&#]+)",
        r"[?&]fbid=([^&#]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return hashlib.sha1(
        url.encode("utf-8")
    ).hexdigest()[:20]


def find_post_url(article):
    candidates = []

    try:
        links = article.locator("a")

        for i in range(links.count()):
            try:
                href = links.nth(i).get_attribute("href")

                if not href:
                    continue

                href = normalize_url(href)

                if (
                    "/posts/" in href
                    or "/videos/" in href
                    or "/reel/" in href
                    or "story_fbid=" in href
                    or "fbid=" in href
                ):
                    candidates.append(href)

            except Exception:
                pass

    except Exception:
        pass

    if not candidates:
        return ""

    # Ưu tiên URL posts
    for url in candidates:
        if "/posts/" in url:
            return url

    return candidates[0]


def find_time(text):
    patterns = [
        r"\bVừa xong\b",
        r"\b\d+\s*phút\b",
        r"\b\d+\s*giờ\b",
        r"\b\d+\s*ngày\b",
        r"\bHôm qua\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return match.group(0)

    return ""


def parse_number(value):
    if not value:
        return None

    value = value.strip().replace(",", ".")

    match = re.search(
        r"([\d.]+)\s*([KkMm]?)",
        value
    )

    if not match:
        return None

    try:
        number = float(match.group(1))
    except ValueError:
        return None

    suffix = match.group(2).lower()

    if suffix == "k":
        number *= 1000
    elif suffix == "m":
        number *= 1000000

    return int(number)


def extract_engagement(raw_text):
    result = {
        "reactions": None,
        "comments": None,
        "shares": None,
    }

    patterns = {
        "comments": [
            r"([\d.,]+\s*[KkMm]?)\s*(?:bình luận|comments?)",
        ],
        "shares": [
            r"([\d.,]+\s*[KkMm]?)\s*(?:lượt chia sẻ|chia sẻ|shares?)",
        ],
        "reactions": [
            r"Tất cả cảm xúc:\s*([\d.,]+\s*[KkMm]?)",
        ],
    }

    for key, regexes in patterns.items():
        for regex in regexes:
            match = re.search(
                regex,
                raw_text,
                re.IGNORECASE
            )

            if match:
                result[key] = parse_number(
                    match.group(1)
                )
                break

    return result


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {
            "seen_post_ids": {},
            "updated_at": None,
        }

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if "seen_post_ids" not in data:
            data["seen_post_ids"] = {}

        return data

    except Exception:
        return {
            "seen_post_ids": {},
            "updated_at": None,
        }


def save_history(history):
    history["updated_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2
        )


def looks_like_post(text, url):
    if not url:
        return False

    if len(text.strip()) < 5:
        return False

    return True


def collect_source(page, source_name, source_url):
    print()
    print("=" * 90)
    print("SOURCE:", source_name)
    print("URL:", source_url)
    print("=" * 90)

    results = []

    try:
        response = page.goto(
            source_url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(4500)

        print(
            "HTTP:",
            response.status if response else "NO RESPONSE"
        )
        print("TITLE:", page.title())
        print("FINAL URL:", page.url)

        # Nạp thêm feed
        for _ in range(6):
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(1200)

        articles = page.locator('[role="article"]')
        article_count = articles.count()

        print("ARTICLES FOUND:", article_count)

        seen_this_source = set()

        scan_count = min(
            article_count,
            MAX_ARTICLES_TO_SCAN
        )

        for i in range(scan_count):
            if len(results) >= MAX_POSTS_PER_PAGE:
                break

            try:
                article = articles.nth(i)

                raw_text = article.inner_text(
                    timeout=5000
                )

                url = find_post_url(article)

                if not url:
                    print(
                        f"Article {i + 1}: "
                        "no post URL"
                    )
                    continue

                post_id = post_id_from_url(url)

                if post_id in seen_this_source:
                    continue

                text = clean_text(
                    raw_text,
                    source_name
                )

                if not looks_like_post(text, url):
                    continue

                seen_this_source.add(post_id)

                post = {
                    "source": source_name,
                    "source_url": source_url,
                    "post_id": post_id,
                    "url": url,
                    "time_text": find_time(raw_text),
                    "text": text[:4000],
                    "engagement":
                        extract_engagement(raw_text),
                }

                results.append(post)

                print()
                print("-" * 75)
                print(
                    f"POST #{len(results)}"
                )
                print("POST ID:", post_id)
                print("URL:", url)
                print(
                    "TIME:",
                    post["time_text"]
                    or "unknown"
                )
                print(
                    "ENGAGEMENT:",
                    json.dumps(
                        post["engagement"],
                        ensure_ascii=False
                    )
                )
                print("TEXT:")
                print(text[:1000])

            except Exception as exc:
                print(
                    f"Article {i + 1} "
                    f"skipped: {exc}"
                )

        print()
        print(
            f">>> {source_name}: "
            f"{len(results)} POSTS EXTRACTED"
        )

    except Exception as exc:
        print(
            f"ERROR collecting "
            f"{source_name}: {exc}"
        )

    return results


def main():
    now = datetime.now(timezone.utc)

    print("=" * 90)
    print("HONG CUNG TOI - SOCIAL RADAR V3")
    print("5 POSTS/SOURCE + DEDUP")
    print("TIME:", now.isoformat())
    print("=" * 90)

    history = load_history()
    previously_seen = history[
        "seen_post_ids"
    ]

    collected = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features="
                "AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = browser.new_context(
            viewport={
                "width": 1280,
                "height": 900
            },
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        for source_name, source_url in SOURCES.items():
            posts = collect_source(
                page,
                source_name,
                source_url
            )

            collected.extend(posts)

            page.wait_for_timeout(1800)

        browser.close()

    # ----------------------------------------
    # Chống trùng giữa các source trong lượt
    # ----------------------------------------

    unique_posts = []
    run_seen = set()

    for post in collected:
        pid = post["post_id"]

        if pid in run_seen:
            continue

        run_seen.add(pid)
        unique_posts.append(post)

    # ----------------------------------------
    # Phân loại NEW / SEEN
    # ----------------------------------------

    new_posts = []
    seen_posts = []

    for post in unique_posts:
        pid = post["post_id"]

        if pid in previously_seen:
            post["radar_status"] = "SEEN"
            seen_posts.append(post)

        else:
            post["radar_status"] = "NEW"
            new_posts.append(post)

            previously_seen[pid] = {
                "source": post["source"],
                "url": post["url"],
                "first_seen":
                    now.isoformat()
            }

    # Giới hạn history để file không phình mãi
    if len(previously_seen) > 1000:
        items = list(
            previously_seen.items()
        )

        previously_seen = dict(
            items[-1000:]
        )

    history["seen_post_ids"] = (
        previously_seen
    )

    save_history(history)

    output = {
        "generated_at": now.isoformat(),
        "sources": list(SOURCES.keys()),
        "collected_count":
            len(collected),
        "unique_count":
            len(unique_posts),
        "new_count":
            len(new_posts),
        "seen_count":
            len(seen_posts),
        "new_posts":
            new_posts,
        "all_posts":
            unique_posts,
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

    print()
    print("=" * 90)
    print("FINAL RADAR RESULT")
    print("=" * 90)

    source_stats = {}

    for post in collected:
        source = post["source"]

        source_stats[source] = (
            source_stats.get(source, 0) + 1
        )

    print(
        "SOURCE STATS:",
        json.dumps(
            source_stats,
            ensure_ascii=False
        )
    )

    print(
        "COLLECTED:",
        len(collected)
    )
    print(
        "UNIQUE:",
        len(unique_posts)
    )
    print(
        "NEW:",
        len(new_posts)
    )
    print(
        "ALREADY SEEN:",
        len(seen_posts)
    )

    print()
    print("NEW POSTS:")

    for post in new_posts:
        print(
            f"- [{post['source']}] "
            f"{post['time_text']} | "
            f"{post['url']}"
        )

    print()
    print(
        "Saved:",
        RESULT_FILE
    )
    print(
        "History:",
        HISTORY_FILE
    )
    print("=== RADAR V3 FINISHED ===")


if __name__ == "__main__":
    main()
