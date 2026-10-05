import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

GROUP_POSTER_MUTEX = "Global\\HongCungToiGroupPoster"
_SINGLE_INSTANCE_HANDLE = None

def acquire_single_instance(wait_seconds=90):
    global _SINGLE_INSTANCE_HANDLE
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, GROUP_POSTER_MUTEX)
        if not handle:
            raise RuntimeError("Could not create Group Poster mutex")
        ERROR_ALREADY_EXISTS = 183
        WAIT_OBJECT_0 = 0
        WAIT_ABANDONED = 0x00000080
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            # A previous poster can survive briefly after a Scheduled Task
            # restart. Wait for that mutex instead of failing the new queue item
            # immediately. If the old process has actually died, Windows returns
            # WAIT_ABANDONED and we can safely continue.
            rc = kernel32.WaitForSingleObject(handle, int(wait_seconds * 1000))
            if rc not in (WAIT_OBJECT_0, WAIT_ABANDONED):
                kernel32.CloseHandle(handle)
                return False
            print(f"GROUP_POSTER_MUTEX_RECOVERED wait_seconds={wait_seconds}")
        _SINGLE_INSTANCE_HANDLE = handle
        return True

    lock_path = Path.home() / ".hong-cung-toi" / "group_poster.instance.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        _SINGLE_INSTANCE_HANDLE = (fd, lock_path)
        return True
    except FileExistsError:
        return False


DEFAULT_PROFILE = str(Path.home() / ".hong-cung-toi" / "facebook-group-profile-v3")
DEFAULT_OUTPUT = "output"
DEFAULT_REGISTRY = Path(__file__).resolve().parent / "group_registry_normalized.json"
DEFAULT_HOLD = Path(__file__).resolve().parent / "group_hold.json"
DEFAULT_AUDIT_REGISTRY = Path(__file__).resolve().parent / "group_registry_52.json"
SESSION_STATE = Path.home() / ".hong-cung-toi" / "facebook-group-session.json"
LOCAL_ASSET_DIR = Path(__file__).resolve().parent / "temp_assets"
PUBLISH_LEDGER = Path.home() / ".hong-cung-toi" / "group_publish_ledger.json"


def _group_key(url):
    return str(url or "").strip().rstrip("/")


def load_publish_ledger():
    if not PUBLISH_LEDGER.exists():
        return {}
    try:
        data = json.loads(PUBLISH_LEDGER.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"LEDGER_READ_WARNING={exc}", file=sys.stderr)
        return {}


def save_publish_ledger(data):
    PUBLISH_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = PUBLISH_LEDGER.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PUBLISH_LEDGER)


def ledger_has_submission(ledger, publish_id, group_url):
    return _group_key(group_url) in set(ledger.get(str(publish_id), []))


def ledger_mark_submission(ledger, publish_id, group_url):
    key = str(publish_id)
    rows = set(ledger.get(key, []))
    rows.add(_group_key(group_url))
    ledger[key] = sorted(rows)
    save_publish_ledger(ledger)


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


