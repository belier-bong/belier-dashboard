"""Build a tier-grouped dashboard from per-account history files.

Reads all data/account_history/@*.json files, scores each post with
dark_horse.score_post(), filters by tier (S/A/B/C), groups by tier,
and produces a single self-contained data/dashboard.html.

Mobile-first. Filter chips at top let user toggle one tier or "all together".

Usage:
    python generate_dashboard.py [--open]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config
import account_history
import dark_horse


def _build_card(handle: str, post: dict, scored: dict, baseline: dict | None) -> dict | None:
    """Build a card dict for the dashboard. Returns None if missing critical data."""
    if not scored.get("tier"):
        return None  # HIDDEN — below 1.5x spike

    image = post.get("_local_image", "") or post.get("image_url", "")
    if not image:
        return None

    # Determine baseline metric for display
    is_video = post.get("type") == "Video"
    if is_video:
        baseline_metric = (baseline or {}).get("video_median_views", 0)
        post_metric = post.get("views") or post.get("likes", 0)
        metric_label = "조회수" if post.get("views") else "좋아요"
    else:
        baseline_metric = (baseline or {}).get("image_median_likes", 0)
        post_metric = post.get("likes", 0)
        metric_label = "좋아요"

    return {
        "url": post["url"],
        "image": image,
        "owner": handle,
        "type": post["type"],
        "tier": scored["tier"],
        "spike": scored["spike"],
        "dhs": scored["dhs"],
        "likes": post.get("likes", 0),
        "comments": post.get("comments", 0),
        "views": post.get("views", 0),
        "posted_at": post.get("posted_at", ""),
        "post_metric": post_metric,
        "baseline_metric": baseline_metric,
        "metric_label": metric_label,
    }


def _collect_cards() -> list[dict]:
    """Walk all account histories, score each post, return scored cards (S/A/B/C only)."""
    cards = []
    for handle in account_history.list_handles():
        history = account_history.load_history(handle)
        baseline = history.get("baseline")
        if not baseline:
            continue  # account too new, no baseline yet
        for post in history["posts"].values():
            scored = dark_horse.score_post(post, baseline)
            card = _build_card(handle, post, scored, baseline)
            if card:
                cards.append(card)
    return cards


def _build_html(cards: list[dict], meta: dict) -> str:
    data_json = json.dumps(cards, ensure_ascii=False)
    meta_json = json.dumps(meta, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BELIER 다크호스</title>
<script src="https://cdn.tailwindcss.com"></script>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Pretendard', sans-serif; }}
  .grid-cards {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 1rem;
  }}
  @media (min-width: 640px) {{ .grid-cards {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (min-width: 1024px) {{ .grid-cards {{ grid-template-columns: repeat(3, 1fr); }} }}
  @media (min-width: 1536px) {{ .grid-cards {{ grid-template-columns: repeat(4, 1fr); }} }}
  .card-img {{
    aspect-ratio: 1 / 1;
    object-fit: cover;
    width: 100%;
    background: #1f2937;
  }}
  .tier-S {{ background: linear-gradient(90deg, #fef3c7, #fde68a); }}
  .tier-A {{ background: linear-gradient(90deg, #fce7f3, #fbcfe8); }}
  .tier-B {{ background: linear-gradient(90deg, #fed7aa, #fdba74); }}
  .tier-C {{ background: linear-gradient(90deg, #e0e7ff, #c7d2fe); }}
</style>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen">

<div x-data="dashboard()" class="max-w-screen-xl mx-auto px-4 py-6">

  <!-- Header -->
  <header class="mb-4">
    <h1 class="text-2xl font-bold mb-1">🐎 BELIER 다크호스</h1>
    <p class="text-sm text-gray-600" x-text="`평소보다 터진 포스트만 · ${{meta.accounts}}개 계정 · ${{meta.last_sync}} 동기화`"></p>
  </header>

  <!-- Filter chips (sticky) -->
  <div class="sticky top-0 bg-gray-50/95 backdrop-blur z-10 py-2 mb-4 border-b border-gray-200">
    <div class="flex flex-wrap gap-2">
      <template x-for="t in tabs" :key="t.key">
        <button
          @click="toggleTier(t.key)"
          :class="isActive(t.key) ? activeClass(t.key) : 'bg-gray-200 text-gray-700 hover:bg-gray-300'"
          class="px-3 py-1.5 text-sm rounded-full font-medium transition flex items-center gap-1"
        >
          <span x-text="t.label"></span>
          <span class="text-xs opacity-70" x-text="`(${{count(t.key)}})`"></span>
        </button>
      </template>
    </div>

    <!-- Type filter -->
    <div class="mt-2 flex flex-wrap gap-2 items-center">
      <span class="text-xs text-gray-500">타입:</span>
      <template x-for="t in typeTabs" :key="t.key">
        <button
          @click="typeFilter = t.key"
          :class="typeFilter === t.key ? 'bg-gray-900 text-white' : 'bg-white border border-gray-300 text-gray-600 hover:bg-gray-100'"
          class="px-2.5 py-1 text-xs rounded-full transition"
          x-text="`${{t.label}} (${{typeCount(t.key)}})`"
        ></button>
      </template>
    </div>
  </div>

  <!-- Empty state if no data -->
  <div x-show="cards.length === 0" class="py-20 text-center text-gray-400">
    <p class="text-lg">아직 데이터 없음</p>
    <p class="text-xs mt-2">계정 추가 후 동기화하면 분석이 시작됩니다.</p>
  </div>

  <!-- Tier sections (when no specific tier filter applied) -->
  <template x-if="cards.length > 0 && activeTiers.length === 0">
    <div>
      <template x-for="tier in ['S', 'A', 'B', 'C']" :key="tier">
        <section x-show="filteredByTier(tier).length > 0" class="mb-8">
          <div :class="`tier-${{tier}}`" class="px-4 py-3 rounded-lg mb-3 flex items-center justify-between">
            <div>
              <h2 class="text-lg font-bold flex items-center gap-2">
                <span x-text="tierMeta(tier).emoji"></span>
                <span x-text="tierMeta(tier).label"></span>
                <span class="text-sm font-normal text-gray-700" x-text="`(${{filteredByTier(tier).length}})`"></span>
              </h2>
              <p class="text-xs text-gray-700 mt-0.5" x-text="tierMeta(tier).desc"></p>
            </div>
          </div>
          <div class="grid-cards">
            <template x-for="p in filteredByTier(tier)" :key="p.url">
              <a :href="p.url" target="_blank" rel="noopener"
                 class="block bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-lg transition group">
                <div class="relative">
                  <img :src="p.image" class="card-img" loading="lazy">
                  <span class="absolute top-2 left-2 text-white text-sm font-bold px-2 py-1 rounded shadow"
                        :class="tierBgClass(p.tier)"
                        x-text="`${{tierMeta(p.tier).emoji}} 평소 ${{p.spike}}배`"></span>
                  <span x-show="p.type === 'Video'"
                        class="absolute top-2 right-2 bg-black/70 text-white text-xs px-2 py-0.5 rounded">🎬</span>
                  <span x-show="p.type === 'Sidecar'"
                        class="absolute top-2 right-2 bg-black/70 text-white text-xs px-2 py-0.5 rounded">🎞</span>
                </div>
                <div class="p-3">
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-sm font-semibold" x-text="`@${{p.owner}}`"></span>
                    <span class="text-xs text-gray-500" x-text="formatDate(p.posted_at)"></span>
                  </div>
                  <div class="flex gap-3 text-sm text-gray-700">
                    <span x-text="`❤️ ${{fmt(p.likes)}}`"></span>
                    <span x-text="`💬 ${{fmt(p.comments)}}`"></span>
                    <span x-show="p.views > 0" x-text="`👁 ${{fmt(p.views)}}`"></span>
                  </div>
                  <div class="text-xs text-gray-500 mt-1" x-text="`평소: ${{fmt(p.baseline_metric)}} ${{p.metric_label}}`"></div>
                </div>
              </a>
            </template>
          </div>
        </section>
      </template>
    </div>
  </template>

  <!-- Filtered view (when specific tier(s) selected) -->
  <template x-if="cards.length > 0 && activeTiers.length > 0">
    <div class="grid-cards">
      <template x-for="p in filteredCards()" :key="p.url">
        <a :href="p.url" target="_blank" rel="noopener"
           class="block bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-lg transition group">
          <div class="relative">
            <img :src="p.image" class="card-img" loading="lazy">
            <span class="absolute top-2 left-2 text-white text-sm font-bold px-2 py-1 rounded shadow"
                  :class="tierBgClass(p.tier)"
                  x-text="`${{tierMeta(p.tier).emoji}} 평소 ${{p.spike}}배`"></span>
            <span x-show="p.type === 'Video'"
                  class="absolute top-2 right-2 bg-black/70 text-white text-xs px-2 py-0.5 rounded">🎬</span>
            <span x-show="p.type === 'Sidecar'"
                  class="absolute top-2 right-2 bg-black/70 text-white text-xs px-2 py-0.5 rounded">🎞</span>
          </div>
          <div class="p-3">
            <div class="flex items-center justify-between mb-1">
              <span class="text-sm font-semibold" x-text="`@${{p.owner}}`"></span>
              <span class="text-xs text-gray-500" x-text="formatDate(p.posted_at)"></span>
            </div>
            <div class="flex gap-3 text-sm text-gray-700">
              <span x-text="`❤️ ${{fmt(p.likes)}}`"></span>
              <span x-text="`💬 ${{fmt(p.comments)}}`"></span>
              <span x-show="p.views > 0" x-text="`👁 ${{fmt(p.views)}}`"></span>
            </div>
            <div class="text-xs text-gray-500 mt-1" x-text="`평소: ${{fmt(p.baseline_metric)}} ${{p.metric_label}}`"></div>
          </div>
        </a>
      </template>
    </div>
  </template>

  <footer class="mt-12 py-6 border-t border-gray-200 text-center text-xs text-gray-500">
    BELIER 다크호스 · 평소 1.5배 미만 포스트는 표시 안 됨<br>
    동기화: <a class="underline" target="_blank"
      href="https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}">시트 열기</a>
  </footer>

</div>

<script>
  const CARDS = {data_json};
  const META = {meta_json};
  const TIER_META = {{
    S: {{ emoji: '🏆', label: 'S 전설', desc: '이 계정 평소 10배 이상 — 거의 안 일어남' }},
    A: {{ emoji: '⭐', label: 'A 대박', desc: '평소 5~10배 — 명확한 히트, 카피할 가치 있음' }},
    B: {{ emoji: '🔥', label: 'B 주목', desc: '평소 3~5배 — 평소보다 잘됨' }},
    C: {{ emoji: '✨', label: 'C 살짝', desc: '평소 1.5~3배 — 약한 신호' }},
  }};

  function dashboard() {{
    return {{
      meta: META,
      cards: CARDS,
      activeTiers: [],   // empty = show all tiers in sections; non-empty = filter mode
      typeFilter: 'all', // all / image / video

      tabs: [
        {{key: 'all', label: '전체'}},
        {{key: 'S',   label: '🏆 S'}},
        {{key: 'A',   label: '⭐ A'}},
        {{key: 'B',   label: '🔥 B'}},
        {{key: 'C',   label: '✨ C'}},
      ],
      typeTabs: [
        {{key: 'all',   label: '전체'}},
        {{key: 'image', label: '📷 이미지'}},
        {{key: 'video', label: '🎬 영상'}},
      ],

      tierMeta(tier) {{ return TIER_META[tier] || {{emoji:'?', label:tier, desc:''}}; }},

      tierBgClass(tier) {{
        return {{
          S: 'bg-amber-500',
          A: 'bg-pink-500',
          B: 'bg-orange-500',
          C: 'bg-indigo-500',
        }}[tier] || 'bg-gray-500';
      }},

      activeClass(key) {{
        if (key === 'all') return 'bg-gray-900 text-white';
        return this.tierBgClass(key) + ' text-white';
      }},

      isActive(key) {{
        if (key === 'all') return this.activeTiers.length === 0;
        return this.activeTiers.includes(key);
      }},

      toggleTier(key) {{
        if (key === 'all') {{ this.activeTiers = []; return; }}
        const idx = this.activeTiers.indexOf(key);
        if (idx >= 0) this.activeTiers.splice(idx, 1);
        else this.activeTiers.push(key);
      }},

      typeMatches(card) {{
        if (this.typeFilter === 'all') return true;
        if (this.typeFilter === 'video') return card.type === 'Video';
        return card.type !== 'Video';  // image (Image or Sidecar)
      }},

      filteredByTier(tier) {{
        return this.cards
          .filter(c => c.tier === tier && this.typeMatches(c))
          .sort((a, b) => b.dhs - a.dhs);
      }},

      filteredCards() {{
        return this.cards
          .filter(c => this.activeTiers.includes(c.tier) && this.typeMatches(c))
          .sort((a, b) => b.dhs - a.dhs);
      }},

      count(key) {{
        if (key === 'all') return this.cards.filter(c => this.typeMatches(c)).length;
        return this.cards.filter(c => c.tier === key && this.typeMatches(c)).length;
      }},

      typeCount(key) {{
        if (key === 'all') return this.cards.length;
        if (key === 'video') return this.cards.filter(c => c.type === 'Video').length;
        return this.cards.filter(c => c.type !== 'Video').length;
      }},

      fmt(n) {{
        if (!n) return '0';
        if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\\.0$/, '') + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1).replace(/\\.0$/, '') + 'K';
        return n.toLocaleString();
      }},

      formatDate(iso) {{
        if (!iso) return '';
        return iso.slice(0, 10);  // YYYY-MM-DD
      }},
    }};
  }}
</script>

</body>
</html>
"""


def generate() -> Path:
    cards = _collect_cards()
    cards.sort(key=lambda c: c["dhs"], reverse=True)

    handles = account_history.list_handles()
    last_syncs = []
    for h in handles:
        ls = account_history.load_history(h).get("last_scraped", "")
        if ls:
            last_syncs.append(ls)

    last_sync = max(last_syncs, default="")[:10] if last_syncs else "—"

    meta = {
        "accounts": len(handles),
        "total_cards": len(cards),
        "last_sync": last_sync,
        "by_tier": {
            t: sum(1 for c in cards if c["tier"] == t) for t in ["S", "A", "B", "C"]
        },
    }

    html = _build_html(cards, meta)
    out = config.DATA_DIR / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    print(f"[dashboard] wrote {out} ({len(cards)} cards across {len(handles)} accounts)")
    print(f"[dashboard] tier breakdown: {meta['by_tier']}")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--open", action="store_true", help="Open in default browser")
    args = p.parse_args()
    try:
        path = generate()
    except Exception as e:
        print(f"[dashboard] ERROR: {e}", file=sys.stderr)
        return 1
    if args.open:
        subprocess.run(["open", str(path)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
