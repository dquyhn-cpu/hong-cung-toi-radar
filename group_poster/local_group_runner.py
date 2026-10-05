import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
POSTER = HERE / "group_poster.py"
DEFAULT_JOB = HERE / "local_jobs" / "current_group_job.json"
OUTPUT = HERE / "output"
RUNTIME = HERE / "local_jobs" / "_runtime_group_package.json"

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def resolve_groups(job):
    urls = list(job.get("group_urls") or [])
    if urls:
        return urls
    registry_path = Path(job.get("registry_path") or "")
    if not str(registry_path):
        raise SystemExit("JOB_MISSING_REGISTRY_PATH")
    if not registry_path.is_absolute():
        registry_path = HERE / registry_path
    registry = load_json(registry_path)
    groups = registry.get("groups") or []
    include_ids = set(job.get("include_group_ids") or [])
    exclude_ids = set(job.get("exclude_group_ids") or [])
    out = []
    for g in groups:
        gid = str(g.get("id") or "")
        if include_ids and gid not in include_ids:
            continue
        if gid in exclude_ids:
            continue
        url = str(g.get("url") or "").strip()
        if url:
            out.append(url)
    return out

def main():
    ap = argparse.ArgumentParser(description="Run current HCT group publishing job locally.")
    ap.add_argument("image", nargs="?", help="Drag a local JPG/PNG/WEBP onto RUN_GROUP_POSTER.bat")
    ap.add_argument("--job", default=str(DEFAULT_JOB))
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    job_path = Path(args.job)
    if not job_path.exists():
        raise SystemExit(f"JOB_NOT_FOUND: {job_path}")
    job = load_json(job_path)

    image = args.image
    if not image:
        image = input("Keo file anh vao day (hoac dan duong dan), roi Enter: ").strip().strip('"')
    image_path = Path(image)
    if not image_path.exists():
        raise SystemExit(f"IMAGE_NOT_FOUND: {image_path}")

    package = dict(job)
    package["image_path"] = str(image_path.resolve())
    package.pop("image_url", None)
    package.pop("image_asset_name", None)
    package["group_urls"] = resolve_groups(job)
    package["use_registry"] = False

    if not package["group_urls"]:
        raise SystemExit("NO_TARGET_GROUPS")

    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"LOCAL_JOB_READY category={package.get('category','')} groups={len(package['group_urls'])} mode={package.get('post_mode')}")
    print(f"IMAGE={image_path.resolve()}")

    cmd = [sys.executable, str(POSTER), "--package", str(RUNTIME), "--output-dir", str(OUTPUT)]
    if not args.preview:
        cmd.append("--confirm-post")
    return subprocess.call(cmd, cwd=str(HERE))

if __name__ == "__main__":
    raise SystemExit(main())
