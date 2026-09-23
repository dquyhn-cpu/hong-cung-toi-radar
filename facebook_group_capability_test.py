import json
import os
import sys
import requests

GRAPH_VERSION=os.getenv("FB_GRAPH_VERSION","v26.0")
TOKEN=os.environ.get("FB_PAGE_ACCESS_TOKEN")
GROUP_IDS=[x.strip() for x in os.environ.get("FB_GROUP_IDS","").split(",") if x.strip()]

if not TOKEN:
    raise SystemExit("Missing FB_PAGE_ACCESS_TOKEN")
if not GROUP_IDS:
    raise SystemExit("Missing FB_GROUP_IDS")

BASE=f"https://graph.facebook.com/{GRAPH_VERSION}"
s=requests.Session()

def get(path, params=None):
    p=dict(params or {})
    p["access_token"]=TOKEN
    r=s.get(f"{BASE}/{path.lstrip('/')}",params=p,timeout=25)
    try:
        payload=r.json()
    except Exception:
        payload={"raw":r.text}
    return r.status_code,payload

results=[]
for gid in GROUP_IDS:
    status,payload=get(f"/{gid}",{"fields":"id,name,privacy"})
    item={"group_id":gid,"http_status":status}
    if status==200 and "error" not in payload:
        item.update({
            "readable":True,
            "name":payload.get("name"),
            "privacy":payload.get("privacy"),
            "note":"Group is readable with current token. This does NOT prove publish permission."
        })
    else:
        err=payload.get("error",{}) if isinstance(payload,dict) else {}
        item.update({
            "readable":False,
            "error_code":err.get("code"),
            "error_subcode":err.get("error_subcode"),
            "error_message":err.get("message") or payload
        })
    results.append(item)

print(json.dumps({"mode":"READ_ONLY_CAPABILITY_TEST","groups":results},ensure_ascii=False,indent=2))
