"""Time-series storage for per-account post history.

Each account gets one JSON file at data/account_history/@{handle}.json:
    {
      "handle": "toteme",
      "first_scraped": "2026-04-23T18:00:00Z",
      "last_scraped": "2026-04-30T18:00:00Z",
      "baseline": {
        "image_median_likes": 5000,
        "video_median_views": 80000,
        "image_count": 23,
        "video_count": 7,
        "computed_at": "2026-04-30T18:00:00Z"
      },
      "posts": {
        "https://instagram.com/p/abc": {
          "url": "...",
          "type": "Image",  # Image / Sidecar / Video
          "likes": 50000,
          "comments": 800,
          "views": 0,
          "posted_at": "2026-04-21T13:43:00Z",
          "caption": "...",
          "image_url": "...",
          "_local_image": "images/abc.jpg",
          "first_seen": "2026-04-23T18:00:00Z",
          "last_seen": "2026-04-30T18:00:00Z"
        },
        ...
      }
    }

Posts are keyed by URL so re-scraping updates the same record (likes can grow).
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import config

HISTORY_DIR = config.HISTORY_DIR
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_handle(h: str) -> str:
    return h.lstrip("@").strip().lower()


def history_path(handle: str) -> Path:
    return HISTORY_DIR / f"@{_normalize_handle(handle)}.json"


def load_history(handle: str) -> dict:
    """Load existing history for an account, or return an empty skeleton."""
    p = history_path(handle)
    if not p.exists():
        return {
            "handle": _normalize_handle(handle),
            "first_scraped": None,
            "last_scraped": None,
            "baseline": None,
            "posts": {},
        }
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def save_history(handle: str, history: dict) -> Path:
    p = history_path(handle)
    with p.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return p


def is_new_account(handle: str) -> bool:
    """True if we've never scraped this account before."""
    return not history_path(handle).exists()


def merge_posts(handle: str, new_posts: list[dict]) -> dict:
    """Merge newly-scraped posts into existing history.

    Each post dict should have at least: url, type, likesCount, commentsCount,
    timestamp, displayUrl. Optional: videoViewCount, caption, _local_image.

    Returns the updated history dict.
    """
    history = load_history(handle)
    now = _now_iso()
    if history["first_scraped"] is None:
        history["first_scraped"] = now
    history["last_scraped"] = now

    posts = history["posts"]
    for raw in new_posts:
        if raw.get("error"):
            continue
        url = raw.get("url") or raw.get("postUrl")
        if not url:
            continue
        existing = posts.get(url)
        record = {
            "url": url,
            "type": raw.get("type", "Image"),
            "likes": int(raw.get("likesCount") or 0),
            "comments": int(raw.get("commentsCount") or 0),
            "views": int(raw.get("videoViewCount") or raw.get("videoPlayCount") or 0),
            "posted_at": raw.get("timestamp", ""),
            "caption": (raw.get("caption") or "")[:500],
            "image_url": raw.get("displayUrl", ""),
            "_local_image": raw.get("_local_image", ""),
            "first_seen": existing["first_seen"] if existing else now,
            "last_seen": now,
        }
        # Preserve previous _local_image if new scrape didn't set it
        if existing and not record["_local_image"] and existing.get("_local_image"):
            record["_local_image"] = existing["_local_image"]
        posts[url] = record

    save_history(handle, history)
    return history


def compute_baseline(handle: str, sample_size: int = 10) -> dict:
    """Compute median likes/views from the last N posts of each type.

    Saves the baseline back to the history file.
    Returns the baseline dict, or None if not enough data.
    """
    history = load_history(handle)
    posts = list(history["posts"].values())
    if len(posts) < 5:
        # Not enough data for a meaningful baseline
        history["baseline"] = None
        save_history(handle, history)
        return None

    # Sort by posted_at desc, take most recent
    posts_sorted = sorted(
        posts, key=lambda p: p.get("posted_at", ""), reverse=True
    )

    images = [p for p in posts_sorted if p["type"] in ("Image", "Sidecar")][:sample_size]
    videos = [p for p in posts_sorted if p["type"] == "Video"][:sample_size]

    baseline = {
        "image_median_likes": (
            int(statistics.median([p["likes"] for p in images])) if images else 0
        ),
        "video_median_views": (
            int(statistics.median([p["views"] for p in videos])) if videos else 0
        ),
        "image_count": len(images),
        "video_count": len(videos),
        "computed_at": _now_iso(),
    }
    history["baseline"] = baseline
    save_history(handle, history)
    return baseline


def list_handles() -> list[str]:
    """Return all account handles we have history for."""
    return [
        p.stem.lstrip("@")
        for p in HISTORY_DIR.glob("@*.json")
    ]
