#!/usr/bin/env python3
"""Automated publish of com.fri3dcamp.fri3dfriends to badgehub.eu via API v3.

Builds a deterministic .mpk from app/com.fri3dcamp.fri3dfriends (same recipe
as the README "Build & publish" section), uploads it plus the icon, updates
the draft metadata (version + executable name kept in sync with
MANIFEST.JSON), and publishes the draft as a new revision.

Credentials: ~/.claude/secrets/badgehub.env (BADGEHUB_API_TOKEN,
BADGEHUB_PROJECT_SLUG). Not stored in this repo.

Usage: python3 tools/publish_badgehub.py [--dry-run]
"""
import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, "app")
FULLNAME = "com.fri3dcamp.fri3dfriends"
APP_SRC = os.path.join(APP_DIR, FULLNAME)
DIST_DIR = os.path.join(REPO_ROOT, "dist")
SECRETS_PATH = os.path.expanduser("~/.claude/secrets/badgehub.env")
API_BASE = "https://badgehub.eu/api/v3"


def load_secrets():
    env = {}
    with open(SECRETS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    return env


def read_manifest():
    with open(os.path.join(APP_SRC, "MANIFEST.JSON")) as f:
        return json.load(f)


def build_mpk(version):
    os.makedirs(DIST_DIR, exist_ok=True)
    mpk_name = f"{FULLNAME}_{version}.mpk"
    mpk_path = os.path.join(DIST_DIR, mpk_name)

    subprocess.run(["rm", "-rf",
                     os.path.join(APP_SRC, "__pycache__"),
                     os.path.join(APP_SRC, ".pytest_cache")], check=True)
    subprocess.run(["find", APP_SRC, "-exec", "touch", "-t",
                     "202501010000.00", "{}", ";"], check=True)

    if os.path.exists(mpk_path):
        os.remove(mpk_path)

    # MPOS validates the archive layout on extract: the first entry in the ZIP
    # stream must be the top-level directory FULLNAME/, and it must be the only
    # top-level entry. Anything else is rejected with a download/install error.
    # So `find` must be given a RELATIVE path (run from APP_DIR) -- an absolute
    # one leaves the whole host path baked into every archive entry (zip only
    # strips the leading "/"), which produced packages rooted at "home/" or
    # "tmp/" that no badge could install.
    find_dirs = subprocess.run(["find", FULLNAME, "-type", "d"],
                                capture_output=True, text=True, check=True,
                                cwd=APP_DIR).stdout
    find_files = subprocess.run(["find", FULLNAME, "-type", "f",
                                  "!", "-name", "config.json",
                                  "!", "-name", "*.tmp.*"],
                                 capture_output=True, text=True, check=True,
                                 cwd=APP_DIR).stdout
    entries = sorted((find_dirs + find_files).splitlines())

    env = dict(os.environ, TZ="CET")
    zip_proc = subprocess.run(
        # No -r: the entry list is already the full, filtered tree, and -r would
        # recurse into the top-level dir entry and re-add the excluded files
        # (that is how config.json ended up inside the 0.11.22 package).
        ["zip", "-X", "-0", mpk_path, "-@"],
        input="\n".join(entries), text=True, cwd=APP_DIR,
        capture_output=True, env=env,
    )
    if zip_proc.returncode != 0:
        print(zip_proc.stdout, zip_proc.stderr, file=sys.stderr)
        raise RuntimeError("zip failed")

    verify_mpk_layout(mpk_path)
    return mpk_path, mpk_name


def verify_mpk_layout(mpk_path):
    """Fail loudly if the package would be rejected on the badge."""
    import zipfile

    with zipfile.ZipFile(mpk_path) as z:
        names = z.namelist()
    if not names:
        raise RuntimeError("mpk is empty")
    if names[0] != f"{FULLNAME}/":
        raise RuntimeError(
            f"first ZIP entry is {names[0]!r}, must be {FULLNAME + '/'!r}")
    tops = {n.split("/", 1)[0] for n in names}
    if tops != {FULLNAME}:
        raise RuntimeError(f"archive has extra top-level entries: {sorted(tops)}")
    if f"{FULLNAME}/MANIFEST.JSON" not in names:
        raise RuntimeError("MANIFEST.JSON missing from the package")
    print(f"Layout OK: {len(names)} entries, all under {FULLNAME}/")


# Python's urllib gets a 403 (Cloudflare bot-management, error 1010) on POST
# to badgehub.eu even with a custom User-Agent; curl is unaffected. Shell out
# to curl for all requests rather than maintaining two code paths.
def curl(args, expect_json=True):
    with tempfile.NamedTemporaryFile(prefix="badgehub_body_", delete=False) as body_f:
        body_path = body_f.name
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", body_path, "-w", "%{http_code}", *args],
            capture_output=True, text=True, check=True,
        )
        status = int(result.stdout.strip())
        with open(body_path, "rb") as f:
            raw = f.read()
    finally:
        os.remove(body_path)
    if not expect_json or not raw:
        return status, raw.decode(errors="replace") if raw else None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw.decode(errors="replace")