def open_group_composer(page, ready_timeout_ms=25000):
    """Open the group composer as soon as any usable trigger is visible.

    Facebook group pages can visually render the composer before the editable
    textbox exists. Prefer the visible feed trigger/button/text and keep polling
    the current page instead of reloading it prematurely.
    """
    css_candidates = [
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Viết gì']",
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Bạn viết gì']",
        "[role='textbox'][contenteditable='true'][aria-placeholder*='Write something']",
        "[contenteditable='true'][aria-placeholder*='Tạo bài viết công khai']",
        "[contenteditable='true'][aria-placeholder*='Create a public post']",
        "[role='button'][aria-label*='Tạo bài viết']",
        "[role='button'][aria-label*='Create post']",
    ]
    text_candidates = [
        "Bạn viết gì đi",
        "Bạn viết gì",
        "Viết gì đó",
        "Tạo bài viết",
        "Write something",
        "Create post",
    ]

    deadline = time.time() + (ready_timeout_ms / 1000.0)
    next_scroll = time.time() + 3.0
    while time.time() < deadline:
        # Fast CSS path.
        for sel in css_candidates:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 4)):
                    el = loc.nth(i)
                    if not el.is_visible():
                        continue
                    el.click(timeout=700, force=True)
                    open_deadline = time.time() + 1.8
                    while time.time() < open_deadline:
                        try:
                            if page.locator("div[role='dialog']:visible").count() or find_active_caption_editor(page) is not None:
                                return True
                        except Exception:
                            pass
                        page.wait_for_timeout(100)
            except Exception:
                pass

        # Text fallback on every poll, because Facebook often renders the group
        # composer as a clickable text block rather than an editable textbox.
        for label in text_candidates:
            try:
                loc = page.get_by_text(label, exact=False)
                for i in range(min(loc.count(), 4)):
                    el = loc.nth(i)
                    if not el.is_visible():
                        continue
                    el.click(timeout=700, force=True)
                    open_deadline = time.time() + 1.8
                    while time.time() < open_deadline:
                        try:
                            if page.locator("div[role='dialog']:visible").count() or find_active_caption_editor(page) is not None:
                                return True
                        except Exception:
                            pass
                        page.wait_for_timeout(100)
            except Exception:
                pass

        # Nudge once if the composer is just below the fold; do not reload.
        if time.time() >= next_scroll:
            try:
                page.mouse.wheel(0, 250)
            except Exception:
                pass
            next_scroll = time.time() + 3.0

        page.wait_for_timeout(150)

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
    # Do not assume the upload is ready after a fixed sleep. Facebook may take
    # much longer on a busy machine; wait until the composer exposes an enabled
    # Post button, which is the practical signal that media processing is ready.
    upload_deadline = time.time() + 25
    while time.time() < upload_deadline:
        if find_post_button(page) is not None:
            print("IMAGE_UPLOAD_READY")
            return
        page.wait_for_timeout(350)
    raise RuntimeError("UI/COMPOSER_ERROR: image upload did not become ready within 25 seconds")


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
        # Fallback for Facebook variants that omit aria-placeholder.
        try:
            dialogs = page.locator("div[role='dialog']")
            for d_i in range(dialogs.count() - 1, -1, -1):
                d = dialogs.nth(d_i)
                if not d.is_visible():
                    continue
                loc = d.locator("[role='textbox'][contenteditable='true'], [contenteditable='true']")
                for i in range(loc.count()):
                    el = loc.nth(i)
                    try:
                        if not el.is_visible():
                            continue
                        box = el.bounding_box()
                        if box and box["width"] >= 180 and box["height"] >= 18:
                            candidates.append((box["y"], el))
                    except Exception:
                        pass
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
    page.wait_for_timeout(250)

    # Verify against the whole page because Facebook can replace the editor node
    # while preserving the typed caption.
    body = page.locator("body").inner_text(timeout=3000)
    if message[:35] not in body:
        raise RuntimeError("Caption text was not retained in Facebook composer")

    print("CAPTION_OK")


def find_post_button(page):
    scopes = []
    try:
        dialogs = page.locator("div[role='dialog']")
        for i in range(dialogs.count() - 1, -1, -1):
            d = dialogs.nth(i)
            if d.is_visible():
                scopes.append(d)
    except Exception:
        pass
    scopes.append(page)

    for scope in scopes:
        for name in ["Đăng", "Post"]:
            try:
                btn = scope.get_by_role("button", name=name, exact=True)
                for i in range(btn.count()):
                    el = btn.nth(i)
                    if el.is_visible() and el.is_enabled():
                        return el
            except Exception:
                pass

    # Fallback for button text nested inside Facebook's role=button wrappers.
    for scope in scopes:
        try:
            buttons = scope.locator("[role='button']")
            for i in range(buttons.count()):
                el = buttons.nth(i)
                if not el.is_visible():
                    continue
                txt = " ".join((el.inner_text(timeout=1000) or "").split()).strip().lower()
                if txt in {"đăng", "post"}:
                    return el
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



