import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

GRAPH_VERSION = os.getenv("FB_GRAPH_VERSION", "v26.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_QUEUE = "facebook_publish_queue.json"
DEFAULT_STATE = "facebook_publish_state.json"


class FacebookAPIError(RuntimeError):
    def __init__(self, message, *, status=None, code=None, subcode=None, payload=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.subcode = subcode
        self.payload = payload or {}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json_atomic(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


def stable_hash(text):
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()[:20]


class FacebookPagePublisher:
    def __init__(self, page_id, access_token, timeout=30, max_attempts=4):
        self.page_id = str(page_id)
        self.access_token = access_token
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.session = requests.Session()

    def _request(self, method, path, *, params=None, data=None):
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"
        params = dict(params or {})
        data = dict(data or {})
        if method.upper() == "GET":
            params["access_token"] = self.access_token
        else:
            data["access_token"] = self.access_token

        last_exc = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = self.session.request(method, url, params=params, data=data, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    raise
                time.sleep(min(2 ** (attempt - 1), 8))
                continue

            try:
                payload = r.json()
            except ValueError:
                payload = {"raw": r.text}

            if r.ok and "error" not in payload:
                return payload

            err = payload.get("error", {}) if isinstance(payload, dict) else {}
            code = err.get("code")
            subcode = err.get("error_subcode")
            message = err.get("message") or f"HTTP {r.status_code}"

            retryable = r.status_code in {429, 500, 502, 503, 504} or code in {1, 2, 4, 17, 32, 613}
            if retryable and attempt < self.max_attempts:
                retry_after = r.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2 ** (attempt - 1), 8)
                time.sleep(delay)
                continue

            raise FacebookAPIError(message, status=r.status_code, code=code, subcode=subcode, payload=payload)

        if last_exc:
            raise last_exc
        raise RuntimeError("Facebook request failed")

    def verify_identity(self):
        me = self._request("GET", "/me", params={"fields": "id,name"})
        if str(me.get("id")) != self.page_id:
            raise RuntimeError(
                f"Token identity mismatch: expected Page {self.page_id}, got {me.get('id')} ({me.get('name')})"
            )
        return me

    def recent_posts(self, limit=25):
        payload = self._request(
            "GET",
            f"/{self.page_id}/feed",
            params={"fields": "id,message,created_time", "limit": str(limit)},
        )
        return payload.get("data", [])

    def find_existing_post_by_message(self, message, limit=25):
        target = (message or "").strip()
        if not target:
            return None
        for post in self.recent_posts(limit=limit):
            if (post.get("message") or "").strip() == target:
                return post.get("id")
        return None

    def create_post(self, message):
        payload = self._request("POST", f"/{self.page_id}/feed", data={"message": message})
        post_id = payload.get("id")
        if not post_id:
            raise RuntimeError(f"Facebook did not return post id: {payload}")
        return post_id

    def existing_comments(self, post_id, limit=100):
        payload = self._request(
            "GET",
            f"/{post_id}/comments",
            params={"fields": "id,message,from", "limit": str(limit)},
        )
        return payload.get("data", [])

    def comment_exists(self, post_id, message):
        target = (message or "").strip()
        if not target:
            return True
        for comment in self.existing_comments(post_id):
            if (comment.get("message") or "").strip() == target:
                return comment.get("id") or True
        return False

    def create_comment(self, post_id, message):
        payload = self._request("POST", f"/{post_id}/comments", data={"message": message})
        comment_id = payload.get("id")
        if not comment_id:
            raise RuntimeError(f"Facebook did not return comment id: {payload}")
        return comment_id


def validate_queue(queue):
    if not isinstance(queue, dict) or not isinstance(queue.get("items"), list):
        raise ValueError("Queue must be an object with an items[] array")

    seen_ids = set()
    for idx, item in enumerate(queue["items"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item #{idx} must be an object")
        publish_id = str(item.get("publish_id") or "").strip()
        message = str(item.get("message") or "").strip()
        if not publish_id:
            raise ValueError(f"Item #{idx} is missing publish_id")
        if publish_id in seen_ids:
            raise ValueError(f"Duplicate publish_id: {publish_id}")
        seen_ids.add(publish_id)
        if not message:
            raise ValueError(f"Item {publish_id} has empty message")
        comments = item.get("comments", [])
        if comments is None:
            item["comments"] = []
        elif not isinstance(comments, list) or any(not isinstance(x, str) for x in comments):
            raise ValueError(f"Item {publish_id} comments must be a string array")


def ensure_state_shape(state):
    if not isinstance(state, dict):
        state = {}
    state.setdefault("version", "1")
    state.setdefault("updated_at", utc_now())
    state.setdefault("items", {})
    return state


def process_item(publisher, item, state, *, dry_run=False, comment_delay=1.0):
    publish_id = str(item["publish_id"])
    message = item["message"].strip()
    comments = [c.strip() for c in item.get("comments", []) if c.strip()]

    record = state["items"].setdefault(
        publish_id,
        {
            "event_id": item.get("event_id"),
            "message_hash": stable_hash(message),
            "post_id": None,
            "post_status": "PENDING",
            "comments": {},
            "created_at": utc_now(),
            "updated_at": utc_now(),
        },
    )

    if item.get("enabled", True) is False:
        record["post_status"] = "DISABLED"
        record["updated_at"] = utc_now()
        return {"publish_id": publish_id, "status": "DISABLED"}

    if dry_run:
        return {
            "publish_id": publish_id,
            "status": "DRY_RUN",
            "message_preview": message[:120],
            "comments": len(comments),
        }

    post_id = record.get("post_id")
    if not post_id:
        post_id = publisher.find_existing_post_by_message(message)
        if post_id:
            record["post_id"] = post_id
            record["post_status"] = "FOUND_EXISTING"
        else:
            post_id = publisher.create_post(message)
            record["post_id"] = post_id
            record["post_status"] = "POSTED"
        record["updated_at"] = utc_now()

    comment_failures = []
    for index, comment in enumerate(comments, start=1):
        key = str(index)
        cstate = record["comments"].setdefault(
            key,
            {
                "message_hash": stable_hash(comment),
                "comment_id": None,
                "status": "PENDING",
                "updated_at": utc_now(),
            },
        )

        if cstate.get("comment_id"):
            continue

        try:
            existing_id = publisher.comment_exists(post_id, comment)
            if existing_id:
                cstate["comment_id"] = existing_id if isinstance(existing_id, str) else None
                cstate["status"] = "FOUND_EXISTING"
            else:
                comment_id = publisher.create_comment(post_id, comment)
                cstate["comment_id"] = comment_id
                cstate["status"] = "POSTED"
                if comment_delay:
                    time.sleep(comment_delay)
        except Exception as exc:
            cstate["status"] = "FAILED"
            cstate["error"] = str(exc)
            comment_failures.append({"index": index, "error": str(exc)})
        finally:
            cstate["updated_at"] = utc_now()
            record["updated_at"] = utc_now()

    return {
        "publish_id": publish_id,
        "status": "POSTED_WITH_COMMENT_ERRORS" if comment_failures else "OK",
        "post_id": post_id,
        "comment_failures": comment_failures,
    }


def main():
    parser = argparse.ArgumentParser(description="Publish approved Hong Cung Toi posts to a Facebook Page")
    parser.add_argument("--queue", default=DEFAULT_QUEUE)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict-comments", action="store_true")
    parser.add_argument("--comment-delay", type=float, default=1.0)
    args = parser.parse_args()

    page_id = os.getenv("FB_PAGE_ID")
    token = os.getenv("FB_PAGE_ACCESS_TOKEN")

    if not args.dry_run and (not page_id or not token):
        print("ERROR: FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN are required", file=sys.stderr)
        return 2

    queue = load_json(args.queue, None)
    if queue is None:
        print(f"ERROR: queue file not found: {args.queue}", file=sys.stderr)
        return 2
    validate_queue(queue)

    state = ensure_state_shape(load_json(args.state, {}))
    publisher = None

    if not args.dry_run:
        publisher = FacebookPagePublisher(page_id, token)
        identity = publisher.verify_identity()
        print(f"PAGE_TOKEN_OK: {identity.get('name')} ({identity.get('id')})")

    results = []
    post_failures = 0
    comment_failures = 0

    for item in queue["items"]:
        try:
            result = process_item(
                publisher,
                item,
                state,
                dry_run=args.dry_run,
                comment_delay=args.comment_delay,
            )
            results.append(result)
            comment_failures += len(result.get("comment_failures", []))
            print(json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            publish_id = item.get("publish_id", "UNKNOWN")
            state["items"].setdefault(str(publish_id), {})["fatal_error"] = str(exc)
            state["items"][str(publish_id)]["updated_at"] = utc_now()
            post_failures += 1
            print(json.dumps({"publish_id": publish_id, "status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        finally:
            state["updated_at"] = utc_now()
            save_json_atomic(args.state, state)

    print(json.dumps({
        "summary": {
            "items": len(queue["items"]),
            "post_failures": post_failures,
            "comment_failures": comment_failures,
            "dry_run": args.dry_run,
        }
    }, ensure_ascii=False))

    if post_failures:
        return 1
    if args.strict_comments and comment_failures:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
