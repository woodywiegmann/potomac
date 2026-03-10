# GitHub connection – COO briefing

Two ways to “connect GitHub here”: (1) **pull data** via the API (no Git installed), and (2) **link this folder to a repo** (push/pull code; requires Git).

---

## 1. Pull data (script in this project)

The script `github_pull_data.py` uses the **GitHub REST API** so you can list repos, get repo details, recent commits, and file contents **without installing Git**.

### Create a token

1. Go to **https://github.com/settings/tokens**
2. **Generate new token (classic)** or **Fine-grained**
   - Classic: enable scope `repo` (and `read:org` if you need org repos).
   - Fine-grained: give “Contents” and “Metadata” read for the repos you care about.
3. Copy the token (e.g. `ghp_...`).

### Use the token in this project

**PowerShell (current session):**

```powershell
$env:GITHUB_TOKEN = "ghp_your_token_here"
```

**Permanent (user env var):**

- Win: Settings → System → About → Advanced system settings → Environment variables → User → New → `GITHUB_TOKEN` = `ghp_...`

### Run the script

From the Potomac folder:

```powershell
cd "C:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac"
python github_pull_data.py
```

- **List your repos:** `python github_pull_data.py`
- **List org repos:** `python github_pull_data.py --org YourOrgName`
- **One repo (details + recent commits):** `python github_pull_data.py --repo owner/repo-name`
- **One file’s contents:** `python github_pull_data.py --repo owner/repo-name --file path/to/file.py`
- **Export to JSON:** `python github_pull_data.py --out repos.json` or `--repo owner/name --out repo.json`

No GitHub App is required; a personal access token is enough.

### Store information (same script)

You can **store** data on GitHub in two ways:

**1. Gists** (quick snippets; no repo needed; default is secret):

```powershell
# From a local file (e.g. JSON, CSV, notes)
python github_pull_data.py --store-gist notes.json --in my_data.json

# Inline text
python github_pull_data.py --store-gist snippet.txt --content "Your text here"

# Public Gist
python github_pull_data.py --store-gist notes.txt --in notes.txt --public-gist
```

**2. A file in a repo** (good for ongoing storage in a dedicated repo):

```powershell
# Create repo on GitHub first (e.g. woodywiegmann/potomac-data), then:
python github_pull_data.py --store-file woodywiegmann/potomac-data data/export.json --in export.json -m "Add export"
```

Token needs **repo** scope (classic token includes Gist creation).

---

## 2. Connect this folder to a GitHub repo (push/pull code)

To use normal Git (clone, commit, push, pull) from this folder you need **Git** and a **remote** pointing at your repo.

### Install Git (if needed)

- **winget:** `winget install Git.Git`
- Or: https://git-scm.com/download/win  
After install, restart the terminal (or Cursor) so `git` is on PATH.

### Create a repo on GitHub

1. GitHub.com → **New repository**
2. Name it (e.g. `potomac-research`), leave “Initialize with README” **unchecked** if this folder already has files.
3. Copy the repo URL (e.g. `https://github.com/YourUser/potomac-research.git`).

### Link this folder to that repo

In PowerShell, from the Potomac folder:

```powershell
cd "C:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac"
git init
git remote add origin https://github.com/YourUser/potomac-research.git
```

First push (after adding and committing):

```powershell
git add .
git commit -m "Initial commit: Potomac research and agents"
git branch -M main
git push -u origin main
```

If GitHub prompts for login, use **GitHub CLI** or **Personal Access Token** as password:

- **GitHub CLI:** `winget install GitHub.cli` then `gh auth login` (easiest).
- **Token:** same token as above; when Git asks for password, paste the token.

---

## Summary

| Goal                         | What to do |
|-----------------------------|------------|
| Pull repo/file data into PC | Use `GITHUB_TOKEN` + `github_pull_data.py` (no Git) |
| Push this project to GitHub | Install Git → create repo → `git init` → `remote add` → add, commit, push |

If you tell me whether you prefer “API data pull only” or “full Git connect,” I can give the exact next command for your machine (and, if you want, extend the script to pull specific data into Excel/JSON).
