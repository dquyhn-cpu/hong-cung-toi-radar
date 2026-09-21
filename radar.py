from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
import re
import json

# ============================================================
# HONG CUNG TOI - SOCIAL RADAR COLLECTOR
# ============================================================

SOURCES = {
    "BeatVN": "https://www.facebook.com/beatvn.network",
    "Theanh28": "https://www.facebook.com/theanh28",
    "Top Comments": "https://www.facebook.com/topcomments.vn",
}

MAX_POSTS_PER_PAGE = 8

IGNORE_LINES = {
    "Đăng nhập",
    "Bạn quên tài khoản ư?",
    "Xem thêm",
    "Thích",
    "Bình luận",
    "Chia sẻ",
    "Tất cả cảm xúc:",
    "Ảnh",
    "Video",
    "Reels",
    "Bài viết",
    "Giới thiệu",
}


def clean_text(text):
    if not text:
        return ""

    lines = []

    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()

        if not line:
            continue

        if line in IGNORE_LINES:
            continue

        lines.append(line)

    return "\n".join(lines)


def find_time(text):
    patterns = [
        r"\b\d+\s*phút\b",
        r"\b\d+\s*giờ\b",
        r"\b\d+\s*ngày\b",
        r"\b\d+\s*phút trước\b",
        r"\b\d+\s*giờ trước\b",
        r"\b\d+\s*ngày trước\b",
        r"\bVừa xong\b",
        r"\bHôm qua\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return ""


def find_engagement(text):
    result = {
        "reactions": None,
        "comments": None,
        "shares": None,
    }

    # Facebook thay đổi HTML khá thường xuyên.
    # Phần này cố lấy tín hiệu nếu chúng xuất hiện trong text.
    comment_patterns = [
        r"([\d,.KkMm]+)\s*(?:bình luận|comments?)",
    ]

    share_patterns = [
        r"([\d,.KkMm]+)\s*(?:lượt chia sẻ|chia sẻ|shares?)",
    ]

    reaction_patterns = [
        r"Tất cả cảm xúc:\s*([\d,.KkMm]+)",
    ]

    for pattern in comment_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result["comments"] = m.group(1)
            break

    for pattern in share_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result["shares"] = m.group(1)
            break

    for pattern in reaction_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result["reactions"] = m.group(1)
            break

    return result


def extract_post_url(article):
    links = article.locator("a").all()

    candidates = []

    for link in links:
        try:
            href = link.get_attribute("href")

            if not href:
                continue

            if href.startswith("/"):
                href = "https://www.facebook.com" + href

            if (
                "/posts/" in href
                or "/videos/" in href
                or "/reel/" in href
                or "story_fbid=" in href
                or "/photo/" in href
            ):
                candidates.append(href)

        except Exception:
            continue

    if not candidates:
        return ""

    url = candidates[0]

    # Bỏ tracking query không cần thiết nếu có
    if "?" in url and "story_fbid=" not in url:
        url = url.split("?")[0]

    return url


def looks_like_real_post(text, url):
    if not url:
        return False

    if len(text) < 20:
        return False

    bad_markers = [
        "Đăng nhập",
        "Bạn quên tài khoản",
        "Tạo tài khoản mới",
    ]

    if all(marker in text for marker in bad_markers):
        return False

    return True


def extract_page_posts(page, source_name, source_url):
    print()
    print("=" * 90)
    print(f"SOURCE: {source_name}")
    print(f"URL: {source_url}")
    print("=" * 90)

    try:
        response = page.goto(
            source_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        print(
            "HTTP:",
            response.status if response else "NO RESPONSE"
        )

        print("TITLE:", page.title())
        print("FINAL URL:", page.url)

        # Scroll vài lần để Facebook nạp thêm bài
        for i in range(4):
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(1800)

        articles = page.locator('[role="article"]')

        count = articles.count()

        print("ARTICLES FOUND:", count)

        results = []
        seen_urls = set()

        limit = min(count, 20)

        for i in range(limit):
            try:
                article = articles.nth(i)

                raw_text = article.inner_text(timeout=5000)
                text = clean_text(raw_text)

                url = extract_post_url(article)

                if not looks_like_real_post(text, url):
                    continue

                if url in seen_urls:
                    continue

                seen_urls.add(url)

                time_text = find_time(text)
                engagement = find_engagement(raw_text)

                # Giới hạn text để log không quá dài
                if len(text) > 2500:
                    text = text[:2500] + "..."

                post = {
                    "source": source_name,
                    "page": source_url,
                    "url": url,
                    "time": time_text,
                    "text": text,
                    "engagement": engagement,
                }

                results.append(post)

                print()
                print("-" * 80)
                print(f"POST #{len(results)}")
                print("URL:", url)
                print("TIME:", time_text or "unknown")
                print(
                    "ENGAGEMENT:",
                    json.dumps(
                        engagement,
                        ensure_ascii=False
                    )
                )
                print("TEXT:")
                print(text[:1200])

                if len(results) >= MAX_POSTS_PER_PAGE:
                    break

            except Exception as exc:
                print(f"Skip article {i + 1}: {exc}")

        print()
        print(
            f">>> {source_name}: "
            f"{len(results)} POSTS EXTRACTED"
        )

        return results

    except Exception as exc:
        print(f"ERROR {source_name}: {exc}")
        return []


def main():
    print("=" * 90)
    print("HONG CUNG TOI - SOCIAL RADAR")
    print("MULTI-PAGE COLLECTOR")
    print(
        "TIME:",
        datetime.now(timezone.utc).isoformat()
    )
    print("=" * 90)

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
            viewport={
                "width": 1280,
                "height": 900,
            },
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for source_name, source_url in SOURCES.items():
            posts = extract_page_posts(
                page,
                source_name,
                source_url,
            )

            all_posts.extend(posts)

            # Nghỉ một chút giữa các page
            page.wait_for_timeout(2500)

        browser.close()

    print()
    print("=" * 90)
    print("FINAL RADAR RESULT")
    print("=" * 90)

    print("TOTAL POSTS:", len(all_posts))

    source_stats = {}

    for post in all_posts:
        source = post["source"]

        source_stats[source] = (
            source_stats.get(source, 0) + 1
        )

    print(
        "SOURCE STATS:",
        json.dumps(
            source_stats,
            ensure_ascii=False,
        )
    )

    # Xuất JSON để bước sau dùng cho bộ lọc tin hot
    with open(
        "radar_results.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            {
                "generated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "total_posts": len(all_posts),
                "posts": all_posts,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("Saved: radar_results.json")

    print()
    print("=== RADAR FINISHED ===")


if __name__ == "__main__":
    main()
