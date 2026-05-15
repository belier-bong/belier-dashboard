"""Download Instagram thumbnails locally so they survive CDN expiration.

Walks all data/account_history/@*.json files, downloads any post images
that don't have a local copy yet, and updates the history with `_local_image`
paths. Idempotent — only fetches missing images.

Usage:
    python download_images.py [--concurrency N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import re
import sys

import requests

import config
import account_history

IMAGES_DIR = config.IMAGES_DIR
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _post_id_from_url(url: str) -> str:
    m = re.search(r"/(?:p|reel|tv)/([^/?#]+)", url)
    if m:
        return m.group(1)
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _download_one(image_url: str, post_id: str) -> tuple[bool, str]:
    """Download one image to images/{post_id}.jpg. Returns (success, path_or_error)."""
    out = IMAGES_DIR / f"{post_id}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return True, str(out.relative_to(config.DATA_DIR))
    try:
        r = requests.get(
            image_url,
            headers={"User-Agent": DEFAULT_UA},
            timeout=15,
            stream=True,
        )
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        total = 0
        with out.open("wb") as f:
            for chunk in r.iter_content(chunk_size=32 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
        if total == 0:
            out.unlink(missing_ok=True)
            return False, "empty response"
        return True, str(out.relative_to(config.DATA_DIR))
    except requests.RequestException as e:
        return False, str(e)[:100]


def download_all(concurrency: int = 8) -> dict:
    """Walk all account histories, download missing images, save back to history."""
    handles = account_history.list_handles()
    if not handles:
        print("[images] no account histories — run scrape first")
        return {"total": 0, "success": 0, "skipped": 0, "failed": 0}

    # Collect all (handle, url, image_url, post_id) tuples that need downloading
    targets = []
    for handle in handles:
        history = account_history.load_history(handle)
        for url, post in history["posts"].items():
            if post.get("_local_image"):
                local_path = config.DATA_DIR / post["_local_image"]
                if local_path.exists() and local_path.stat().st_size > 0:
                    continue  # already downloaded
            image_url = post.get("image_url", "")
            if not image_url:
                continue
            post_id = _post_id_from_url(url)
            targets.append((handle, url, image_url, post_id))

    if not targets:
        print(f"[images] nothing to download (all {sum(len(account_history.load_history(h)['posts']) for h in handles)} posts already have local images)")
        return {"total": 0, "success": 0, "skipped": 0, "failed": 0}

    total = len(targets)
    success = 0
    failed = 0
    print(f"[images] {total} images to download (concurrency={concurrency})")

    # Track which posts to update per handle
    updates_per_handle: dict[str, list[tuple[str, str]]] = {}

    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {
            ex.submit(_download_one, image_url, pid): (handle, url, image_url, pid)
            for handle, url, image_url, pid in targets
        }
        for i, fut in enumerate(cf.as_completed(futures), 1):
            handle, url, image_url, pid = futures[fut]
            ok, result = fut.result()
            if ok:
                success += 1
                updates_per_handle.setdefault(handle, []).append((url, result))
            else:
                failed += 1
                if failed <= 5:
                    print(f"[images] fail: {pid} — {result}", file=sys.stderr)
            if i % 25 == 0 or i == total:
                print(f"[images] {i}/{total}... ok={success} fail={failed}")

    # Persist _local_image paths back to histories
    for handle, updates in updates_per_handle.items():
        history = account_history.load_history(handle)
        for url, local_path in updates:
            if url in history["posts"]:
                history["posts"][url]["_local_image"] = local_path
        account_history.save_history(handle, history)

    summary = {
        "total": total,
        "success": success,
        "failed": failed,
        "images_dir": str(IMAGES_DIR),
    }
    print(f"[images] done: {summary}")
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--concurrency", type=int, default=8)
    args = p.parse_args()
    try:
        download_all(args.concurrency)
    except Exception as e:
        print(f"[images] ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
