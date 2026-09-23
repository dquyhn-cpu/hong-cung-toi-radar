import base64
import json
import os
import requests

GRAPH_VERSION = os.getenv("FB_GRAPH_VERSION", "v26.0")
PAGE_ID = os.environ["FB_PAGE_ID"]
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]

# 1x1 valid JPEG, used only as an unpublished diagnostic upload.
JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/"
    "xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF/"
    "/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/"
    "xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EB//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EB//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EB//2Q=="
)
image = base64.b64decode(JPEG_B64)

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

me = session.get(
    f"https://graph.facebook.com/{GRAPH_VERSION}/me",
    params={"fields": "id,name", "access_token": TOKEN},
    timeout=30,
)
show("ME", me)

r = session.post(
    f"https://graph.facebook.com/{GRAPH_VERSION}/{PAGE_ID}/photos",
    data={"published": "false", "access_token": TOKEN},
    files={"source": ("diag.jpg", image, "image/jpeg")},
    timeout=60,
)
payload = show("UNPUBLISHED_PHOTO", r)
if not r.ok or "error" in payload:
    raise SystemExit(2)

photo_id = payload.get("id")
print("DIAGNOSTIC_PHOTO_OK", photo_id)
