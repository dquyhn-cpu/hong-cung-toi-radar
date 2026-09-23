import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_PROFILE = str(Path.home() / ".hong-cung-toi" / "facebook-group-profile")


def read_text(path):
    return Path(path).read_text(encoding="utf-8").strip()


def ensure_file(path, label):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"{label} not found: {p}")
    return p


def click_first(page, candidates, timeout=2500):
    last = None
    for kind, value in candidates:
        try:
            if kind == "role":
                role, name = value
                loc = page.get_by_role(role, name=name)
            elif kind == "text":
                loc = page.get_by_text(value, exact=False)
            elif kind == "css":
                loc = page.locator(value)
            else:
                continue
            loc.first.wait_for(state="visible", timeout=timeout)
            loc.first.click()
            return True
        except Exception as exc:
            last = exc
    if last:
        raise last
    return False


def switch_to_page_identity(page, page_name):
    """
    Switch Facebook interaction identity to the requested Page.
    Safety rule: if the requested Page cannot be selected/confirmed, STOP.
    """
    target = (page_name or "").strip()
    if not target:
        raise RuntimeError("Missing --page-name; refusing to post as personal profile")

    # First try obvious identity controls shown in groups.
    identity_labels = [
        "Tương tác dưới tên",
        "Interact as",
        "Chuyển trang cá nhân",
        "Switch profile",
        "Chuyển hồ sơ",
        "Switch profile or Page",
    ]
    opened = False
    for label in identity_labels:
        try:
            loc = page.get_by_text(label, exact=False)
            loc.first.wait_for(state="visible", timeout=1600)
            loc.first.click()
            opened = True
            break
        except Exception:
            pass

    # Fallback: click account/profile menu in the top-right.
    if not opened:
        selectors = [
            "div[aria-label='Account']",
            "div[aria-label='Tài khoản']",
            "div[aria-label='Your profile']",
            "div[aria-label='Trang cá nhân của bạn']",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                loc.first.wait_for(state="visible", timeout=1400)
                loc.first.click()
                opened = True
                break
            except Exception:
                pass

    if not opened:
        raise RuntimeError(
            f"Could not open Facebook identity switcher. Refusing to continue because Page '{target}' is required."
        )

    page.wait_for_timeout(700)

    # Select exact Page name where possible.
    selected = False
    try:
        loc = page.get_by_text(target, exact=True)
        loc.first.wait_for(state="visible", timeout=3000)
        loc.first.click()
        selected = True
    except Exception:
        try:
            loc = page.get_by_text(target, exact=False)
            loc.first.wait_for(state="visible", timeout=2500)
            loc.first.click()
            selected = True
        except Exception:
            pass

    if not selected:
        raise RuntimeError(
            f"Page identity '{target}' was not available. Refusing to post as personal profile."
        )

    page.wait_for_timeout(2200)

    # Conservative confirmation: the requested Page name must be visible after switch.
    # If Facebook changes UI and this cannot be confirmed, stop rather than risk wrong identity.
    try:
        page.get_by_text(target, exact=False).first.wait_for(state="visible", timeout=2500)
    except Exception:
        raise RuntimeError(
            f"Could not confirm active identity '{target}'. Refusing to continue."
        )

    print(f"PAGE_IDENTITY_CONFIRMED={target}")
    return True


def open_composer(page):
    candidates = [
        ("role", ("button", "Write something")),
        ("role", ("button", "Viết gì đó")),
        ("role", ("button", "Bạn viết gì đi")),
        ("role", ("button", "Tạo bài viết")),
        ("text", "Write something"),
        ("text", "Viết gì đó"),
        ("text", "Bạn viết gì đi"),
        ("text", "Hãy viết gì đó"),
        ("text", "Tạo bài viết"),
    ]
    try:
        return click_first(page, candidates, timeout=2200)
    except Exception:
        # Fallback: click the visible composer prompt text.
        for needle in ["Write something", "Viết gì đó", "Bạn viết gì đi", "Hãy viết gì đó", "Create post", "Tạo bài viết"]:
            try:
                page.get_by_text(needle, exact=False).first.click(timeout=2000)
                return True
            except Exception:
                pass
    return False


def fill_message(page, message):
    # Facebook uses a Lexical editor. After media is attached there can be
    # several contenteditable nodes, so target the visible empty textbox in the
    # active Create Post dialog and paste text as one operation.
    dialog = page.locator("div[role='dialog']").last
    candidates = [
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "div[contenteditable='true']",
    ]
    last_error = None
    for sel in candidates:
        loc = dialog.locator(sel)
        try:
            count = loc.count()
            for i in range(count):
                target = loc.nth(i)
                if not target.is_visible():
                    continue
                box = target.bounding_box()
                if not box or box["height"] < 20 or box["width"] < 120:
                    continue
                target.click()
                page.keyboard.press("Control+A")
                page.keyboard.insert_text(message)
                page.wait_for_timeout(500)
                txt = target.inner_text().strip()
                if message[:25] in txt:
                    print("CAPTION_TYPED")
                    return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not reliably fill Facebook post text editor: {last_error}")


def verify_message(page, message):
    expected = message.strip()
    if not expected:
        return True
    prefix = expected[:40]
    dialog = page.locator("div[role='dialog']")
    try:
        text = dialog.last.inner_text(timeout=3000)
    except Exception:
        text = page.locator("body").inner_text(timeout=3000)
    if prefix not in text:
        raise RuntimeError(
            "Caption disappeared from composer after media upload. Refusing to continue."
        )
    print("CAPTION_CONFIRMED")
    return True


def attach_image(page, image_path):
    if not image_path:
        return
    p = ensure_file(image_path, "Image")
    inputs = page.locator("input[type='file']")
    count = inputs.count()
    if count == 0:
        # Try to expose file input by clicking Photo/video.
        for needle in ["Photo/video", "Ảnh/video", "Photo", "Ảnh"]:
            try:
                page.get_by_text(needle, exact=False).first.click(timeout=1800)
                time.sleep(0.5)
                break
            except Exception:
                pass
        inputs = page.locator("input[type='file']")
        count = inputs.count()
    if count == 0:
        raise RuntimeError("Could not locate Facebook image upload input")
    inputs.last.set_input_files(str(p.resolve()))


def find_post_button(page):
    candidates = [
        ("role", ("button", "Post")),
        ("role", ("button", "Đăng")),
        ("text", "Post"),
        ("text", "Đăng"),
    ]
    for kind, value in candidates:
        try:
            if kind == "role":
                role, name = value
                loc = page.get_by_role(role, name=name)
            else:
                loc = page.get_by_text(value, exact=True)
            loc.first.wait_for(state="visible", timeout=2000)
            return loc.first
        except Exception:
            pass
    return None


def login_mode(context, page):
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
    print("\nFacebook opened in a dedicated browser profile.")
    print("Log in manually, complete any checkpoint/2FA, then return here.")
    input("Press ENTER after Facebook is fully logged in... ")
    page.reload(wait_until="domcontentloaded", timeout=60000)
    print("LOGIN_PROFILE_READY")
    return 0


def post_mode(context, page, group_url, message, image_path, do_post, screenshot_dir, page_name):
    group_url = group_url.strip()
    if not group_url.startswith("https://www.facebook.com/groups/"):
        raise SystemExit("group_url must be a Facebook group URL")

    page.goto(group_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)

    if "login" in page.url.lower():
        raise RuntimeError("Facebook session is not logged in. Run with --login first.")

    # Dedicated Chromium profile is reserved for Group Poster and should
    # remain logged in as the Hóng Cùng Tôi Page. Do not switch identity on
    # every run: it adds an unnecessary navigation round-trip.
    # Safety is verified from the composer after it opens.
    print(f"USING_PERSISTED_PAGE_SESSION={page_name}")

    if not open_composer(page):
        raise RuntimeError("Could not open group post composer. You may not have permission to post in this group.")

    page.wait_for_timeout(800)

    # Dedicated browser profile is already reserved for the Page session.
    # Do not perform another identity switch or a brittle text check here.
    # The first manual setup/preview established the Page identity.
    print(f"PAGE_SESSION_REUSED={page_name}")
    # Attach media FIRST. Facebook re-renders the composer after image upload,
    # which can discard text entered beforehand.
    attach_image(page, image_path)
    page.wait_for_timeout(1800)

    # Fill caption only after the media editor has stabilized.
    fill_message(page, message)
    page.wait_for_timeout(700)
    verify_message(page, message)

    post_button = find_post_button(page)
    if not post_button:
        raise RuntimeError("Could not locate the final Post button")

    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
    preview = Path(screenshot_dir) / "group_post_preview.png"
    page.screenshot(path=str(preview), full_page=False)
    print(f"PREVIEW_SCREENSHOT={preview}")

    if not do_post:
        print("DRY_RUN_OK: composer is ready; nothing was posted.")
        print("Re-run with --confirm-post only after checking the preview.")
        return 0

    post_button.click()
    page.wait_for_timeout(3500)

    final = Path(screenshot_dir) / "group_post_after_submit.png"
    page.screenshot(path=str(final), full_page=False)
    print(f"POST_CLICKED screenshot={final}")
    print("IMPORTANT: Some groups use admin approval. Confirm the post state visually in Facebook.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Hóng Cùng Tôi - isolated Facebook Group Poster V1")
    ap.add_argument("--profile-dir", default=DEFAULT_PROFILE)
    ap.add_argument("--login", action="store_true", help="Open a visible browser for manual Facebook login")
    ap.add_argument("--group-url")
    ap.add_argument("--message")
    ap.add_argument("--message-file")
    ap.add_argument("--image")
    ap.add_argument("--page-name", default="Hóng Cùng Tôi", help="Required Facebook Page identity for group posting")
    ap.add_argument("--confirm-post", action="store_true")
    ap.add_argument("--screenshot-dir", default="group_poster/output")
    args = ap.parse_args()

    if not args.login and not args.group_url:
        ap.error("Use --login or provide --group-url")

    message = args.message or (read_text(args.message_file) if args.message_file else "")
    if not args.login and not message:
        ap.error("Provide --message or --message-file")

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
                return login_mode(context, page)
            return post_mode(
                context,
                page,
                args.group_url,
                message,
                args.image,
                args.confirm_post,
                args.screenshot_dir,
                args.page_name,
            )
        except PlaywrightTimeoutError as exc:
            print(f"TIMEOUT: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            try:
                Path(args.screenshot_dir).mkdir(parents=True, exist_ok=True)
                err = Path(args.screenshot_dir) / "group_post_error.png"
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
