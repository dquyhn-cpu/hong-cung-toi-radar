import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_PROFILE = str(Path.home() / ".hong-cung-toi" / "facebook-group-profile")
DEFAULT_OUTPUT = "output"
DEFAULT_REGISTRY = Path(__file__).resolve().parent / "group_registry_normalized.json"
DEFAULT_HOLD = Path(__file__).resolve().parent / "group_hold.json"
SESSION_STATE = Path.home() / ".hong-cung-toi" / "facebook-group-session.json"


def load_saved_session(context):
    if not SESSION_STATE.exists():
        return False
    try:
        data = json.loads(SESSION_STATE.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        if cookies:
            context.add_cookies(cookies)
            print(f"SESSION_RESTORED cookies={len(cookies)}")
            return True
    except Exception as exc:
        print(f"SESSION_RESTORE_WARNING={exc}", file=sys.stderr)
    return False


def save_current_session(context):
    try:
        SESSION_STATE.parent.mkdir(parents=True, exist_ok=True)
        cookies = context.cookies()
        tmp = SESSION_STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"cookies": cookies}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SESSION_STATE)
        print(f"SESSION_SAVED cookies={len(cookies)}")
    except Exception as exc:
        print(f"SESSION_SAVE_WARNING={exc}", file=sys.stderr)


def read_text(path):
    p = Path(path)
    # Tolerate UTF-8 BOM and Windows-created UTF-16 files.
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1258", "cp1252"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            pass
    raise RuntimeError(f"Could not decode text file: {p}")


def open_group_composer(page):
    # Facebook frequently changes the visible copy around the group composer.
    # Prefer semantic/placeholder selectors first, then fall back to text.
    selectors = [
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Viết gì']",
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Bạn viết gì']",
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Write something']",
        "[contenteditable='true'][aria-placeholder*='Tạo bài viết công khai']",
        "[contenteditable='true'][aria-placeholder*='Create a public post']",
    ]
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(loc.count()):
            try:
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                el.click(timeout=2500, force=True)
                page.wait_for_timeout(900)
                # Modal composer normally creates a dialog and/or a public-post textbox.
                if page.locator("div[role='dialog']").count() or find_active_caption_editor(page) is not None:
                    return True
            except Exception:
                pass

    labels = [
        "Bạn viết gì đi",
        "Viết gì đó",
        "Tạo bài viết",
        "Write something",
        "Create post",
    ]
    for label in labels:
        try:
            loc = page.get_by_text(label, exact=False)
            for i in range(loc.count()):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                el.click(timeout=2500, force=True)
                page.wait_for_timeout(900)
                if page.locator("div[role='dialog']").count() or find_active_caption_editor(page) is not None:
                    return True
        except Exception:
            pass

    return False


def attach_image(page, image_path):
    if not image_path:
        return
    p = Path(image_path)
    if not p.exists():
        raise RuntimeError(f"Image not found: {p}")

    inputs = page.locator("input[type='file']")
    if inputs.count() == 0:
        for label in ["Ảnh/video", "Photo/video", "Ảnh", "Photo"]:
            try:
                page.get_by_text(label, exact=False).first.click(timeout=1500)
                page.wait_for_timeout(400)
                break
            except Exception:
                pass
        inputs = page.locator("input[type='file']")

    if inputs.count() == 0:
        raise RuntimeError("Could not find Facebook image upload control")

    inputs.last.set_input_files(str(p.resolve()))
    page.wait_for_timeout(1800)


def find_active_caption_editor(page):
    """
    Facebook exposes more than one editable region.
    The real modal caption editor is the visible element whose aria-placeholder
    says 'Tạo bài viết công khai...' (or English equivalent) nearest the top of
    the active composer.
    """
    selectors = [
        "[contenteditable='true'][aria-placeholder*='Tạo bài viết công khai']",
        "[contenteditable='true'][aria-placeholder*='Create a public post']",
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Tạo bài viết công khai']",
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Create a public post']",
    ]

    candidates = []
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                box = el.bounding_box()
                if not box or box["width"] < 150 or box["height"] < 15:
                    continue
                candidates.append((box["y"], el))
            except Exception:
                pass

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def enter_caption(page, message):
    editor = find_active_caption_editor(page)
    if editor is None:
        raise RuntimeError("Caption box not found")

    box = editor.bounding_box()
    if not box:
        raise RuntimeError("Caption box has no visible bounds")

    # Click the visual center of the real caption field, then inject text.
    page.mouse.click(box["x"] + min(40, box["width"] / 2), box["y"] + box["height"] / 2)
    page.wait_for_timeout(150)
    page.keyboard.insert_text(message)
    page.wait_for_timeout(650)

    # Verify against the whole page because Facebook can replace the editor node
    # while preserving the typed caption.
    body = page.locator("body").inner_text(timeout=3000)
    if message[:35] not in body:
        raise RuntimeError("Caption text was not retained in Facebook composer")

    print("CAPTION_OK")


