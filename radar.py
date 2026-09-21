import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.facebook.com/beatvn.network"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

print("=== HONG CUNG TOI RADAR TEST ===")
print("Time:", datetime.utcnow().isoformat(), "UTC")
print("Target:", URL)

try:
    r = requests.get(URL, headers=headers, timeout=30)

    print("HTTP status:", r.status_code)
    print("Downloaded:", len(r.content), "bytes")
    print("Final URL:", r.url)

    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else "NO TITLE"
    print("Page title:", title)

    text = soup.get_text(" ", strip=True)
    print("Text length:", len(text))

    print("\n--- SAMPLE ---")
    print(text[:2000])

except Exception as e:
    print("ERROR:", repr(e))
    raise
