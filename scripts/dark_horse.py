"""Dark Horse Score (DHS) computation + tier classification.

DHS = Spike × Recency × QualityBonus

Where:
  Spike       = post_metric / account_baseline_metric  (likes for image, views for video)
  Recency     = exp(-days_since_post / 7)              (recent posts weighted more)
  QualityBonus = 1 + (comments / likes × 10)           (high comments = real engagement)

Tier (based purely on Spike for marketer intuitiveness):
  S (전설):    spike >= 10.0
  A (대박):    spike >= 5.0
  B (주목):    spike >= 3.0
  C (살짝):    spike >= 1.5
  HIDDEN:      spike <  1.5  (filtered out, never shown)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

# Spike thresholds for tier classification
TIER_THRESHOLDS = {
    "S": 10.0,
    "A": 5.0,
    "B": 3.0,
    "C": 1.5,
}
TIER_LABELS = {
    "S": ("🏆", "전설", "이 계정 평소 10배 이상 — 거의 안 일어남"),
    "A": ("⭐", "대박", "평소 5~10배 — 명확한 히트, 카피할 가치 있음"),
    "B": ("🔥", "주목", "평소 3~5배 — 평소보다 잘됨"),
    "C": ("✨", "살짝", "평소 1.5~3배 — 약한 신호"),
}

# Hard cap to prevent absurd spikes (a post with 1 baseline post = infinity)
MAX_SPIKE = 50.0

# Minimum likes/views to even consider (filter out noise)
MIN_LIKES_FOR_TIER = 50  # need at least 50 likes to be a "dark horse"


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp like '2026-04-21T13:43:41.000Z'."""
    if not ts:
        return None
    try:
        # Handle Z and timezone offset variants
        cleaned = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def days_since(ts: str) -> Optional[float]:
    """Days between now and a posted_at timestamp. Returns None if unparseable."""
    dt = _parse_timestamp(ts)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    delta = now - dt
    return delta.total_seconds() / 86400


def compute_spike(post: dict, baseline: Optional[dict]) -> float:
    """How many times the account's typical performance is this post?

    Returns 0.0 if baseline missing or post type doesn't match available baseline.
    """
    if not baseline:
        return 0.0
    post_type = post.get("type", "Image")
    if post_type == "Video":
        baseline_metric = baseline.get("video_median_views", 0)
        post_metric = post.get("views", 0)
        # Video fallback to likes if no views available
        if post_metric == 0:
            post_metric = post.get("likes", 0)
            baseline_metric = baseline.get("image_median_likes", 0)
    else:
        baseline_metric = baseline.get("image_median_likes", 0)
        post_metric = post.get("likes", 0)

    if not baseline_metric or baseline_metric < 1:
        return 0.0
    spike = post_metric / baseline_metric
    return min(spike, MAX_SPIKE)


def compute_recency_weight(posted_at: str, half_life_days: float = 7.0) -> float:
    """Exponential decay weight. 1.0 today, 0.5 at 7 days, ~0 at 30 days."""
    days = days_since(posted_at)
    if days is None or days < 0:
        return 1.0
    return math.exp(-days / half_life_days)


def compute_quality_bonus(post: dict) -> float:
    """Comments-to-likes ratio bonus. 1.0 if no engagement, up to ~3.0 for hot debate."""
    likes = post.get("likes") or 0
    comments = post.get("comments") or 0
    if likes < 1:
        return 1.0
    ratio = comments / likes
    return 1.0 + min(ratio * 10, 3.0)  # cap at 4.0 total


def classify_tier(spike: float, post: dict) -> Optional[str]:
    """Map spike → tier letter, or None if below threshold or insufficient signal.

    Returns 'S', 'A', 'B', 'C', or None (HIDDEN).
    """
    # Need minimum absolute engagement to even consider
    metric = post.get("views") if post.get("type") == "Video" else post.get("likes")
    if (metric or 0) < MIN_LIKES_FOR_TIER:
        return None

    if spike >= TIER_THRESHOLDS["S"]:
        return "S"
    if spike >= TIER_THRESHOLDS["A"]:
        return "A"
    if spike >= TIER_THRESHOLDS["B"]:
        return "B"
    if spike >= TIER_THRESHOLDS["C"]:
        return "C"
    return None  # HIDDEN — below 1.5x


def score_post(post: dict, baseline: Optional[dict]) -> dict:
    """Compute spike, recency, quality, DHS, and tier for one post.

    Returns dict augmenting the post:
        {spike, recency, quality_bonus, dhs, tier}
    """
    spike = compute_spike(post, baseline)
    recency = compute_recency_weight(post.get("posted_at", ""))
    quality = compute_quality_bonus(post)
    dhs = spike * recency * quality
    tier = classify_tier(spike, post) if baseline else None
    return {
        "spike": round(spike, 2),
        "recency": round(recency, 3),
        "quality_bonus": round(quality, 2),
        "dhs": round(dhs, 2),
        "tier": tier,
    }