def ensure_posting_identity(page, page_name="Hóng Cùng Tôi"):
    """Switch the first group composer to the requested Page, then verify it."""
    target = page_name.strip()
    target_lower = target.lower()

    def composer_has_target():
        try:
            dialogs = page.locator("div[role='dialog']")
            for i in range(dialogs.count()):
                d = dialogs.nth(i)
                if not d.is_visible():
                    continue
                txt = " ".join(d.inner_text(timeout=3000).split())
                if target_lower in txt.lower():
                    return True
        except Exception:
            pass
        return False

    if composer_has_target():
        print(f"IDENTITY_OK={target}")
        return True

    # Explicitly open Facebook's profile/Page selector when the composer starts
    # as the personal profile. Once selected, Facebook normally keeps this
    # identity for subsequent group composers in the same browser session.
    trigger_texts = [
        "Chọn trang cá nhân hoặc Trang",
        "Chọn trang cá nhân hoặc trang",
        "Chọn Trang",
        "Đang tương tác dưới tên",
        "Tương tác dưới tên",
        "Đăng dưới tên",
        "Post as",
        "Posting as",
        "Interact as",
    ]
    clicked = False
    for label in trigger_texts:
        try:
            loc = page.get_by_text(label, exact=False)
            for i in range(loc.count()):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                el.click(timeout=2500, force=True)
                page.wait_for_timeout(1000)
                clicked = True
                break
            if clicked:
                break
        except Exception:
            pass

    # Fallback: click visible buttons/controls in the active composer whose
    # accessible text suggests an identity/profile selector.
    if not clicked:
        try:
            dialog = page.locator("div[role='dialog']").last
            controls = dialog.locator("[role='button']")
            for i in range(controls.count()):
                el = controls.nth(i)
                if not el.is_visible():
                    continue
                label = " ".join([
                    el.get_attribute("aria-label") or "",
                    el.get_attribute("title") or "",
                    el.inner_text(timeout=1000) or "",
                ]).lower()
                if any(k in label for k in ["trang cá nhân", "trang", "profile", "page", "tương tác", "đăng dưới"]):
                    el.click(timeout=2200, force=True)
                    page.wait_for_timeout(1000)
                    clicked = True
                    break
        except Exception:
            pass

    if clicked:
        try:
            choices = page.get_by_text(target, exact=False)
            for i in range(choices.count()):
                el = choices.nth(i)
                if not el.is_visible():
                    continue
                el.click(timeout=3000, force=True)
                page.wait_for_timeout(1400)
                break
        except Exception:
            pass

    if composer_has_target():
        print(f"IDENTITY_SWITCHED={target}")
        return True

    # Fail closed only after actively attempting the Page switch.
    raise RuntimeError(f"IDENTITY_GUARD: could not switch composer to Page '{target}'")


