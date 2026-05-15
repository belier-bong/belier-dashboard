"""Config: env vars + paths. Repo-only — no Google Sheets dependency."""
from __future__ import annotations

import json
import os
from pathlib import Path

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent

# Env vars (from .env locally OR GitHub Secrets in Actions)
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
APIFY_ACTOR_ID = os.environ.get("APIFY_ACTOR_ID", "apify/instagram-post-scraper")
POSTS_PER_ACCOUNT = int(os.environ.get("POSTS_PER_ACCOUNT", "10"))
DAYS_BACK = int(os.environ.get("DAYS_BACK", "30"))
BOOTSTRAP_POSTS = int(os.environ.get("BOOTSTRAP_POSTS", "30"))
BOOTSTRAP_DAYS = int(os.environ.get("BOOTSTRAP_DAYS", "180"))

# Paths (relative to repo root)
ACCOUNTS_FILE = REPO_ROOT / "accounts.json"
HISTORY_DIR = REPO_ROOT / "data" / "account_history"
IMAGES_DIR = REPO_ROOT / "images"
DASHBOARD_OUT = REPO_ROOT / "index.html"

# Ensure dirs exist
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# --- Account loading ---------------------------------------------------------

def load_accounts() -> list[dict]:
    """Read accounts.json → list of active account dicts.

    Sorted: category, priority, handle.
    Returns list of dicts with keys: handle, category, priority, active, region, note.
    """
    if not ACCOUNTS_FILE.exists():
        return []
    with ACCOUNTS_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("accounts", []) if isinstance(data, dict) else data
    active = [a for a in raw if a.get("active", True)]
    active.sort(key=lambda a: (a.get("category", ""), a.get("priority", 99), a.get("handle", "")))
    return active


def validate_env() -> list[str]:
    """Return list of missing env vars."""
    issues = []
    if not APIFY_TOKEN or APIFY_TOKEN.startswith("apify_api_xxx"):
        issues.append("APIFY_TOKEN")
    if not ACCOUNTS_FILE.exists():
        issues.append(f"accounts.json missing at {ACCOUNTS_FILE}")
    return issues


if __name__ == "__main__":
    print(f"REPO_ROOT: {REPO_ROOT}")
    print(f"ACCOUNTS_FILE: {ACCOUNTS_FILE}")
    print(f"HISTORY_DIR: {HISTORY_DIR}")
    print(f"IMAGES_DIR: {IMAGES_DIR}")
    print()
    issues = validate_env()
    if issues:
        print("ENV ISSUES:", issues)
    else:
        accounts = load_accounts()
        print(f"Active accounts: {len(accounts)}")
        for a in accounts:
            print(f"  [{a.get('priority', '?')}] @{a['handle']} ({a.get('category', '')}) — {a.get('region', '')}")