def api_request(method, path, token, data=None, is_json=False):
    url = f"{API_BASE}{path}"
    args = ["-X", method, url, "-H", f"badgehub-api-token: {token}"]
    if is_json and data is not None:
        args += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    return curl(args)


def upload_file(path, dest_filename, token):
    url = f"{API_BASE}/projects/{SLUG}/draft/files/{dest_filename}"
    args = ["-X", "POST", url, "-H", f"badgehub-api-token: {token}",
            "-F", f"file=@{path};filename={dest_filename}"]
    return curl(args)


def main():
    dry_run = "--dry-run" in sys.argv

    secrets = load_secrets()
    token = secrets["BADGEHUB_API_TOKEN"]
    global SLUG
    SLUG = secrets.get("BADGEHUB_PROJECT_SLUG", FULLNAME)

    manifest = read_manifest()
    version = manifest["version"]
    print(f"Building {FULLNAME} v{version} ...")
    mpk_path, mpk_name = build_mpk(version)
    print(f"Built {mpk_path} ({os.path.getsize(mpk_path)} bytes)")

    metadata = {
        "name": manifest["name"],
        "description": manifest["short_description"],
        "long_description": manifest["long_description"],
        "author": manifest["publisher"],
        "git_url": "https://github.com/steemandavid/fri3d-friends",
        "icon_map": {"64x64": "icon-64x64.png"},
        "license_type": "MIT",
        "version": version,
        "badges": ["mpos_api_0"],
        "application": [{"executable": mpk_name}],
    }

    if dry_run:
        print("--dry-run: skipping cleanup/upload/publish. Would upload:")
        print(f"  {mpk_name}")
        print("  icon-64x64.png")
        print(json.dumps(metadata, indent=2))
        return

    status, draft = api_request("GET", f"/projects/{SLUG}/draft", token)
    if status == 200:
        stale_mpks = [f["full_path"] for f in draft.get("version", {}).get("files", [])
                      if f["full_path"].endswith(".mpk") and f["full_path"] != mpk_name]
        for stale in stale_mpks:
            print(f"Deleting stale {stale} ...")
            status, resp = api_request("DELETE", f"/projects/{SLUG}/draft/files/{stale}", token)
            if status not in (200, 204):
                print(f"FAILED deleting {stale}: HTTP {status} {resp}", file=sys.stderr)
                sys.exit(1)

    print(f"Uploading {mpk_name} ...")
    status, resp = upload_file(mpk_path, mpk_name, token)
    if status not in (200, 204):
        print(f"FAILED uploading mpk: HTTP {status} {resp}", file=sys.stderr)
        sys.exit(1)

    icon_src = os.path.join(APP_SRC, "icon_64x64.png")
    print("Uploading icon-64x64.png ...")
    status, resp = upload_file(icon_src, "icon-64x64.png", token)
    if status not in (200, 204):
        print(f"FAILED uploading icon: HTTP {status} {resp}", file=sys.stderr)
        sys.exit(1)

    print("Updating draft metadata ...")
    status, resp = api_request("PATCH", f"/projects/{SLUG}/draft/metadata",
                                token, data=metadata, is_json=True)
    if status not in (200, 204):
        print(f"FAILED updating metadata: HTTP {status} {resp}", file=sys.stderr)
        sys.exit(1)

    print("Publishing draft ...")
    status, resp = api_request("PATCH", f"/projects/{SLUG}/publish", token)
    if status not in (200, 204):
        print(f"FAILED publishing: HTTP {status} {resp}", file=sys.stderr)
        sys.exit(1)

    status, project = api_request("GET", f"/projects/{SLUG}", token)
    print(f"Published. latest_revision={project.get('latest_revision')} version={version}")
    print(f"https://badgehub.eu/page/project/{SLUG}/edit")


if __name__ == "__main__":
    main()