def post_mode(page, group_url, message, image_path, confirm_post, output_dir, duplicate_scan=True):
    if not group_url.startswith("https://www.facebook.com/groups/"):
        raise RuntimeError("Invalid Facebook Group URL")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Navigate only until the main document is committed. Waiting for
    # DOMContentLoaded on Facebook can add 20-30 seconds even though the group
    # page is already visibly usable.
    nav_error = None
    for attempt in range(1, 3):
        try:
            page.goto(group_url, wait_until="commit", timeout=20000)
            nav_error = None
            break
        except Exception as exc:
            nav_error = exc
            print(f"NAV_RETRY attempt={attempt} error={exc}", file=sys.stderr)
            if attempt < 2:
                page.wait_for_timeout(500)
    if nav_error is not None:
        raise RuntimeError(f"Group navigation failed after retry: {nav_error}")

    if "login" in page.url.lower():
        raise RuntimeError("Facebook session expired. Run --login again.")

    print("GROUP_NAV_COMMITTED")

    # Package batches already have a persistent story+group ledger, so scanning
    # the entire group DOM for duplicate text before every post is redundant and
    # expensive. Keep it only for standalone/manual post_mode calls.
    if duplicate_scan and group_already_has_post(page, message):
        print("SKIP_ALREADY_POSTED")
        return "SKIP_ALREADY_POSTED"

    # Stay on the current group page and wait for the visible composer trigger.
    # Reload only once as a last resort; repeated reloads were the main source of
    # the "page flashes 2-3 times before posting" behaviour.
    # Most Facebook groups open at the cover/header. The composer is commonly
    # just below the fold, so reveal that area first instead of spending the
    # initial seconds searching the cover DOM.
    page.wait_for_timeout(500)
    try:
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(350)
        print("COMPOSER_REVEAL_SCROLL")
    except Exception as exc:
        print(f"COMPOSER_SCROLL_WARNING={exc}", file=sys.stderr)

    composer_ok = open_group_composer(page, ready_timeout_ms=9000)
    if not composer_ok:
        print("COMPOSER_LAST_RESORT_RELOAD")
        try:
            page.reload(wait_until="commit", timeout=20000)
            page.wait_for_timeout(500)
            page.mouse.wheel(0, 650)
            page.wait_for_timeout(350)
            print("COMPOSER_REVEAL_SCROLL_AFTER_RELOAD")
        except Exception as exc:
            print(f"COMPOSER_RELOAD_WARNING={exc}", file=sys.stderr)
        composer_ok = open_group_composer(page, ready_timeout_ms=8000)

    if not composer_ok:
        raise RuntimeError("Could not open Facebook Group composer after retry")

    print("COMPOSER_OPENED")

    # Never publish as the user's personal profile by accident.
    try:
        ensure_posting_identity(page, "Hóng Cùng Tôi")
    except Exception as exc:
        print(f"IDENTITY_RETRY={exc}", file=sys.stderr)
        page.wait_for_timeout(1500)
        ensure_posting_identity(page, "Hóng Cùng Tôi")

    # Important: media first, caption second.
    attach_image(page, image_path)
    if image_path:
        print("IMAGE_ATTACHED")

    if message:
        try:
            enter_caption(page, message)
        except Exception as exc:
            print(f"CAPTION_RETRY={exc}", file=sys.stderr)
            page.wait_for_timeout(500)
            enter_caption(page, message)
    else:
        print("IMAGE_ONLY_POST")

    # Wait by UI state, not a short fixed window. Fast groups proceed
    # immediately; slow groups get enough time when Chromium/Facebook is lagging.
    post_button = None
    button_deadline = time.time() + 25
    while time.time() < button_deadline:
        post_button = find_post_button(page)
        if post_button is not None:
            break
        page.wait_for_timeout(300)
    if post_button is None:
        raise RuntimeError("UI/COMPOSER_ERROR: Post button not found/enabled within 25 seconds")

    # Skip preview screenshots during production batches to reduce Chromium load.
    # Text/image/button checks above already validate the composer before submit.
    print("PREVIEW_SCREENSHOT_SKIPPED")

    if not confirm_post:
        print("DRY_RUN_OK")
        return 0

    post_button.click()

    # Wait only for the composer to disappear. In production we do not need to
    # wait for the new post to fully materialize because comments/visibility are
    # audited separately. This removes the old fixed 6-second penalty per group.
    try:
        page.locator("div[role='dialog']").first.wait_for(state="hidden", timeout=4500)
    except Exception:
        pass
    # Give Facebook a short settle window after the composer closes before
    # navigating to the next group. This reduces the risk of closing/navigating
    # while Facebook is still finishing the submission.
    page.wait_for_timeout(1200)

    # Avoid full-page screenshots after every submit; they caused long font/render
    # stalls in large batches. Verification below is text/state based.
    final = out / "group_post_after_submit.png"

    # Lightweight submit result. Do not scan the whole group page for generic
    # pending markers: they can belong to other posts and caused false positives.
    # Explicit visibility/pending can be audited separately only when needed.
    status = "SUBMITTED_UNVERIFIED"
    safety_stop = detect_facebook_safety_stop(page)
    if safety_stop:
        raise RuntimeError(f"SAFETY_STOP:{safety_stop}")

    print(f"{status}=lightweight_no_page_scan")
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
    """Download an approved remote image into a stable local cache.

    This runs during package preflight, before Chromium opens. Network/image
    failures therefore never cause the visible browser to flash open and close.
    """
    if not url.startswith("https://"):
        raise RuntimeError("ASSET_DOWNLOAD_FAILED: image_url must use https")

    parsed = urlparse(url)
    if "dropbox.com" in parsed.netloc.lower():
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        q["dl"] = "1"
        parsed = parsed._replace(query=urlencode(q))
        url = urlunparse(parsed)

    out_dir = Path(output_dir) / "remote_assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    cached = list(out_dir.glob(f"remote_asset_{cache_key}.*"))
    for candidate in cached:
        try:
            data = candidate.read_bytes()
            if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff") or (
                data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP"
            ):
                print(f"REMOTE_IMAGE_CACHE_HIT={candidate} bytes={len(data)}")
                return str(candidate)
        except Exception:
            pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://docs.google.com/",
    }

    data = None
    content_type = ""
    last_error = None
    for attempt in range(1, 4):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=25) as resp:
                data = resp.read()
                content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            last_error = None
            break
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            print(f"REMOTE_IMAGE_RETRY attempt={attempt} error={exc}", file=sys.stderr)
            if attempt < 3:
                time.sleep(attempt * 2)

    if last_error is not None or data is None:
        raise RuntimeError(f"ASSET_DOWNLOAD_FAILED: {last_error}")

    if len(data) < 1024:
        raise RuntimeError("ASSET_DOWNLOAD_FAILED: remote image returned too little data")

    detected_suffix = None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_suffix = ".png"
    elif data.startswith(b"\xff\xd8\xff"):
        detected_suffix = ".jpg"
    elif data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        detected_suffix = ".webp"

    if not detected_suffix:
        head = data[:200].lstrip().lower()
        if "text/html" in content_type or head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            raise RuntimeError("ASSET_DOWNLOAD_FAILED: remote URL returned HTML instead of an image")
        raise RuntimeError(f"ASSET_DOWNLOAD_FAILED: unsupported image content-type={content_type or 'unknown'}")

    if len(data) >= 10 * 1024 * 1024:
        raise RuntimeError(f"ASSET_DOWNLOAD_FAILED: image too large ({len(data)} bytes)")

    out_path = out_dir / f"remote_asset_{cache_key}{detected_suffix}"
    out_path.write_bytes(data)
    print(f"REMOTE_IMAGE_READY={out_path} bytes={len(data)} type={content_type or 'unknown'}")
    return str(out_path)


