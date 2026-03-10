"""
Upload the entire Potomac codebase to a GitHub repo via API (no Git CLI).
Creates the repo if it doesn't exist, then uploads every relevant file.

Usage:
  $env:GITHUB_TOKEN = "ghp_..."
  python upload_to_github.py
  python upload_to_github.py --repo john-woodside-inc --private
  python upload_to_github.py --repo potomac-research --skip-existing
"""

import base64
import os
import sys

try:
    import requests
except ImportError:
    raise SystemExit("pip install requests")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_BASE = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
MAX_FILE_BYTES = 950_000  # stay under 1MB for API comfort
SKIP_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules"}
SKIP_EXTENSIONS = {".pyc", ".xlsx", ".zip", ".pdf"}
SKIP_FILES = {".env"}  # never upload secrets


def get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("Set GITHUB_TOKEN (https://github.com/settings/tokens, scope: repo)")
        sys.exit(1)
    return token


def auth_headers(token: str) -> dict:
    h = HEADERS.copy()
    h["Authorization"] = f"Bearer {token}"
    return h


def get(path: str, token: str, params: dict | None = None) -> dict | list:
    url = f"{API_BASE}{path}"
    r = requests.get(url, headers=auth_headers(token), params=params or {}, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def post(path: str, token: str, json_body: dict) -> dict:
    url = f"{API_BASE}{path}"
    r = requests.post(url, headers=auth_headers(token), json=json_body, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def put(path: str, token: str, json_body: dict) -> dict:
    url = f"{API_BASE}{path}"
    r = requests.put(url, headers=auth_headers(token), json=json_body, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def get_user_login(token: str) -> str:
    u = get("/user", token)
    if not u:
        raise RuntimeError("Could not get current user")
    return u.get("login", "")


def create_repo(token: str, name: str, description: str, private: bool) -> dict:
    body = {"name": name, "description": description, "private": private}
    return post("/user/repos", token, body)


def ensure_repo(token: str, repo_full_name: str, description: str, private: bool) -> None:
    existing = get(f"/repos/{repo_full_name}", token)
    if existing:
        print(f"Repo {repo_full_name} already exists.")
        return
    owner, name = repo_full_name.split("/", 1)
    create_repo(token, name, description, private)
    print(f"Created repo {repo_full_name}")


def collect_files(root: str) -> list[tuple[str, str]]:
    """Yield (relative_path_forward_slash, absolute_path)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        for f in filenames:
            if f in SKIP_FILES:
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in SKIP_EXTENSIONS:
                continue
            abspath = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(abspath)
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                print(f"Skip (too large): {os.path.join(rel_dir, f)}")
                continue
            rel = os.path.join(rel_dir, f) if rel_dir else f
            rel = rel.replace("\\", "/")
            out.append((rel, abspath))
    return out


def upload_file(token: str, repo: str, path: str, content_bytes: bytes, message: str, sha: str | None) -> None:
    content_b64 = base64.b64encode(content_bytes).decode("ascii")
    body = {"message": message, "content": content_b64}
    if sha:
        body["sha"] = sha
    put(f"/repos/{repo}/contents/{path}", token, body)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Upload Potomac codebase to GitHub")
    ap.add_argument("--repo", default="woodywiegmann/potomac", help="Full name: owner/repo")
    ap.add_argument("--description", default="John Woodside Inc — Potomac research, agents, and scripts", help="Repo description")
    ap.add_argument("--private", action="store_true", help="Create as private repo")
    ap.add_argument("--skip-existing", action="store_true", help="Skip files that already exist (no overwrite)")
    args = ap.parse_args()

    token = get_token()
    login = get_user_login(token)
    repo_name = args.repo
    if "/" not in repo_name:
        repo_name = f"{login}/{repo_name}"

    ensure_repo(token, repo_name, args.description, args.private)

    files = collect_files(SCRIPT_DIR)
    print(f"Uploading {len(files)} files to {repo_name}...")
    done = 0
    for rel, abspath in files:
        try:
            with open(abspath, "rb") as f:
                content = f.read()
        except OSError as e:
            print(f"Read error {rel}: {e}")
            continue
        try:
            existing = get(f"/repos/{repo_name}/contents/{rel}", token)
            sha = existing.get("sha") if isinstance(existing, dict) else None
            if args.skip_existing and sha:
                done += 1
                continue
        except Exception:
            sha = None
        try:
            upload_file(token, repo_name, rel, content, f"Add/update {rel}", sha)
            done += 1
            print(f"  {rel}")
        except requests.HTTPError as e:
            print(f"  FAIL {rel}: {e.response.status_code} {e.response.text[:200]}")
    print(f"Done. {done} files uploaded/updated.")


if __name__ == "__main__":
    main()
