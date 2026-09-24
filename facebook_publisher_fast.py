import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image

GRAPH_VERSION = os.getenv("FB_GRAPH_VERSION", "v26.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def load_queue(path):
    with open(path, "r", encoding="utf-8") as f:
        q = json.load(f)
    items = [x for x in q.get("items", []) if x.get("enabled", True)]
    if len(items) != 1:
        raise RuntimeError(f"Fast publisher requires exactly 1 enabled item, got {len(items)}")
    item = items[0]
    if str(item.get("lifecycle_status", "")).upper() != "APPROVED":
        raise RuntimeError("Item must be APPROVED before fast publish")
    if not item.get("message"):
        raise RuntimeError("Approved item has no message")
    return item


def verify_exact_asset(item):
    image_url = str(item.get("image_url") or "").strip()
    image_path = str(item.get("image_path") or "").strip()

    if image_url:
        if not image_url.startswith("https://"):
            raise RuntimeError("Approved image_url must use https")
        r = requests.get(image_url, timeout=90)
        r.raise_for_status()
        raw = r.content
        if len(raw) < 1024:
            raise RuntimeError("Remote approved image download returned too little data")
        suffix = ".png" if (r.headers.get("content-type") or "").lower().startswith("image/png") else ".jpg"
        p = Path("/tmp") / f"approved_remote_asset{suffix}"
        p.write_bytes(raw)
    else:
        p = Path(image_path)
        if not p.exists():
            raise RuntimeError(f"Approved image missing: {p}")
        raw = p.read_bytes()

    with Image.open(p) as im:
        im.verify()
    with Image.open(p) as im:
        im.load()
        w, h = im.size
        if w < 900 or h < 900:
            raise RuntimeError(f"Approved master too small: {w}x{h}")

    sha = hashlib.sha256(raw).hexdigest()
    expected = str(item.get("asset_sha256") or "").strip()
    if expected and sha != expected:
        raise RuntimeError("Approved asset hash mismatch; refusing to publish")

    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return p, raw, mime, sha


class Publisher:
    def __init__(self, page_id, token):
        self.page_id = str(page_id)
        self.token = token
        self.s = requests.Session()

    def get(self, path, params=None):
        p = dict(params or {})
        p["access_token"] = self.token
        r = self.s.get(f"{GRAPH_BASE}/{path.lstrip('/')}", params=p, timeout=20)
        r.raise_for_status()
        payload = r.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload

    def post(self, path, data=None, files=None, timeout=60):
        d = dict(data or {})
        d["access_token"] = self.token
        r = self.s.post(f"{GRAPH_BASE}/{path.lstrip('/')}", data=d, files=files, timeout=timeout)
        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text}
        if not r.ok or "error" in payload:
            raise RuntimeError(f"Facebook API error {r.status_code}: {payload}")
        return payload

    def identity(self):
        me = self.get("/me", {"fields": "id,name"})
        if str(me.get("id")) != self.page_id:
            raise RuntimeError(f"Page token mismatch: {me}")
        return me

    def find_same_message(self, message):
        feed = self.get(f"/{self.page_id}/feed", {"fields": "id,message", "limit": "15"})
        for post in feed.get("data", []):
            if (post.get("message") or "").strip() == message.strip():
                return post.get("id")
        return None

    def publish_exact_image(self, message, path, raw, mime):
        media = self.post(
            f"/{self.page_id}/photos",
            data={"published": "false"},
            files={"source": (path.name, raw, mime)},
            timeout=90,
        )
        media_id = media.get("id")
        if not media_id:
            raise RuntimeError(f"No media id returned: {media}")

        feed = self.post(
            f"/{self.page_id}/feed",
            data={
                "message": message,
                "attached_media[0]": json.dumps({"media_fbid": media_id}),
            },
            timeout=45,
        )
        post_id = feed.get("id")
        if not post_id:
            raise RuntimeError(f"No post id returned: {feed}")
        return post_id

    def comment(self, parent_id, message):
        return self.post(f"/{parent_id}/comments", data={"message": message}, timeout=30).get("id")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="facebook_publish_queue.json")
    args = ap.parse_args()

    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_id or not token:
        raise RuntimeError("Missing FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN")

    item = load_queue(args.queue)
    path, raw, mime, sha = verify_exact_asset(item)

    pub = Publisher(page_id, token)
    me = pub.identity()

    existing = pub.find_same_message(item["message"])
    if existing:
        print(json.dumps({
            "status": "FOUND_EXISTING",
            "post_id": existing,
            "asset_sha256": sha,
            "page": me.get("name"),
        }, ensure_ascii=False))
        return 0

    post_id = pub.publish_exact_image(item["message"], path, raw, mime)

    comment_ids = {}
    failures = []
    for i, raw_comment in enumerate(item.get("comments", []), start=1):
        if isinstance(raw_comment, str):
            msg = raw_comment.strip()
            reply_to = None
        else:
            msg = str(raw_comment.get("message") or "").strip()
            reply_to = raw_comment.get("reply_to")
        if not msg:
            continue
        try:
            parent = comment_ids.get(reply_to) if reply_to else post_id
            if not parent:
                raise RuntimeError(f"Missing parent for comment #{i}")
            cid = pub.comment(parent, msg)
            comment_ids[i] = cid
            time.sleep(0.25)
        except Exception as exc:
            failures.append({"index": i, "error": str(exc)})

    print(json.dumps({
        "status": "OK" if not failures else "POSTED_WITH_COMMENT_ERRORS",
        "post_id": post_id,
        "asset_sha256": sha,
        "page": me.get("name"),
        "comments_posted": len(comment_ids),
        "comment_failures": failures,
    }, ensure_ascii=False))
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
