import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / 'group_registry.json'
OUTPUT = HERE / 'output' / 'group_scan_report.json'
PROFILE = str(Path.home() / '.hong-cung-toi' / 'facebook-group-profile')

def canonical_group_url(url):
    m = re.search(r'facebook\.com/groups/(\d+)', url or '')
    if m:
        return f'https://www.facebook.com/groups/{m.group(1)}/'
    return url

def group_id_from_url(url):
    m = re.search(r'facebook\.com/groups/(\d+)', url or '')
    return m.group(1) if m else None

def text_present(page, needles):
    body = page.locator('body').inner_text(timeout=5000)
    low = body.lower()
    return any(n.lower() in low for n in needles)

def first_text(page, selectors):
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count():
                t = loc.first.inner_text(timeout=2000).strip()
                if t:
                    return t
        except Exception:
            pass
    return None

def scan_one(page, item):
    src = item['url']
    result = {'id': item['id'], 'source_url': src, 'status': 'ERROR'}
    try:
        page.goto(src, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(1800)
        final = page.url
        # Even if Facebook redirects to login, its ?next= URL often still
        # contains the real group target. Preserve that resolved identity.
        from urllib.parse import urlparse, parse_qs, unquote
        identity_url = final
        if 'login' in final.lower():
            try:
                nxt = parse_qs(urlparse(final).query).get('next', [None])[0]
                if nxt:
                    identity_url = unquote(nxt)
            except Exception:
                pass
        result['resolved_url'] = canonical_group_url(identity_url)
        result['group_id'] = group_id_from_url(identity_url)
        result['name'] = first_text(page, ['h1', "div[role='main'] h1"])

        if 'login' in final.lower():
            result['status'] = 'SESSION_EXPIRED'
            result['membership'] = 'UNKNOWN'
            result['page_can_post_signal'] = False
            return result

        # Read-only membership signals. Never click Join.
        not_joined = text_present(page, ['Tham gia nhóm', 'Join group'])
        joined = text_present(page, ['Đã tham gia', 'Joined'])
        result['membership'] = 'NOT_JOINED' if not_joined and not joined else ('JOINED' if joined else 'UNKNOWN')

        # Read-only posting signals. We do not open composer during scan.
        can_post = text_present(page, ['Bạn viết gì đi', 'Viết gì đó', 'Write something', 'Tạo bài viết'])
        result['page_can_post_signal'] = bool(can_post)
        result['status'] = 'OK'
        return result
    except Exception as exc:
        result['error'] = str(exc)
        return result

def main():
    registry = json.loads(REGISTRY.read_text(encoding='utf-8-sig'))
    items = registry.get('groups', [])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            headless=True,
            args=['--disable-notifications'],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for idx, item in enumerate(items, 1):
                print(f'SCAN_GROUP={idx}/{len(items)} {item["id"]}', flush=True)
                results.append(scan_one(page, item))
        finally:
            context.close()

    # Mark duplicates by resolved group_id.
    seen = {}
    for r in results:
        gid = r.get('group_id')
        if gid:
            if gid in seen:
                r['duplicate_of'] = seen[gid]
            else:
                seen[gid] = r['id']

    payload = {
        'mode': 'READ_ONLY_NO_JOIN_NO_POST',
        'total_input': len(items),
        'unique_resolved_group_ids': len(seen),
        'results': results,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'SCAN_REPORT={OUTPUT}', flush=True)
    print(f'UNIQUE_RESOLVED={len(seen)}', flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
