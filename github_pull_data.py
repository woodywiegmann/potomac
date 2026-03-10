"""
Pull and store data via GitHub API (no Git CLI required).

Pull:
  python github_pull_data.py                    # list your repos
  python github_pull_data.py --repo owner/name  # repo details + recent commits
  python github_pull_data.py --repo owner/name --file path/to/file.py
  python github_pull_data.py --out repos.json

Store:
  python github_pull_data.py --store-gist my-notes.txt --in data.json   # create Gist from file
  python github_pull_data.py --store-gist "note" --content "raw text"    # Gist from inline text
  python github_pull_data.py --store-file owner/repo path/in/repo.txt --in file.txt  # create/update file in repo
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    raise SystemExit("pip install requests")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_BASE = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("Set GITHUB_TOKEN to pull data (create at: https://github.com/settings/tokens)")
        print("  PowerShell: $env:GITHUB_TOKEN = \"ghp_...\"")
        sys.exit(1)
    return token


def auth_headers(token: str) -> dict:
    h = HEADERS.copy()
    h["Authorization"] = f"Bearer {token}"
    return h


def get(path: str, token: str, params: dict | None = None) -> dict | list:
    url = f"{API_BASE}{path}"
    r = requests.get(url, headers=auth_headers(token), params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _request(method: str, path: str, token: str, json_body: dict) -> dict:
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=auth_headers(token), json=json_body, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def list_repos(token: str, org: str | None = None, per_page: int = 30) -> list:
    if org:
        path = f"/orgs/{org}/repos"
    else:
        path = "/user/repos"
    data = get(path, token, {"per_page": per_page, "sort": "updated"})
    return data if isinstance(data, list) else [data]


def repo_details(token: str, repo: str) -> dict:
    path = f"/repos/{repo}"
    return get(path, token)


def repo_commits(token: str, repo: str, per_page: int = 20) -> list:
    path = f"/repos/{repo}/commits"
    return get(path, token, {"per_page": per_page})


def repo_contents(token: str, repo: str, path: str = "") -> list | dict:
    """ path empty = root; returns list of files/dirs or dict with 'content' for file """
    api_path = f"/repos/{repo}/contents/{path}" if path else f"/repos/{repo}/contents"
    return get(api_path, token)


def file_content(token: str, repo: str, file_path: str) -> str:
    """ Raw file content (decoded). """
    data = repo_contents(token, repo, file_path)
    if isinstance(data, list):
        raise ValueError(f"{file_path} is a directory")
    enc = data.get("encoding")
    content = data.get("content")
    if enc == "base64" and content:
        return base64.b64decode(content).decode("utf-8", errors="replace")
    return content or ""


# --- Store (write) ---


def create_gist(token: str, description: str, files: dict[str, str], public: bool = False) -> dict:
    """Create a Gist. files = { "filename.txt": "content" }. Returns Gist metadata including html_url."""
    body = {"description": description, "public": public, "files": {k: {"content": v} for k, v in files.items()}}
    return _request("POST", "/gists", token, body)


def create_or_update_file(token: str, repo: str, path: str, content: str, message: str, sha: str | None = None) -> dict:
    """Create or update a file in repo. If sha is provided, updates; otherwise creates."""
    body = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii")}
    if sha:
        body["sha"] = sha
    return _request("PUT", f"/repos/{repo}/contents/{path}", token, body)


def run_list_repos(token: str, org: str | None, out_path: str | None) -> None:
    repos = list_repos(token, org=org)
    rows = []
    for r in repos:
        rows.append({
            "name": r.get("full_name"),
            "private": r.get("private"),
            "description": (r.get("description") or "")[:200],
            "updated_at": r.get("updated_at"),
            "default_branch": r.get("default_branch"),
            "language": r.get("language"),
        })
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
        print(f"Wrote {len(rows)} repos to {out_path}")
    else:
        for row in rows:
            print(row["name"], "|", row.get("language") or "-", "|", row["updated_at"])


def run_repo_details(token: str, repo: str, out_path: str | None, file_path: str | None) -> None:
    if file_path:
        content = file_content(token, repo, file_path)
        if out_path:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Wrote file content to {out_path}")
        else:
            print(content)
        return

    details = repo_details(token, repo)
    commits = repo_commits(token, repo, per_page=10)
    payload = {
        "repo": details.get("full_name"),
        "description": details.get("description"),
        "default_branch": details.get("default_branch"),
        "updated_at": details.get("updated_at"),
        "clone_url": details.get("clone_url"),
        "recent_commits": [
            {"sha": c.get("sha")[:7], "message": (c.get("commit", {}).get("message") or "").split("\n")[0], "date": c.get("commit", {}).get("author", {}).get("date")}
            for c in commits
        ],
    }
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"Wrote repo data to {out_path}")
    else:
        print(json.dumps(payload, indent=2))


def run_store_gist(token: str, gist_filename: str, content: str | None, in_path: str | None, description: str, public: bool) -> None:
    if in_path:
        with open(in_path, "r", encoding="utf-8") as f:
            content = f.read()
    if content is None:
        print("Provide --content 'text' or --in path/to/file")
        sys.exit(1)
    result = create_gist(token, description, {gist_filename: content}, public=public)
    print("Created Gist:", result.get("html_url", result.get("id", "?")))


def run_store_file(token: str, repo: str, path: str, in_path: str, message: str) -> None:
    with open(in_path, "r", encoding="utf-8") as f:
        content = f.read()
    sha = None
    try:
        existing = repo_contents(token, repo, path)
        if isinstance(existing, dict) and existing.get("sha"):
            sha = existing["sha"]
    except Exception:
        pass
    result = create_or_update_file(token, repo, path, content, message, sha=sha)
    print("Stored:", result.get("content", {}).get("html_url", path))


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull or store data via GitHub API")
    ap.add_argument("--repo", "-r", help="Repo as owner/name (e.g. octocat/Hello-World)")
    ap.add_argument("--file", "-f", help="Path to file in repo (with --repo)")
    ap.add_argument("--org", "-o", help="List repos for this org (default: your user)")
    ap.add_argument("--out", help="Export to this JSON/text file")

    ap.add_argument("--store-gist", metavar="FILENAME", help="Create a Gist with this filename")
    ap.add_argument("--content", help="Inline content for --store-gist")
    ap.add_argument("--in", dest="in_path", metavar="FILE", help="Read content from file (for --store-gist or --store-file)")
    ap.add_argument("--store-file", metavar="REPO/PATH", help="Store file in repo (e.g. owner/repo/data/note.txt); use with --in")
    ap.add_argument("--message", "-m", default="Update from github_pull_data.py", help="Commit message for --store-file")
    ap.add_argument("--public-gist", action="store_true", help="Make Gist public (default: secret)")
    args = ap.parse_args()

    token = get_token()

    if args.store_gist:
        run_store_gist(
            token,
            args.store_gist,
            args.content,
            args.in_path,
            description=args.store_gist,
            public=args.public_gist,
        )
        return
    if args.store_file:
        if not args.in_path:
            print("--store-file requires --in path/to/source/file")
            sys.exit(1)
        parts = args.store_file.strip().split("/", 2)  # owner/repo/path/to/file
        if len(parts) < 3:
            print("--store-file must be owner/repo/path/to/file (e.g. woodywiegmann/myrepo/data/note.txt)")
            sys.exit(1)
        repo = f"{parts[0]}/{parts[1]}"
        file_path = parts[2]
        run_store_file(token, repo, file_path, args.in_path, args.message)
        return

    if args.repo:
        run_repo_details(token, args.repo.strip(), args.out, args.file)
    else:
        run_list_repos(token, args.org, args.out)


if __name__ == "__main__":
    main()
