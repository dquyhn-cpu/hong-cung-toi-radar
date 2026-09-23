import os
import sys
import requests

GRAPH_VERSION = os.getenv("FB_GRAPH_VERSION", "v26.0")
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
PAGE_ID = os.getenv("FB_PAGE_ID", "").strip()
POST_ID = os.getenv("FB_POST_ID", "").strip()
MESSAGE_CONTAINS = os.getenv("FB_MESSAGE_CONTAINS", "").strip()

session = requests.Session()


def api_get(path, params=None):
    p = dict(params or {})
    p["access_token"] = TOKEN
    r = session.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}",
        params=p,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def resolve_post_id():
    if POST_ID:
        return POST_ID

    if not PAGE_ID or not MESSAGE_CONTAINS:
        raise SystemExit(
            "Set FB_POST_ID, or set both FB_PAGE_ID and FB_MESSAGE_CONTAINS"
        )

    payload = api_get(
        f"/{PAGE_ID}/feed",
        {"fields": "id,message,created_time", "limit": "25"},
    )
    matches = []
    needle = MESSAGE_CONTAINS.casefold()
    for post in payload.get("data", []):
        message = str(post.get("message") or "")
        if needle in message.casefold():
            matches.append(post)

    if not matches:
        print("DELETE_SKIP_NO_MATCH", MESSAGE_CONTAINS)
        raise SystemExit(0)

    matches.sort(key=lambda p: p.get("created_time") or "", reverse=True)
    post = matches[0]
    print("DELETE_MATCH", post.get("id"), post.get("created_time"), (post.get("message") or "")[:120])
    return post["id"]


post_id = resolve_post_id()
r = session.delete(
    f"https://graph.facebook.com/{GRAPH_VERSION}/{post_id}",
    data={"access_token": TOKEN},
    timeout=30,
)
print("STATUS", r.status_code)
print("BODY", r.text)
r.raise_for_status()
payload = r.json()
if payload.get("success") is not True:
    raise SystemExit("Delete did not return success=true: " + str(payload))
print("DELETE_OK", post_id)
