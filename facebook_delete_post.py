import os
import requests

GRAPH_VERSION = os.getenv("FB_GRAPH_VERSION", "v26.0")
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
RAW_POST_ID = os.environ["FB_POST_ID"]\nPAGE_ID = RAW_POST_ID.split("_", 1)[0]\nPOST_ID = f"{PAGE_ID}_122126195721380231"

r = requests.delete(
    f"https://graph.facebook.com/{GRAPH_VERSION}/{POST_ID}",
    data={"access_token": TOKEN},
    timeout=30,
)
print("STATUS", r.status_code)
print("BODY", r.text)
r.raise_for_status()
payload = r.json()
if payload.get("success") is not True:
    raise SystemExit(f"Delete did not return success=true: {payload}")
print("DELETE_OK", POST_ID)
