from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
import re

TARGET = "https://www.facebook.com/beatvn.network"
MAX_POSTS = 10

print("=== HONG CUNG TOI RADAR - BEATVN POSTS TEST ===")
print("Time:", datetime.now(timezone.utc).isoformat())
print("Target:", TARGET)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
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

    try:
        response = page.goto(
            TARGET,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        print("HTTP status:", response.status if response else "No response")
        print("Final URL:", page.url)
        print("Title:", page.title())

        # Cuộn để Facebook tải thêm bài viết
        for i in range(6):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(2000)

        # Facebook thường đặt bài viết trong role="article"
        articles = page.locator('[role="article"]')

        count = articles.count()

        print("\nArticles found:", count)
        print("=" * 80)

        found = 0
        seen = set()

        for i in range(count):
            if found >= MAX_POSTS:
                break

            article = articles.nth(i)

            try:
                text = article.inner_text(timeout=5000).strip()
            except Exception:
                continue

            text = re.sub(r"\n{3,}", "\n\n", text)

            # Bỏ các khối quá ngắn
            if len(text) < 40:
                continue

            # Tìm link có dạng bài viết Facebook
            links = article.locator("a")
            post_url = ""

            for j in range(min(links.count(), 50)):
                try:
                    href = links.nth(j).get_attribute("href") or ""

                    if any(
                        key in href
                        for key in [
                            "/posts/",
                            "/videos/",
                            "/reel/",
                            "story_fbid=",
                            "permalink.php",
                        ]
                    ):
                        if href.startswith("/"):
                            href = "https://www.facebook.com" + href

                        post_url = href.split("?__cft__")[0]
                        break

                except Exception:
                    pass

            # Tránh in trùng
            fingerprint = text[:200]

            if fingerprint in seen:
                continue

            seen.add(fingerprint)
            found += 1

            print(f"\n--- POST {found} ---")
            print("URL:", post_url if post_url else "Không tìm thấy permalink")
            print("TEXT:")
            print(text[:3000])
            print("-" * 80)

        print("\n=== RESULT ===")
        print("Posts extracted:", found)

        if found == 0:
            print("WARNING: Facebook page loaded but no public post blocks were extracted.")

    except Exception as e:
        print("ERROR:", repr(e))

    finally:
        browser.close()
