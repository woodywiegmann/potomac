# How to upload this codebase to GitHub

Use this when you're on the machine that **has** the full Potomac folder and you want to push everything to a GitHub repo (e.g. before switching computers). No Git install required — uses the GitHub API.

## 1. Get a token

- Go to **https://github.com/settings/tokens**
- Create a token (classic) with **repo** scope (full control of private repos).
- Copy the token (`ghp_...`).

## 2. Set the token and run the upload

**PowerShell:**

```powershell
cd "C:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac"
$env:GITHUB_TOKEN = "ghp_your_token_here"
python upload_to_github.py
```

This will:

- Create a repo **woodywiegmann/potomac** if it doesn’t exist (public by default).
- Walk the Potomac folder and upload every relevant file (`.py`, `.md`, `.mdc`, `.yaml`, `.json`, `.pine`, `.txt`, etc.).
- Skip: `.git`, `__pycache__`, `venv`, `.env`, `.xlsx`, `.pdf`, and files larger than ~1 MB.

## 3. Options

| Option | Meaning |
|--------|--------|
| `--repo owner/name` | Use a different repo (e.g. `--repo woodywiegmann/john-woodside-inc`). |
| `--private` | Create the repo as private. |
| `--skip-existing` | Don’t overwrite files that already exist in the repo (faster for re-runs). |
| `--description "..."` | Set the repo description. |

**Examples:**

```powershell
python upload_to_github.py --repo woodywiegmann/john-woodside-inc --private
python upload_to_github.py --repo woodywiegmann/potomac --skip-existing
```

## 4. After upload

- On the **new computer**: clone the repo (`git clone https://github.com/woodywiegmann/potomac.git`) or download as ZIP from the repo page.
- Open the folder in Cursor and follow **README.md** for setup (pip install, env vars, how to run each employee).

## 5. What gets uploaded

- All Cursor rules (`.cursor/rules/*.mdc`) and skills (`.cursor/skills/**/SKILL.md`).
- All agents: `agents/daily_wrap/`, `agents/voice_clone/`, `agents/style_corpus/`, `agents/transcribe_podcasts.py`.
- All Python scripts, configs, briefs, and docs in the repo root and subfolders.
- **Not** uploaded: `.env`, `.git`, `venv`, `__pycache__`, `.xlsx`, `.pdf`, and files &gt; ~1 MB (e.g. very large data files). Add those locally on the new machine or store secrets in env vars.