def preflight_package(package_path, output_dir):
    """Validate package and resolve its image before launching Chromium."""
    pkg_path = Path(package_path)
    if not pkg_path.exists():
        raise RuntimeError(f"PREFLIGHT_FAILED: package not found: {pkg_path}")

    pkg = json.loads(pkg_path.read_text(encoding="utf-8-sig"))
    message = str(pkg.get("message") or "").strip()
    post_mode_name = str(pkg.get("post_mode") or "IMAGE_CAPTION").strip().upper()
    if not message and post_mode_name != "IMAGE_COMMENTS":
        raise RuntimeError("PREFLIGHT_FAILED: package message is empty")

    group_urls = pkg.get("group_urls") or ([pkg["group_url"]] if pkg.get("group_url") else [])
    if not group_urls and not pkg.get("use_registry"):
        raise RuntimeError("PREFLIGHT_FAILED: package has no target groups")

    image_asset_name = str(pkg.get("image_asset_name") or "").strip()
    image_url = str(pkg.get("image_url") or "").strip()
    image_path = pkg.get("image_path")
    resolved = None

    if image_asset_name:
        resolved_path = LOCAL_ASSET_DIR / image_asset_name
        if not resolved_path.exists():
            raise RuntimeError(f"PREFLIGHT_FAILED: local temp image not found: {resolved_path}")
        try:
            raw = resolved_path.read_bytes()
        except Exception as exc:
            raise RuntimeError(f"PREFLIGHT_FAILED: cannot read local temp image: {exc}")
        if len(raw) < 1024:
            raise RuntimeError(f"PREFLIGHT_FAILED: local temp image too small ({len(raw)} bytes)")
        suffix = resolved_path.suffix.lower()
        valid = (
            raw.startswith(b"\xff\xd8\xff")
            or raw.startswith(b"\x89PNG\r\n\x1a\n")
            or (raw.startswith(b"RIFF") and len(raw) >= 12 and raw[8:12] == b"WEBP")
        )
        if not valid:
            raise RuntimeError(f"PREFLIGHT_FAILED: local temp asset is not a valid JPG/PNG/WEBP: {resolved_path.name}")
        print(f"LOCAL_ASSET_OK={resolved_path.name} bytes={len(raw)} suffix={suffix}")
        resolved = str(resolved_path)
    elif image_url:
        resolved = download_remote_image(image_url, output_dir)
    elif image_path:
        candidate = Path(image_path)
        if not candidate.exists():
            alt = Path("..") / candidate
            candidate = alt if alt.exists() else candidate
        if not candidate.exists():
            raise RuntimeError(f"PREFLIGHT_FAILED: image not found: {candidate}")
        resolved = str(candidate)

    print(f"PREFLIGHT_OK groups={len(group_urls) if group_urls else 'registry'} image={'yes' if resolved else 'no'}")
    return resolved



