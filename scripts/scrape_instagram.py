"""Scrape Instagram posts on-demand.

Two modes per account, decided automatically:
- BOOTSTRAP: account has no history yet → fetch last 30 posts to build baseline
- INCREMENTAL: account has history → fetch posts since last scrape only

Scrapes are triggered manually (via `./run.sh` or Apps Script "지금 동기화" button),
NOT on a daily schedule. This keeps Apify costs low.

Usage:
    python scrape_instagram.py [--limit-accounts N] [--force-bootstrap]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apify_client import ApifyClient

import config
import account_history

ACCOUNT_ACTOR = "apify/instagram-post-scraper"

# Bootstrap depth (per new account, one-time)
BOOTSTRAP_POSTS = 30


def _now_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_n_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _route_accounts(accounts: list) -> tuple[list, list]:
    """Split accounts into (bootstrap, incremental) lists based on history."""
    bootstrap, incremental = [], []
    for a in accounts:
        if account_history.is_new_account(a.handle):
            bootstrap.append(a)
        else:
            incremental.append(a)
    return bootstrap, incremental


def _scrape_apify(client: ApifyClient, handles: list[str], days_back: int, limit: int) -> list[dict]:
    """Run Apify post scraper on a batch of handles. Returns raw post items."""
    if not handles:
        return []
    print(f"[apify] scraping {len(handles)} accounts (last {days_back}d, max {limit}/acct)")
    print(f"[apify] handles: {', '.join('@' + h for h in handles)}")

    run_input = {
        "username": handles,
        "resultsLimit": limit,
        "onlyPostsNewerThan": _date_n_days_ago(days_back),
        "skipPinnedPosts": False,
    }
    run = client.actor(ACCOUNT_ACTOR).call(run_input=run_input, timeout_secs=15 * 60)
    if not run:
        raise RuntimeError(f"Apify {ACCOUNT_ACTOR} failed")
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"[apify] returned {len(items)} items")
    return items


def _group_by_owner(items: list[dict]) -> dict[str, list[dict]]:
    """Group raw Apify post items by owner username."""
    out: dict[str, list[dict]] = {}
    for it in items:
        if it.get("error"):
            owner = (it.get("inputUrl", "").rstrip("/").split("/")[-1] or "").lstrip("@").lower()
            print(f"  [error] @{owner}: {it.get('errorDescription', 'unknown')}", file=sys.stderr)
            continue
        owner = (
            it.get("ownerUsername")
            or (it.get("owner") or {}).get("username", "")
        ).lower()
        if owner:
            out.setdefault(owner, []).append(it)
    return out


def scrape(
    limit_accounts: int | None = None,
    force_bootstrap: bool = False,
) -> dict:
    """Run a full scrape. Routes new accounts → bootstrap, existing → incremental.

    Returns summary: {bootstrapped: N, incremental: N, posts_added: N}.
    """
    if not config.APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN not set in .env")

    accounts = config.load_accounts()
    if limit_accounts:
        accounts = accounts[:limit_accounts]
    if not accounts:
        raise RuntimeError("No active seed accounts. Add to '시드 계정' tab first.")

    if force_bootstrap:
        bootstrap_accts, incremental_accts = accounts, []
    else:
        bootstrap_accts, incremental_accts = _route_accounts(accounts)

    print(f"[route] bootstrap: {len(bootstrap_accts)} new accounts")
    print(f"[route] incremental: {len(incremental_accts)} existing accounts")

    client = ApifyClient(config.APIFY_TOKEN)
    summary = {"bootstrapped": 0, "incremental": 0, "posts_added": 0, "accounts_with_data": 0}

    # Bootstrap pass: deep fetch for new accounts (one Apify call)
    if bootstrap_accts:
        handles = [a.handle for a in bootstrap_accts]
        items = _scrape_apify(client, handles, days_back=180, limit=BOOTSTRAP_POSTS)
        grouped = _group_by_owner(items)
        for handle, posts in grouped.items():
            account_history.merge_posts(handle, posts)
            account_history.compute_baseline(handle)
            summary["bootstrapped"] += 1
            summary["posts_added"] += len(posts)
            summary["accounts_with_data"] += 1
            print(f"  [bootstrap] @{handle}: {len(posts)} posts → baseline computed")

    # Incremental pass: shallow fetch for existing accounts
    if incremental_accts:
        handles = [a.handle for a in incremental_accts]
        items = _scrape_apify(client, handles, days_back=config.DAYS_BACK, limit=config.POSTS_PER_ACCOUNT)
        grouped = _group_by_owner(items)
        for handle, posts in grouped.items():
            before = len(account_history.load_history(handle)["posts"])
            account_history.merge_posts(handle, posts)
            after = len(account_history.load_history(handle)["posts"])
            account_history.compute_baseline(handle)
            new_count = after - before
            summary["incremental"] += 1
            summary["posts_added"] += new_count
            summary["accounts_with_data"] += 1
            print(f"  [incr] @{handle}: +{new_count} new posts (total {after})")

    print(f"[done] {summary}")
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", "--limit-accounts", type=int, dest="limit_accounts",
                   help="Limit to first N accounts (PoC)")
    p.add_argument("--force-bootstrap", action="store_true", dest="force_bootstrap",
                   help="Force bootstrap mode for ALL accounts (re-fetch deep history)")
    args = p.parse_args()
    try:
        scrape(args.limit_accounts, args.force_bootstrap)
    except Exception as e:
        print(f"[scrape] ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
