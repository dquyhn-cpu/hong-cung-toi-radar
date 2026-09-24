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
    print("LOGIN_PROFILE_READY")
    return 0


def post_mode(page, group_url, message, image_path, confirm_post, output_dir):
    if not group_url.startswith("https://www.facebook.com/groups/"):
        raise RuntimeError("Invalid Facebook Group URL")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    page.goto(group_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)

    if "login" in page.url.lower():
        # Interactive recovery: keep this exact persistent-profile Chromium
        # window open so the operator can complete Facebook login/2FA.
        print("FACEBOOK_LOGIN_REQUIRED")
        print("LOGIN_HOLD=300s")
        deadline = time.time() + 300
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            if "login" not in page.url.lower():
                break
        if "login" in page.url.lower():
            raise RuntimeError("Facebook login was not completed within 300 seconds")
        # Return to the intended group after login completes.
        page.goto(group_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

    print("GROUP_OPENED")

    if not open_group_composer(page):
        # Diagnostic mode: capture visible Facebook text and keep the browser
        # open briefly so the operator can inspect the exact UI variant.
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
            diag = out / "composer_debug.txt"
            diag.write_text(body_text[:30000], encoding="utf-8")
            print(f"COMPOSER_DEBUG_TEXT={diag}")
            snap = out / "composer_debug.png"
            page.screenshot(path=str(snap), full_page=False)
            print(f"COMPOSER_DEBUG_SCREENSHOT={snap}")
        except Exception as exc:
            print(f"COMPOSER_DEBUG_WARNING={exc}")
        print("COMPOSER_DEBUG_HOLD=120s")
        page.wait_for_timeout(120000)
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
    page.wait_for_timeout(3500)
    final = out / "group_post_after_submit.png"
    page.screenshot(path=str(final), full_page=False)
    print(f"POST_CLICKED={final}")
    return 0



def add_comment(page, message):
    # Top-level comment on the current post.
    selectors = [
        "[contenteditable='true'][aria-label*='Bình luận dưới tên']",
        "[contenteditable='true'][aria-label*='Viết bình luận']",
        "[contenteditable='true'][aria-label*='Write a comment']",
    ]
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(loc.count() - 1, -1, -1):
            box = loc.nth(i)
            try:
                if not box.is_visible():
                    continue
                box.click(force=True)
                page.keyboard.insert_text(message)
                page.keyboard.press("Enter")
                page.wait_for_timeout(1400)
                print("COMMENT_POSTED")
                return True
            except Exception:
                pass
    raise RuntimeError("Could not find comment box for the submitted post")


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
            status = "PREVIEW_OK" if not confirm_post else "POST_CLICKED"
            if confirm_post:
                # Keep comments deliberately simple and robust: all comments are
                # posted at top level. reply_to metadata is ignored.
                for spec in comments:
                    try:
                        add_comment(page, spec["message"])
                    except Exception as exc:
                        print(f"COMMENT_WARNING={exc}")
                        status = "POST_OK_COMMENT_WARNING"
                        break
            results.append({"group_url": group_url, "status": status})
        except Exception as exc:
            err = str(exc)
            expected_skip = any(x in err for x in [
                "Could not open Facebook Group composer",
                "Facebook session expired",
                "Invalid Facebook Group URL",
            ])
            status = "SKIPPED" if expected_skip else "ERROR"
            results.append({"group_url": group_url, "status": status, "error": err})
            print(f"GROUP_{status}={group_url} :: {err}", file=sys.stderr)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "group_batch_report.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"BATCH_REPORT={report}")

    failures = [r for r in results if r["status"] == "ERROR"]
    skipped = [r for r in results if r["status"] == "SKIPPED"]
    posted = [r for r in results if r["status"] in {"POST_CLICKED","POST_OK_COMMENT_WARNING","PREVIEW_OK"}]
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
    ap.add_argument("--comment-only-url", help="Existing Facebook post URL; never creates a new post")
    ap.add_argument("--confirm-comments", action="store_true", help="Actually submit comments in comment-only mode")
    args = ap.parse_args()

    if not args.login and not args.group_url and not args.package and not args.comment_only_url:
        ap.error("Use --login, --package, --comment-only-url, or provide --group-url")

    message = args.message or (read_text(args.message_file) if args.message_file else "")
    if not args.login and not args.package and not args.comment_only_url and not message:
        ap.error("Provide --message or --message-file")
    if args.comment_only_url and not args.package:
        ap.error("--comment-only-url requires --package for comment text")

    profile = Path(args.profile_dir)
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Always use the single dedicated persistent Group Poster profile.
        # This preserves Facebook login/session state across publish runs.
        # Do not clone the profile; if it is currently open elsewhere, fail
        # clearly and let the operator close that dedicated Chromium window.
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                viewport={"width": 1400, "height": 1000},
                args=["--disable-notifications", "--disable-background-mode", "--no-first-run"],
            )
        except Exception as exc:
            msg = str(exc)
            if "Target page, context or browser has been closed" in msg or "ProcessSingleton" in msg or "profile" in msg.lower():
                raise RuntimeError(
                    "Dedicated Group Poster Chromium profile is already in use. "
                    "Close only the Group Poster Chromium window/background process, then retry. "
                    "The saved Facebook login will remain in this same profile."
                ) from exc
            raise
        page = context.pages[0] if context.pages else context.new_page()
        try:
            if args.login:
                return login_mode(page)
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