def audit_groups_mode(page, registry_path, message, output_dir):
    """Read-only recheck of the previous story across the canonical group list.

    Strategy:
    1) Open group home and look for the exact post headline/snippet.
    2) If absent, use Facebook group search for the headline and scroll results.
    3) Mark PENDING only when Facebook explicitly shows a pending-approval marker.
    4) Otherwise return UNKNOWN, never assume rejection from a missing DOM match.
    """
    from urllib.parse import quote

    registry_file = Path(registry_path or DEFAULT_AUDIT_REGISTRY)
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
    snippet = first_line if len(first_line) >= 20 else normalized[:90]
    search_query = first_line[:120]
    results = []
    pending_markers = [
        "đang chờ phê duyệt",
        "chờ quản trị viên phê duyệt",
        "bài viết đang chờ",
        "pending approval",
        "awaiting approval",
    ]

    def inspect_current_page():
        body_raw = " ".join(page.locator("body").inner_text(timeout=7000).split())
        body = body_raw.lower()
        if snippet and snippet in body_raw:
            return "ACTIVE"
        if any(x in body for x in pending_markers):
            return "PENDING"
        return None

    for idx, g in enumerate(groups, 1):
        url = str(g.get("url") or "").strip()
        if not url:
            continue
        row_no = g.get("row", idx)
        code = str(g.get("code") or f"ROW{row_no}")
        name = str(g.get("name") or "")
        print(f"AUDIT_GROUP={idx}/{len(groups)} row={row_no} id={code} name={name}")

        row = {
            "row": row_no,
            "id": code,
            "name": name,
            "group_url": url,
            "status": "UNKNOWN",
        }

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2600)

            if "login" in page.url.lower():
                row["status"] = "SESSION_EXPIRED"
            else:
                status = inspect_current_page()
                if status:
                    row["status"] = status
                else:
                    # Search inside this group for the exact headline.
                    search_url = url.rstrip("/") + "/search/?q=" + quote(search_query)
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)

                    for _ in range(3):
                        status = inspect_current_page()
                        if status:
                            row["status"] = status
                            break
                        try:
                            page.mouse.wheel(0, 3200)
                        except Exception:
                            pass
                        page.wait_for_timeout(1500)

                    if row["status"] == "UNKNOWN":
                        # Do not label as rejected: Facebook may hide older posts
                        # from search or paginate differently for Page identities.
                        row["status"] = "UNKNOWN"
        except Exception as exc:
            row["status"] = "ERROR"
            row["error"] = str(exc)

        results.append(row)
        print(f"AUDIT_RESULT=row{row_no}:{row['status']}")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "group_approval_audit.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    active = sum(1 for r in results if r["status"] == "ACTIVE")
    pending = sum(1 for r in results if r["status"] == "PENDING")
    unknown = sum(1 for r in results if r["status"] == "UNKNOWN")
    errors = len(results) - active - pending - unknown

    print(
        f"AUDIT_DONE total={len(results)} active={active} "
        f"pending={pending} unknown={unknown} errors={errors}"
    )
    print(f"AUDIT_REPORT={report}")
    return 0


