import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

import radar

HERE = Path(__file__).resolve().parent
PROFILE_DIR = Path.home() / ".hong-cung-toi" / "facebook-radar-profile"
OUTPUT_FILE = HERE / "radar_fb_local.json"
DIAG_FILE = HERE / "radar_fb_local_diagnostics.json"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)



def likely_page_authored(post, source_name):
    """Filter nested comment/reply role=article nodes that inherit a parent post URL."""
    text = radar.normalize_text(post.get("text", ""))[:500]
    aliases = {
        "Thông tin Chính phủ": ["thong tin chinh phu"],
        "Bộ Công an": ["bo cong an"],
        "BeatVN": ["beatvn"],
        "Theanh28": ["theanh28"],
        "Top Comments": ["top comments"],
        "Bí Mật Showbiz": ["bi mat showbiz"],
    }
    keys = aliases.get(source_name, [radar.normalize_text(source_name)])
    if any(key and key in text for key in keys):
        return True
    # Main page posts commonly include the explicit author marker in Facebook UI.
    return text.startswith("tac gia")


def collect_once(headless=False):
    generated_at = datetime.now(timezone.utc).isoformat()
    all_posts = []
    source_stats = {}
    source_errors = {}
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 1000},
            locale="vi-VN",
            args=["--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)
        try:
            body = radar.normalize_text(page.locator("body").inner_text(timeout=3000))
        except Exception:
            body = ""

        if "dang nhap" in body or "log in" in body or "login" in body:
            context.close()
            raise RuntimeError("Facebook session is not logged in. Run: python facebook_collector_local.py --login")

        for source_name, config in radar.FACEBOOK_SOURCES.items():
            if config.get("tier") not in {"SOCIAL_RADAR", "OFFICIAL_FB"}:
                continue
            try:
                raw_posts = radar.collect_fb_source(page, source_name, config)
                posts = [p for p in raw_posts if likely_page_authored(p, source_name)]
                source_stats[source_name] = len(posts)
                all_posts.extend(posts)
                print(f"AUTHORED_FILTER {source_name}: raw={len(raw_posts)} kept={len(posts)}")
            except Exception as exc:
                source_stats[source_name] = 0
                source_errors[source_name] = str(exc)

        context.close()

    unique = {}
    for post in all_posts:
        key = post.get("post_id") or post.get("url")
        if not key:
            continue
        current = unique.get(key)
        if current is None or len(post.get("text", "")) > len(current.get("text", "")):
            unique[key] = post

    payload = {
        "generated_at": generated_at,
        "collector": "LOCAL_PERSISTENT_CHROMIUM",
        "profile_dir": str(PROFILE_DIR),
        "source_stats": source_stats,
        "facebook_posts": list(unique.values()),
    }
    save_json(OUTPUT_FILE, payload)
    save_json(DIAG_FILE, {
        "generated_at": generated_at,
        "source_stats": source_stats,
        "source_errors": source_errors,
        "post_count": len(unique),
    })
    print(f"LOCAL_FB_COLLECTOR_OK posts={len(unique)} output={OUTPUT_FILE.name}")
    for name, count in source_stats.items():
        print(f" - {name}: {count}")
    return 0


def login():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 1000},
            locale="vi-VN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
        print("Log in to Facebook in this dedicated Chromium window.")
        print("After the Facebook home page is fully usable, return here and press ENTER.")
        input()
        context.close()
    print("FACEBOOK_RADAR_PROFILE_READY")
    return 0


def git_sync_outputs():
    paths = [OUTPUT_FILE, DIAG_FILE]
    rels = [str(p.relative_to(HERE)) for p in paths if p.exists()]
    if not rels:
        return

    def run(args, timeout=90):
        return subprocess.run(args, cwd=str(HERE), capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)

    run(["git", "config", "user.name", "HCT Facebook Collector"])
    run(["git", "config", "user.email", "hct-fb-collector@local"])
    run(["git", "add", "-f", *rels])
    diff = run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("GIT_SYNC: no changes")
        return

    commit = run(["git", "commit", "-m", f"Facebook collector snapshot {datetime.now().isoformat(timespec='seconds')}"])
    if commit.returncode != 0:
        raise RuntimeError((commit.stderr or commit.stdout).strip())

    rebase = run(["git", "pull", "--rebase", "--autostash", "origin", "main"])
    if rebase.returncode != 0:
        raise RuntimeError((rebase.stderr or rebase.stdout).strip())

    push = run(["git", "push", "origin", "HEAD:main"])
    if push.returncode != 0:
        raise RuntimeError((push.stderr or push.stdout).strip())

    print("GIT_SYNC: pushed radar_fb_local.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()

    if args.login:
        return login()

    rc = collect_once(headless=args.headless)
    if args.push:
        git_sync_outputs()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
