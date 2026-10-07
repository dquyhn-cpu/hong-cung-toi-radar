import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LOCAL_DYNAMIC = Path.home() / ".hong-cung-toi" / "group_dynamic_hold.json"
CENTRAL_HOLD = HERE / "group_hold.json"
CENTRAL_REPORT = HERE / "not_member_registry.json"

def norm(url):
    return str(url or "").strip().rstrip("/")

def run_git(*args, check=True):
    p = subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        text=True,
        capture_output=True,
    )
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip())
    return p

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default

def category_map():
    out = {}
    for path in HERE.glob("group_registry_*.json"):
        try:
            data = load_json(path, {})
            cat = str(data.get("category") or path.stem).strip()
            for g in data.get("groups") or []:
                u = norm(g.get("url"))
                if not u:
                    continue
                row = out.setdefault(u, {"categories": set(), "names": set(), "ids": set()})
                row["categories"].add(cat)
                if g.get("name"):
                    row["names"].add(str(g["name"]))
                if g.get("id"):
                    row["ids"].add(str(g["id"]))
        except Exception:
            pass
    return out

def main():
    if not LOCAL_DYNAMIC.exists():
        print("CENTRAL_HOLD_SYNC=no_local_dynamic_hold")
        return 0

    local = load_json(LOCAL_DYNAMIC, {})
    discovered = {norm(x) for x in (local.get("groups") or []) if norm(x)}
    if not discovered:
        print("CENTRAL_HOLD_SYNC=no_not_member_groups")
        return 0

    # Refresh remote tracked files before merging. Dynamic hold lives outside
    # the repo, so it cannot be lost by this pull.
    pull = run_git("pull", "--rebase", "--autostash", "origin", "main", check=False)
    if pull.returncode != 0:
        print("CENTRAL_HOLD_PULL_WARNING=" + (pull.stderr or pull.stdout).strip())

    central = load_json(CENTRAL_HOLD, {"groups": []})
    existing = {norm(x) for x in (central.get("groups") or []) if norm(x)}
    merged = existing | discovered

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    reasons = dict(central.get("reasons") or {})
    for u in discovered:
        reasons[u] = "NOT_MEMBER"

    central["updated_at"] = now
    central["policy"] = (
        "Global exclusion list shared by all Group Poster categories. "
        "Contains manual exclusions/pending groups plus groups automatically "
        "confirmed as NOT_MEMBER. Never auto-join; remove only by explicit user instruction."
    )
    central["groups"] = sorted(merged)
    central["reasons"] = reasons
    CENTRAL_HOLD.write_text(json.dumps(central, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cmap = category_map()
    report = load_json(CENTRAL_REPORT, {"groups": {}})
    report.setdefault("groups", {})
    for u in discovered:
        meta = cmap.get(u, {})
        report["groups"][u] = {
            "status": "NOT_MEMBER",
            "first_or_last_seen": now,
            "categories": sorted(meta.get("categories", set())),
            "names": sorted(meta.get("names", set())),
            "ids": sorted(meta.get("ids", set())),
        }
    report["updated_at"] = now
    report["count"] = len(report["groups"])
    CENTRAL_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run_git("add", "--", str(CENTRAL_HOLD.relative_to(REPO)), str(CENTRAL_REPORT.relative_to(REPO)))
    diff = run_git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        print(f"CENTRAL_HOLD_SYNC=no_changes total={len(merged)}")
        return 0

    commit = run_git("commit", "-m", "Sync NOT_MEMBER groups to central hold", check=False)
    if commit.returncode != 0:
        print("CENTRAL_HOLD_COMMIT_WARNING=" + (commit.stderr or commit.stdout).strip())
        return 1

    push = run_git("push", "origin", "main", check=False)
    if push.returncode != 0:
        print("CENTRAL_HOLD_PUSH_WARNING=" + (push.stderr or push.stdout).strip())
        return 1

    print(f"CENTRAL_HOLD_SYNC=ok newly_seen={len(discovered)} total_hold={len(merged)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