def run_package(page, package_path, confirm_post, output_dir, prepared_image_path=None):
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

    post_mode_name = str(pkg.get("post_mode") or "IMAGE_CAPTION").strip().upper()
    if post_mode_name not in {"IMAGE_CAPTION", "IMAGE_COMMENTS"}:
        raise RuntimeError(f"Unsupported post_mode: {post_mode_name}")
    message = pkg.get("message", "").strip()
    if not message and post_mode_name != "IMAGE_COMMENTS":
        raise RuntimeError("Package message is empty")
    if post_mode_name == "IMAGE_COMMENTS" and not image_path:
        raise RuntimeError("IMAGE_COMMENTS requires an image")

    image_path = prepared_image_path
    if image_path is None:
        image_path = pkg.get("image_path")
        image_asset_name = str(pkg.get("image_asset_name") or "").strip()
        image_url = str(pkg.get("image_url") or "").strip()

        if image_asset_name:
            image_path = str(LOCAL_ASSET_DIR / image_asset_name)
            if not Path(image_path).exists():
                raise RuntimeError(f"Local temp image not found: {image_path}")
        elif image_url:
            image_path = download_remote_image(image_url, output_dir)
        elif image_path and not Path(image_path).exists():
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
    publish_id = str(pkg.get("publish_id") or pkg.get("event_id") or pkg_path.stem)
    publish_ledger = load_publish_ledger()

    for idx, group_url in enumerate(group_urls, 1):
        if confirm_post and ledger_has_submission(publish_ledger, publish_id, group_url):
            print(f"LEDGER_SKIP_ALREADY_SUBMITTED={publish_id}::{group_url}")
            results.append({"group_url": group_url, "status": "SKIP_ALREADY_POSTED", "reason": "local_publish_ledger"})
            write_batch_report(results, output_dir)
            continue
        print(f"GROUP_BATCH={idx}/{len(group_urls)}")
        try:
            rc = post_mode(page, group_url, message, image_path, confirm_post, output_dir, duplicate_scan=False)
            status = "PREVIEW_OK" if not confirm_post else (rc if isinstance(rc, str) else "POST_CLICKED")
            comment_status = None
            if confirm_post and comments and post_mode_name == "IMAGE_COMMENTS":
                # News mode: image-only main post, then comments immediately.
                # Submit each comment at most once. If Facebook keeps the post
                # pending for admin approval, comment boxes may be unavailable;
                # record that condition and move on instead of retry-spamming.
                comment_status = "COMMENTS_OK"
                for c_idx, spec in enumerate(comments, 1):
                    try:
                        safety_stop = detect_facebook_safety_stop(page)
                        if safety_stop:
                            raise RuntimeError(f"SAFETY_STOP:{safety_stop}")
                        add_comment(page, spec["message"])
                        print(f"NEWS_COMMENT_DONE={c_idx}/{len(comments)}")
                        page.wait_for_timeout(int(pkg.get("inter_comment_delay_seconds") or 2) * 1000)
                    except Exception as comment_exc:
                        if str(comment_exc).startswith("SAFETY_STOP:"):
                            raise
                        comment_status = "COMMENTS_UNAVAILABLE"
                        print(f"NEWS_COMMENT_WARNING={c_idx}/{len(comments)}::{comment_exc}", file=sys.stderr)
                        break
            elif confirm_post and comments:
                print(f"COMMENTS_IGNORED_FOR_MODE={post_mode_name} count={len(comments)}")
            row = {"group_url": group_url, "status": status, "post_mode": post_mode_name}
            if comment_status:
                row["comment_status"] = comment_status
            results.append(row)
            # Once Facebook accepted/clicked the submission, persist the story+group
            # pair locally. This prevents a repeated command from posting again even
            # when the first post is still pending approval and not publicly visible.
            if confirm_post and status in {"POST_CLICKED","POSTED_UNVERIFIED","SUBMITTED_UNVERIFIED","PUBLISHED_VISIBLE","POST_OK_COMMENT_WARNING","PENDING_APPROVAL"}:
                ledger_mark_submission(publish_ledger, publish_id, group_url)
            write_batch_report(results, output_dir)
        except Exception as exc:
            err = str(exc)
            import traceback
            print(f"GROUP_EXCEPTION_TRACE={traceback.format_exc()}", file=sys.stderr)
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

        # Recycle the tab every few groups. Facebook group pages accumulate large
        # DOM trees/media and become sluggish in long runs; a fresh tab in the same
        # browser context keeps cookies/Page identity but frees per-tab resources.
        recycle_every = int(pkg.get("recycle_page_every") or 5)
        if idx < len(group_urls) and recycle_every > 0 and idx % recycle_every == 0:
            try:
                context = page.context
                old_page = page
                page = context.new_page()
                old_page.close()
                print(f"PAGE_RECYCLED_AFTER={idx}")
            except Exception as exc:
                print(f"PAGE_RECYCLE_WARNING={exc}", file=sys.stderr)

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
    posted = [r for r in results if r["status"] in {"POST_CLICKED","POSTED_UNVERIFIED","SUBMITTED_UNVERIFIED","PUBLISHED_VISIBLE","POST_OK_COMMENT_WARNING","PREVIEW_OK","PENDING_APPROVAL","SKIP_ALREADY_POSTED"}]
    safety_stops = [r for r in results if r["status"] == "SAFETY_STOP"]
    print(f"BATCH_DONE total={len(results)} posted_or_preview={len(posted)} skipped={len(skipped)} errors={len(failures)}")
    # Keep the queue alive when only a few groups fail. The per-group report is
    # authoritative for selective retries. Fail the command only if nothing
    # posted or Facebook raised a safety stop.
    return 1 if safety_stops or (not posted and failures) else 0