def find_post_button(page):
    for name in ["Đăng", "Post"]:
        try:
            btn = page.get_by_role("button", name=name)
            btn.first.wait_for(state="visible", timeout=1600)
            return btn.first
        except Exception:
            pass
    return None


def login_mode(page):
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
    print("Facebook opened in the dedicated Group Poster browser.")
    print("Log in and switch this dedicated browser to Page 'Hóng Cùng Tôi' once.")
    input("Press ENTER after Facebook is ready... ")
    save_current_session(page.context)
    print("LOGIN_PROFILE_READY")
    return 0



def group_already_has_post(page, message):
    """Best-effort duplicate guard for recent group posts.

    Uses a stable headline/snippet from the package message. This is intended
    to prevent accidental reposts when a previous rollout was interrupted
    before its batch report was written.
    """
    normalized = " ".join((message or "").split())
    if not normalized:
        return False
    # Prefer the first logical line/headline; fall back to a stable prefix.
    first_line = (message or "").strip().splitlines()[0].strip()
    snippet = first_line if len(first_line) >= 20 else normalized[:70]
    try:
        body = " ".join(page.locator("body").inner_text(timeout=5000).split())
        if snippet and snippet in body:
            print(f"DUPLICATE_GUARD_HIT={snippet[:80]}")
            return True
    except Exception as exc:
        print(f"DUPLICATE_GUARD_WARNING={exc}", file=sys.stderr)
    return False


