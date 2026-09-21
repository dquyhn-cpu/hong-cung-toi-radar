from playwright.sync_api import sync_playwright
from datetime import datetime, timezone

TARGET = "https://www.facebook.com/beatvn.network"

print("=== HONG CUNG TOI RADAR - PLAYWRIGHT TEST ===")
print("Time:", datetime.now(timezone.utc).isoformat())
print("Target:", TARGET)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
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

        text = page.locator("body").inner_text(timeout=10000)

        print("Text length:", len(text))
        print("\n--- PAGE SAMPLE ---")
        print(text[:5000])

    except Exception as e:
        print("ERROR:", repr(e))

    finally:
        browser.close()
