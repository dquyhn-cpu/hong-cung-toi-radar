import io
import json
import os
import requests
from PIL import Image

GRAPH_VERSION = os.getenv("FB_GRAPH_VERSION", "v26.0")
PAGE_ID = os.environ["FB_PAGE_ID"]
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]

session = requests.Session()

def show(label, response):
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    print(label, json.dumps({
        "status": response.status_code,
        "payload": payload,
        "headers": {
            "content-type": response.headers.get("content-type"),
            "x-fb-trace-id": response.headers.get("x-fb-trace-id"),
            "x-fb-rev": response.headers.get("x-fb-rev"),
        },
    }, ensure_ascii=False))
    return payload

def get(path, params=None):
    p = dict(params or {})
    p["access_token"] = TOKEN
    r = session.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}", params=p, timeout=30)
    return show("GET " + path, r)

get("/me", {"fields": "id,name"})
get("/me/permissions")
get(f"/{PAGE_ID}", {"fields": "id,name,tasks"})

# Generate a plain, standards-compliant 600x600 RGB JPEG in memory.
im = Image.new("RGB", (600, 600), (245, 245, 245))
buf = io.BytesIO()
im.save(buf, format="JPEG", quality=88, optimize=False, progressive=False)
image = buf.getvalue()
print("TEST_JPEG_BYTES", len(image), image[:2].hex(), image[-2:].hex())

r = session.post(
    f"https://graph.facebook.com/{GRAPH_VERSION}/{PAGE_ID}/photos",
    data={"published": "false", "access_token": TOKEN},
    files={"source": ("diag_600.jpg", image, "image/jpeg")},
    timeout=60,
)
payload = show("UNPUBLISHED_PHOTO_GENERATED", r)
if not r.ok or "error" in payload:
    raise SystemExit(2)

print("DIAGNOSTIC_PHOTO_OK", payload.get("id"))