def write_batch_report(results, output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "group_batch_report.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"BATCH_REPORT_UPDATED={report} rows={len(results)}")
    return report


def detect_facebook_safety_stop(page):
    """Return a safety-stop reason only for strong Facebook safety signals.

    Do not treat the bare word "spam" anywhere in group content as a safety
    warning; public posts/comments can contain that word and caused false
    positives during the 2026-09-25 rollout.
    """
    texts = []

    # Prefer modal/alert surfaces where Facebook presents actual restrictions.
    for sel in ["div[role='dialog']", "[role='alert']", "[aria-live='assertive']"]:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible():
                    txt = " ".join(el.inner_text(timeout=2500).split()).lower()
                    if txt:
                        texts.append(txt)
        except Exception:
            pass

    # Also inspect the page for strong, specific phrases only.
    try:
        body = " ".join(page.locator("body").inner_text(timeout=5000).split()).lower()
        texts.append(body)
    except Exception:
        pass

    markers = [
        ("RATE_LIMIT", "bạn tạm thời bị hạn chế"),
        ("RATE_LIMIT", "tài khoản của bạn tạm thời bị hạn chế"),
        ("RATE_LIMIT", "we limit how often you can"),
        ("RATE_LIMIT", "you are temporarily blocked"),
        ("RATE_LIMIT", "you're temporarily blocked"),
        ("CHECKPOINT", "xác nhận danh tính"),
        ("CHECKPOINT", "confirm your identity"),
        ("CHECKPOINT", "security check required"),
        ("SPAM_WARNING", "bài viết của bạn có vẻ giống spam"),
        ("SPAM_WARNING", "bài viết này có vẻ giống spam"),
        ("SPAM_WARNING", "we removed your post because it may be spam"),
        ("SPAM_WARNING", "your post may go against our spam"),
        ("SPAM_WARNING", "we think this post may be spam"),
    ]
    for text_blob in texts:
        for code, marker in markers:
            if marker in text_blob:
                print(f"SAFETY_SIGNAL_MATCH={code}:{marker}")
                return code
    return None



def post_mode(page, group_url, message, image_path, confirm_post, output_dir):
    if not group_url.startswith("https://www.facebook.com/groups/"):
        raise RuntimeError("Invalid Facebook Group URL")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    page.goto(group_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)

    if "login" in page.url.lower():
        raise RuntimeError("Facebook session expired. Run --login again.")

    save_current_session(page.context)
    print("GROUP_OPENED")

    if group_already_has_post(page, message):
        print("SKIP_ALREADY_POSTED")
        return "SKIP_ALREADY_POSTED"

    if not open_group_composer(page):
        raise RuntimeError("Could not open Facebook Group composer")

    print("COMPOSER_OPENED")

    # Important: media first, caption second.
    attach_image(page, image_path)
    if image_path:
        print("IMAGE_ATTACHED")

    enter_caption(page, message)

    post_button = find_post_button(page)
    if post_button is None:
        raise RuntimeError("Post button not found")

    preview = out / "group_post_preview.png"
    page.screenshot(path=str(preview), full_page=False)
    print(f"PREVIEW={preview}")

    if not confirm_post:
        print("DRY_RUN_OK")
        return 0

    post_button.click()

    # Facebook often needs several seconds to close the composer and materialize
    # the newly created group post. Do not attempt comments immediately.
    try:
        page.locator("div[role='dialog']").first.wait_for(state="hidden", timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(6000)

    final = out / "group_post_after_submit.png"
    page.screenshot(path=str(final), full_page=False)

    status = "POSTED_UNVERIFIED"
    safety_stop = detect_facebook_safety_stop(page)
    if safety_stop:
        raise RuntimeError(f"SAFETY_STOP:{safety_stop}")

    try:
        body_raw = " ".join(page.locator("body").inner_text(timeout=5000).split())
        body = body_raw.lower()
        pending_markers = [
            "đang chờ phê duyệt",
            "chờ quản trị viên phê duyệt",
            "bài viết đang chờ",
            "pending approval",
            "awaiting approval",
        ]
        if any(marker in body for marker in pending_markers):
            status = "PENDING_APPROVAL"
        else:
            snippet = " ".join((message or "").split())[:70]
            if snippet and snippet in body_raw:
                status = "PUBLISHED_VISIBLE"
    except Exception:
        pass

    print(f"{status}={final}")
    return status



def add_comment(page, message, post_message=None):
    # Submit at most once. Facebook can materialize comments slowly; after Enter,
    # only poll for verification instead of re-submitting and creating duplicates.
    selectors = [
        "[contenteditable='true'][aria-label*='Bình luận dưới tên']",
        "[contenteditable='true'][aria-label*='Viết bình luận']",
        "[contenteditable='true'][aria-label*='Write a comment']",
    ]
    verify_text = " ".join(message.split())[:60]
    post_snippet = " ".join((post_message or "").split())[:55]

    def resolve_scope():
        scope = page.locator("body")
        if post_snippet:
            matches = page.get_by_text(post_snippet, exact=False)
            for j in range(matches.count()):
                try:
                    hit = matches.nth(j)
                    if not hit.is_visible():
                        continue
                    article = hit.locator("xpath=ancestor::*[@role='article'][1]")
                    if article.count():
                        return article
                except Exception:
                    pass
        return scope

    # Duplicate guard for reruns or delayed Facebook rendering.
    try:
        body = " ".join(page.locator("body").inner_text(timeout=5000).split())
        if verify_text and verify_text in body:
            print("COMMENT_ALREADY_PRESENT")
            return True
    except Exception:
        pass

    deadline = time.time() + 25
    last_error = None
    submitted = False

    while time.time() < deadline and not submitted:
        try:
            scope = resolve_scope()

            if scope.locator("[contenteditable='true']").count() == 0:
                for label in ["Bình luận", "Comment"]:
                    try:
                        btn = scope.get_by_text(label, exact=True)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1500)
                            page.wait_for_timeout(800)
                            break
                    except Exception:
                        pass

            for sel in selectors:
                loc = scope.locator(sel)
                for i in range(loc.count() - 1, -1, -1):
                    box = loc.nth(i)
                    try:
                        if not box.is_visible():
                            continue
                        box.click(force=True)
                        page.keyboard.insert_text(message)
                        page.keyboard.press("Enter")
                        submitted = True
                        print("COMMENT_SUBMITTED_ONCE")
                        break
                    except Exception as exc:
                        last_error = exc
                if submitted:
                    break
        except Exception as exc:
            last_error = exc

        if not submitted:
            page.wait_for_timeout(1200)

    if not submitted:
        raise RuntimeError(f"Could not submit comment: {last_error}")

    # Verification phase: never submit again.
    verify_deadline = time.time() + 25
    while time.time() < verify_deadline:
        try:
            body = " ".join(page.locator("body").inner_text(timeout=5000).split())
            if verify_text and verify_text in body:
                print("COMMENT_POSTED_VERIFIED")
                return True
        except Exception as exc:
            last_error = exc
        page.wait_for_timeout(1500)

    raise RuntimeError(
        f"Comment was submitted once but could not be verified within timeout: {last_error}"
    )

def comment_only_mode(page, post_url, comments, confirm_comments, output_dir):
    if not post_url.startswith("https://www.facebook.com/"):
        raise RuntimeError("Invalid Facebook post URL")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    if "login" in page.url.lower():
        raise RuntimeError("Facebook session expired. Run --login again.")

    print("POST_OPENED")
    preview = out / "comment_only_preview.png"
    page.screenshot(path=str(preview), full_page=False)
    print(f"COMMENT_PREVIEW={preview}")

    if not confirm_comments:
        print("COMMENT_DRY_RUN_OK")
        return 0

    for idx, spec in enumerate(comments, 1):
        add_comment(page, spec["message"])
        print(f"COMMENT_DONE={idx}/{len(comments)}")

    final = out / "comment_only_after.png"
    page.screenshot(path=str(final), full_page=False)
    print(f"COMMENTS_COMPLETE={final}")
    return 0


def load_package_comments(package_path):
    pkg = json.loads(Path(package_path).read_text(encoding="utf-8-sig"))
    return [
        {
            "message": x.get("message", "").strip(),
            "reply_to": x.get("reply_to"),
        }
        for x in pkg.get("comments", [])
        if x.get("message", "").strip()
    ]

def download_remote_image(url, output_dir):
    """Download a remotely hosted approved image for a package.

    Supports normal HTTPS URLs and Dropbox share links. The downloaded file is
    stored locally before Facebook upload, so the posting core still receives a
    normal filesystem path.
    """
    if not url.startswith("https://"):
        raise RuntimeError("image_url must use https")

    # Dropbox share links should force the original file download.
    parsed = urlparse(url)
    if "dropbox.com" in parsed.netloc.lower():
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        q["dl"] = "1"
        parsed = parsed._replace(query=urlencode(q))
        url = urlunparse(parsed)

    out_dir = Path(output_dir) / "remote_assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    name = f"remote_asset_{abs(hash(url))}{suffix}"
    out_path = out_dir / name

    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
    if len(data) < 1024:
        raise RuntimeError("Remote image download returned too little data")
    out_path.write_bytes(data)
    print(f"REMOTE_IMAGE_READY={out_path} bytes={len(data)}")
    return str(out_path)



def audit_groups_mode(page, registry_path, message, output_dir):
    """Recheck whether the previous story is visible or still pending in every registry group."""
    registry_file = Path(registry_path or DEFAULT_REGISTRY)
    if not registry_file.is_absolute():
        registry_file = Path(__file__).resolve().parent / registry_file
    registry = json.loads(registry_file.read_text(encoding="utf-8-sig"))
    groups = registry.get("groups", [])
    if not groups:
        raise RuntimeError("Registry has no groups")
    normalized = " ".join((message or "").split())
    if not normalized:
        raise RuntimeError("Audit message/snippet is empty")
    first_line = (message or "").strip().splitlines()[0].strip()
    snippet = first_line if len(first_line) >= 20 else normalized[:70]
    results = []
    pending_markers = [
        "đang chờ phê duyệt",
        "chờ quản trị viên phê duyệt",
        "bài viết đang chờ",
        "pending approval",
        "awaiting approval",
    ]
    for idx, g in enumerate(groups, 1):
        url = str(g.get("url") or "").strip()
        gid = str(g.get("id") or "")
        if not url:
            continue
        print(f"AUDIT_GROUP={idx}/{len(groups)} id={gid}")
        row = {"id": gid, "group_url": url, "status": "ERROR"}
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            if "login" in page.url.lower():
                row["status"] = "SESSION_EXPIRED"
            else:
                body_raw = " ".join(page.locator("body").inner_text(timeout=7000).split())
                body = body_raw.lower()
                if snippet and snippet in body_raw:
                    row["status"] = "ACTIVE"
                elif any(x in body for x in pending_markers):
                    row["status"] = "PENDING"
                else:
                    row["status"] = "NOT_FOUND"
        except Exception as exc:
            row["error"] = str(exc)
        results.append(row)
        print(f"AUDIT_RESULT={gid}:{row['status']}")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "group_approval_audit.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    active = sum(1 for r in results if r["status"] == "ACTIVE")
    pending = sum(1 for r in results if r["status"] == "PENDING")
    unknown = len(results) - active - pending
    print(f"AUDIT_DONE total={len(results)} active={active} pending={pending} other={unknown}")
    print(f"AUDIT_REPORT={report}")
    return 0


def run_package(page, package_path, confirm_post, output_dir):
    pkg_path = Path(package_path)
    pkg = json.loads(pkg_path.read_text(encoding="utf-8-sig"))
    group_urls = pkg.get("group_urls") or ([pkg["group_url"]] if pkg.get("group_url") else [])

    # Production mode: package may request registry targets instead of embedding
    # URLs. Only explicitly enabled registry groups are used unless the package
    # asks for a controlled rollout of the first N resolved groups.
    if not group_urls and pkg.get("use_registry"):
        registry_path = Path(pkg.get("registry_path") or DEFAULT_REGISTRY)
        if not registry_path.is_absolute():
            registry_path = Path(__file__).resolve().parent / registry_path
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        reg_groups = registry.get("groups", [])

        rollout_limit = int(pkg.get("rollout_limit") or 0)
        include_ids = set(pkg.get("include_group_ids") or [])
        exclude_ids = set(pkg.get("exclude_group_ids") or [])

        selected = []
        for g in reg_groups:
            gid = str(g.get("id") or "")
            if gid in exclude_ids:
                continue
            if include_ids and gid not in include_ids:
                continue

            if include_ids:
                eligible = True
            elif rollout_limit > 0:
                eligible = True
            else:
                eligible = bool(g.get("enabled"))

            if not eligible:
                continue

            url = str(g.get("url") or "").strip()
            if not url:
                continue
            selected.append(url)
            if rollout_limit > 0 and len(selected) >= rollout_limit:
                break

        group_urls = selected

    if not group_urls:
        raise RuntimeError("Package has no target groups")

    # Global hold list: groups with a previous PENDING_APPROVAL result are
    # temporarily excluded from later story rollouts until explicitly cleared.
    hold_path = Path(pkg.get("hold_path") or DEFAULT_HOLD)
    if not hold_path.is_absolute():
        hold_path = Path(__file__).resolve().parent / hold_path
    held_urls = set()
    if hold_path.exists():
        try:
            hold_data = json.loads(hold_path.read_text(encoding="utf-8-sig"))
            held_urls = {str(x).strip() for x in (hold_data.get("groups") or []) if str(x).strip()}
        except Exception as exc:
            print(f"HOLD_LIST_WARNING={exc}", file=sys.stderr)
    if held_urls:
        before = len(group_urls)
        group_urls = [u for u in group_urls if u not in held_urls]
        print(f"HOLD_FILTER excluded={before-len(group_urls)} remaining={len(group_urls)}")
    if not group_urls:
        raise RuntimeError("All target groups are currently on hold")

    message = pkg.get("message", "").strip()
    if not message:
        raise RuntimeError("Package message is empty")

    image_path = pkg.get("image_path")
    image_url = str(pkg.get("image_url") or "").strip()

    if image_url:
        image_path = download_remote_image(image_url, output_dir)
    elif image_path and not Path(image_path).exists():
        # Packages live in group_poster/packages; repo assets live one directory up.
        alt = Path("..") / image_path
        if alt.exists():
            image_path = str(alt)

    comments = [
        {
            "message": x.get("message", "").strip(),
            "reply_to": x.get("reply_to"),
        }
        for x in pkg.get("comments", [])
        if x.get("message", "").strip()
    ]
    results = []

    for idx, group_url in enumerate(group_urls, 1):
        print(f"GROUP_BATCH={idx}/{len(group_urls)}")
        try:
            rc = post_mode(page, group_url, message, image_path, confirm_post, output_dir)
            status = "PREVIEW_OK" if not confirm_post else (rc if isinstance(rc, str) else "POST_CLICKED")
            if confirm_post and comments:
                # Group rollout policy: publish the main post only.
                # Automated comments are intentionally disabled to reduce
                # Facebook rate-limit risk. Source links/details must live in
                # the main post package instead.
                print(f"GROUP_COMMENTS_DISABLED count={len(comments)}")
            results.append({"group_url": group_url, "status": status})
            write_batch_report(results, output_dir)
        except Exception as exc:
            err = str(exc)
            safety_stop = err.startswith("SAFETY_STOP:")
            expected_skip = any(x in err for x in [
                "Could not open Facebook Group composer",
                "Facebook session expired",
                "Invalid Facebook Group URL",
            ])
            status = "SAFETY_STOP" if safety_stop else ("SKIPPED" if expected_skip else "ERROR")
            results.append({"group_url": group_url, "status": status, "error": err})
            write_batch_report(results, output_dir)
            print(f"GROUP_{status}={group_url} :: {err}", file=sys.stderr)
            if safety_stop:
                print("BATCH_HALTED_FOR_SAFETY", file=sys.stderr)
                break

        # Pace group submissions to avoid accidental burst-posting.
        delay_sec = int(pkg.get("inter_group_delay_seconds") or 0)
        if idx < len(group_urls) and delay_sec > 0:
            print(f"GROUP_DELAY={delay_sec}s")
            page.wait_for_timeout(delay_sec * 1000)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "group_batch_report.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"BATCH_REPORT={report}")

    failures = [r for r in results if r["status"] == "ERROR"]
    skipped = [r for r in results if r["status"] == "SKIPPED"]
    posted = [r for r in results if r["status"] in {"POST_CLICKED","POSTED_UNVERIFIED","PUBLISHED_VISIBLE","POST_OK_COMMENT_WARNING","PREVIEW_OK","PENDING_APPROVAL","SKIP_ALREADY_POSTED"}]
    print(f"BATCH_DONE total={len(results)} posted_or_preview={len(posted)} skipped={len(skipped)} errors={len(failures)}")
    return 1 if failures else 0

def main():
    ap = argparse.ArgumentParser(description="Hóng Cùng Tôi - Facebook Group Poster")
    ap.add_argument("--profile-dir", default=DEFAULT_PROFILE)
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--group-url")
    ap.add_argument("--message")
    ap.add_argument("--message-file")
    ap.add_argument("--image")
    ap.add_argument("--confirm-post", action="store_true")
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    ap.add_argument("--page-name", default="Hóng Cùng Tôi")
    ap.add_argument("--package", help="JSON package with message, image, comments and group_url/group_urls")
    ap.add_argument("--audit-groups", action="store_true", help="Recheck previous story visibility/pending status across registry groups; never posts")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Registry JSON for --audit-groups")
    ap.add_argument("--audit-message-file", help="Previous post text used to identify the story during --audit-groups")
    ap.add_argument("--comment-only-url", help="Existing Facebook post URL; never creates a new post")
    ap.add_argument("--confirm-comments", action="store_true", help="Actually submit comments in comment-only mode")
    args = ap.parse_args()

    if not args.login and not args.group_url and not args.package and not args.comment_only_url and not args.audit_groups:
        ap.error("Use --login, --package, --comment-only-url, --audit-groups, or provide --group-url")

    message = args.message or (read_text(args.message_file) if args.message_file else "")
    if not args.login and not args.package and not args.comment_only_url and not message:
        ap.error("Provide --message or --message-file")
    if args.comment_only_url and not args.package:
        ap.error("--comment-only-url requires --package for comment text")

    profile = Path(args.profile_dir)
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            viewport={"width": 1400, "height": 1000},
            args=["--disable-notifications"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            if args.login:
                return login_mode(page)
            if args.audit_groups:
                audit_message = read_text(args.audit_message_file) if args.audit_message_file else message
                return audit_groups_mode(page, args.registry, audit_message, args.output_dir)
            if args.comment_only_url:
                return comment_only_mode(
                    page,
                    args.comment_only_url,
                    load_package_comments(args.package),
                    args.confirm_comments,
                    args.output_dir,
                )
            if args.package:
                return run_package(page, args.package, args.confirm_post, args.output_dir)
            return post_mode(
                page,
                args.group_url,
                message,
                args.image,
                args.confirm_post,
                args.output_dir,
            )
        except PlaywrightTimeoutError as exc:
            print(f"TIMEOUT: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            try:
                out = Path(args.output_dir)
                out.mkdir(parents=True, exist_ok=True)
                err = out / "group_post_error.png"
                page.screenshot(path=str(err), full_page=False)
                print(f"ERROR_SCREENSHOT={err}", file=sys.stderr)
            except Exception:
                pass
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