def main():
    if not acquire_single_instance():
        print("GROUP_POSTER_ALREADY_RUNNING", file=sys.stderr)
        return 3

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
    ap.add_argument("--registry", default=str(DEFAULT_AUDIT_REGISTRY), help="Registry JSON for --audit-groups")
    ap.add_argument("--audit-message-file", help="Previous post text used to identify the story during --audit-groups")
    ap.add_argument("--comment-only-url", help="Existing Facebook post URL; never creates a new post")
    ap.add_argument("--confirm-comments", action="store_true", help="Actually submit comments in comment-only mode")
    args = ap.parse_args()

    if not args.login and not args.group_url and not args.package and not args.comment_only_url and not args.audit_groups:
        ap.error("Use --login, --package, --comment-only-url, --audit-groups, or provide --group-url")

    message = args.message or (read_text(args.message_file) if args.message_file else "")
    if not args.login and not args.package and not args.comment_only_url and not args.audit_groups and not message:
        ap.error("Provide --message or --message-file")
    if args.comment_only_url and not args.package:
        ap.error("--comment-only-url requires --package for comment text")

    prepared_image_path = None
    if args.package and not args.comment_only_url:
        try:
            prepared_image_path = preflight_package(args.package, args.output_dir)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Cookies are saved separately, so Group Poster does not need a persistent
    # Chromium user-data directory. A fresh context per batch avoids profile
    # locks/corruption and the long hangs seen with launch_persistent_context.
    with sync_playwright() as p:
        browser = None
        context = None
        launch_error = None
        for attempt in range(1, 3):
            try:
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        "--disable-notifications",
                        "--disable-background-networking",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-extensions",
                        "--disable-component-extensions-with-background-pages",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": 1400, "height": 1000},
                    locale="vi-VN",
                )
                launch_error = None
                break
            except Exception as exc:
                launch_error = exc
                print(f"BROWSER_LAUNCH_RETRY attempt={attempt} error={exc}", file=sys.stderr)
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
                browser = None
                context = None
                if attempt < 2:
                    time.sleep(2)

        if launch_error is not None or context is None:
            raise RuntimeError(f"Could not launch clean Chromium context: {launch_error}")

        if not args.login:
            load_saved_session(context)
        page = context.new_page()
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
                return run_package(page, args.package, args.confirm_post, args.output_dir, prepared_image_path=prepared_image_path)
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
            try:
                if context is not None:
                    context.close()
            finally:
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
