import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REG = HERE / 'group_registry_normalized.json'
OUT = HERE / 'output' / 'group_verify_report.json'
PROFILE = str(Path.home() / '.hong-cung-toi' / 'facebook-group-profile')

def body_text(page):
    try:
        return page.locator('body').inner_text(timeout=5000)
    except Exception:
        return ''

def main():
    reg = json.loads(REG.read_text(encoding='utf-8-sig'))
    groups = reg.get('groups', [])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    results=[]
    with sync_playwright() as p:
        context=p.chromium.launch_persistent_context(user_data_dir=PROFILE, headless=True, args=['--disable-notifications'])
        page=context.pages[0] if context.pages else context.new_page()
        try:
            for i,g in enumerate(groups,1):
                print(f'VERIFY_GROUP={i}/{len(groups)} {g["id"]}', flush=True)
                r={'id':g['id'],'group_id':g.get('group_id'),'url':g['url'],'status':'ERROR'}
                try:
                    page.goto(g['url'], wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_timeout(1200)
                    txt=body_text(page)
                    r['final_url']=page.url
                    r['login_redirect']='login' in page.url.lower()
                    r['join_button_visible']=('Tham gia nhóm' in txt or 'Join group' in txt)
                    r['joined_signal']=('Đã tham gia' in txt or 'Joined' in txt)
                    r['composer_signal']=any(x in txt for x in ['Bạn viết gì đi','Viết gì đó','Write something','Tạo bài viết'])
                    # No clicks: do not join, do not open composer.
                    r['status']='OK'
                except Exception as exc:
                    r['error']=str(exc)
                results.append(r)
        finally:
            context.close()
    OUT.write_text(json.dumps({'mode':'VERIFY_READ_ONLY','results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'VERIFY_REPORT={OUT}', flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
