"""Fetch fresh stories from RSS feeds and Hacker News, dedupe, score and rank.

This module never raises to the caller for individual feed failures; a broken
feed is skipped silently (logged to stdout) so the pipeline can continue.
"""

from __future__ import annotations

import calendar
import concurrent.futures
import difflib
import html as html_lib
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

USER_AGENT = (
    "NewsCardStudio/1.0 (editorial automation; "
    "+https://github.com/newscard-studio)"
)
FEED_TIMEOUT = 12
HN_TIMEOUT = 10
MAX_PER_FEED = 25
MAX_HN_STORIES = 30

TRACKING_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_name",
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "ref_url",
    "cmpid",
    "ocid",
    "smid",
    "share",
    "source",
}

CATEGORY_LABELS: Dict[str, str] = {
    "tech_ai": "Tech & AI",
    "business": "Business",
    "science_space": "Science & Space",
    "world": "World",
    "sports": "Sports",
    "health": "Health",
    "entertainment": "Entertainment",
    "environment": "Environment",
}

# Concrete visual scenes for the rule-based image query. Never a person's name.
CATEGORY_SCENES: Dict[str, str] = {
    "tech_ai": "server room",
    "business": "stock market screen",
    "science_space": "rocket launch",
    "world": "city skyline",
    "sports": "stadium floodlights",
    "health": "medical laboratory",
    "entertainment": "stage lights",
    "environment": "forest canopy",
}

CATEGORY_HASHTAGS: Dict[str, List[str]] = {
    "tech_ai": ["#technews", "#ai", "#technology", "#innovation", "#future", "#tech", "#digital"],
    "business": ["#business", "#markets", "#economy", "#finance", "#startups", "#money", "#trade"],
    "science_space": ["#science", "#space", "#research", "#discovery", "#nasa", "#physics", "#universe"],
    "world": ["#worldnews", "#global", "#geopolitics", "#international", "#news", "#policy", "#world"],
    "sports": ["#sports", "#sportnews", "#game", "#athlete", "#matchday", "#team", "#champions"],
    "health": ["#health", "#wellbeing", "#medical", "#healthcare", "#research", "#medicine", "#publichealth"],
    "entertainment": ["#entertainment", "#culture", "#film", "#music", "#streaming", "#arts", "#popculture"],
    "environment": ["#environment", "#climate", "#sustainability", "#nature", "#green", "#earth", "#ecosystem"],
}

GOOGLE_NEWS = "https://news.google.com/rss"
GOOGLE_LOCALE = "hl=en-IN&gl=IN&ceid=IN:en"

FEEDS: Dict[str, List[tuple]] = {
    "tech_ai": [
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("Wired", "https://www.wired.com/feed/rss"),
        ("Google News", f"{GOOGLE_NEWS}/headlines/section/topic/TECHNOLOGY?{GOOGLE_LOCALE}"),
    ],
    "business": [
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("Google News", f"{GOOGLE_NEWS}/headlines/section/topic/BUSINESS?{GOOGLE_LOCALE}"),
    ],
    "science_space": [
        ("BBC Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
        ("Google News", f"{GOOGLE_NEWS}/headlines/section/topic/SCIENCE?{GOOGLE_LOCALE}"),
    ],
    "world": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Google News", f"{GOOGLE_NEWS}/headlines/section/topic/WORLD?{GOOGLE_LOCALE}"),
    ],
    "sports": [
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
        ("Google News", f"{GOOGLE_NEWS}/headlines/section/topic/SPORTS?{GOOGLE_LOCALE}"),
    ],
    "health": [
        ("BBC Health", "https://feeds.bbci.co.uk/news/health/rss.xml"),
        ("Google News", f"{GOOGLE_NEWS}/headlines/section/topic/HEALTH?{GOOGLE_LOCALE}"),
    ],
    "entertainment": [
        ("BBC Entertainment", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
        ("Google News", f"{GOOGLE_NEWS}/headlines/section/topic/ENTERTAINMENT?{GOOGLE_LOCALE}"),
    ],
    "environment": [
        ("BBC Science & Environment", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
        (
            "Google News",
            f"{GOOGLE_NEWS}/search?q=climate%20OR%20environment%20OR%20biodiversity&{GOOGLE_LOCALE}",
        ),
    ],
}

SOURCE_WEIGHT = {
    "Hacker News": 4,
    "TechCrunch": 5,
    "The Verge": 5,
    "Ars Technica": 5,
    "Wired": 4,
    "BBC World": 4,
    "BBC Business": 4,
    "BBC Science": 4,
    "BBC Sport": 4,
    "BBC Health": 4,
    "BBC Entertainment": 4,
    "BBC Science & Environment": 4,
    "Google News": 2,
}


@dataclass
class Candidate:
    title: str
    url: str
    source: str
    category: str
    summary: str
    published_ts: float
    score: float = 0.0
    title_norm: str = ""
    age_minutes: int = 0
    index: int = -1

    def to_prompt(self) -> Dict[str, Any]:
        if self.age_minutes < 60:
            age = f"{self.age_minutes}m"
        else:
            age = f"{self.age_minutes // 60}h"
        return {
            "index": self.index,
            "title": self.title,
            "source": self.source,
            "age": age,
            "category": self.category,
            "summary": self.summary,
        }


def _clean_text(raw: Optional[str], limit: int = 240) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?is)<script.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        pos = cut.rfind(" ")
        if pos > 40:
            cut = cut[:pos]
        text = cut.rstrip(" ,.;:") + "\u2026"
    return text


def title_key(title: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def is_similar_title(a: str, b: str) -> bool:
    """Loose title similarity used for cross-source + history dedupe."""
    if not a or not b:
        return False
    if a == b:
        return True
    aset = set(a.split())
    bset = set(b.split())
    if min(len(aset), len(bset)) >= 3:
        union = aset | bset
        if union and len(aset & bset) / len(union) >= 0.72:
            return True
    if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.5:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def canonical_url(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_KEYS and not k.lower().startswith("utm_")
    ]
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit(
        (
            parts.scheme.lower() or "https",
            host,
            parts.path.rstrip("/"),
            urlencode(query),
            "",
        )
    )


def _entry_timestamp(entry: Any, fallback: float) -> float:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return float(calendar.timegm(parsed))
            except (TypeError, ValueError, OverflowError):
                continue
    return fallback


def _strip_google_source(title: str, source: str) -> str:
    if source != "Google News":
        return title
    cleaned = re.sub(r"\s+-\s+[^-]{2,60}$", "", title).strip()
    return cleaned or title


def _fetch_feed(
    source: str, url: str, category: str, cutoff: float, now_ts: float
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        resp = requests.get(
            url,
            timeout=FEED_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            },
        )
        if resp.status_code != 200:
            print(f"[news] skip {source}: HTTP {resp.status_code}")
            return items
        parsed = feedparser.parse(resp.content)
        for entry in parsed.entries[:MAX_PER_FEED]:
            title = _clean_text(entry.get("title"), 220)
            title = _strip_google_source(title, source)
            if not title:
                continue
            ts = _entry_timestamp(entry, now_ts)
            if ts < cutoff:
                continue
            if ts > now_ts + 3 * 3600:
                ts = now_ts
            link = entry.get("link") or ""
            summary = _clean_text(
                entry.get("summary") or entry.get("description") or "", 240
            )
            items.append(
                {
                    "title": title,
                    "url": link,
                    "source": source,
                    "category": category,
                    "summary": summary,
                    "ts": ts,
                }
            )
    except Exception as exc:  # noqa: BLE001 - feed isolation
        print(f"[news] skip {source}: {type(exc).__name__}")
    return items


def _fetch_hn_item(item_id: int, cutoff: float, now_ts: float) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            timeout=HN_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            return None
        item = resp.json()
        if not isinstance(item, dict):
            return None
        if item.get("type") != "story" or item.get("dead") or item.get("deleted"):
            return None
        title = _clean_text(item.get("title"))
        if not title:
            return None
        ts = float(item.get("time") or now_ts)
        if ts < cutoff or ts > now_ts + 3600:
            return None
        points = int(item.get("score") or 0)
        comments = int(item.get("descendants") or 0)
        url = item.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
        summary = f"{points} points and {comments} comments on Hacker News."
        return {
            "title": title,
            "url": url,
            "source": "Hacker News",
            "category": "tech_ai",
            "summary": summary,
            "ts": ts,
            "points": points,
        }
    except Exception:  # noqa: BLE001 - per-item isolation
        return None


def _fetch_hn(cutoff: float, now_ts: float) -> List[Dict[str, Any]]:
    try:
        resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=HN_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            print(f"[news] skip Hacker News: HTTP {resp.status_code}")
            return []
        ids = resp.json()
        if not isinstance(ids, list):
            return []
        ids = [int(i) for i in ids[:MAX_HN_STORIES] if isinstance(i, int)]
    except Exception as exc:  # noqa: BLE001
        print(f"[news] skip Hacker News: {type(exc).__name__}")
        return []
    results: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_fetch_hn_item, i, cutoff, now_ts) for i in ids]
        for future in concurrent.futures.as_completed(futures):
            try:
                item = future.result()
            except Exception:  # noqa: BLE001
                item = None
            if item:
                results.append(item)
    return results


def _prefer_boost(blob: str, prefer: Iterable[str]) -> float:
    boost = 0.0
    for keyword in prefer:
        if keyword and keyword in blob:
            boost += 12.0
    return min(boost, 36.0)


def _prune_category(candidates: List[Candidate], limit: int) -> List[Candidate]:
    ordered = sorted(candidates, key=lambda c: c.score, reverse=True)
    counts: Dict[str, int] = {}
    chosen: List[Candidate] = []
    overflow: List[Candidate] = []
    for cand in ordered:
        if counts.get(cand.category, 0) < 6:
            counts[cand.category] = counts.get(cand.category, 0) + 1
            chosen.append(cand)
        else:
            overflow.append(cand)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        chosen.extend(overflow[: limit - len(chosen)])
    chosen.sort(key=lambda c: c.score, reverse=True)
    return chosen[:limit]


def fetch_candidates(
    config: Dict[str, Any],
    history: Dict[str, Any],
    topic_override: Optional[str] = None,
    limit: int = 25,
) -> List[Candidate]:
    """Return up to ``limit`` fresh, de-duplicated, scored candidates."""
    topics_cfg = config.get("topics") or {}
    enabled = [c for c in CATEGORY_LABELS if bool(topics_cfg.get(c))]
    if topic_override in CATEGORY_LABELS:
        enabled = [topic_override]
    if not enabled:
        return []

    max_age = float((config.get("news") or {}).get("max_age_hours") or 24)
    max_age = max(1.0, min(max_age, 72.0))
    now_ts = time.time()
    cutoff = now_ts - max_age * 3600

    mute = [
        str(k).strip().lower()
        for k in (config.get("mute_keywords") or [])
        if str(k).strip()
    ]
    prefer = [
        str(k).strip().lower()
        for k in (config.get("prefer_keywords") or [])
        if str(k).strip()
    ]

    jobs = []
    for category in enabled:
        for source, url in FEEDS.get(category, []):
            jobs.append((source, url, category))

    raw: List[Dict[str, Any]] = []
    if jobs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [
                pool.submit(_fetch_feed, source, url, category, cutoff, now_ts)
                for source, url, category in jobs
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    raw.extend(future.result())
                except Exception:  # noqa: BLE001
                    pass
    if "tech_ai" in enabled:
        raw.extend(_fetch_hn(cutoff, now_ts))

    posts = (history or {}).get("posts") or []
    history_urls = set()
    history_titles: List[str] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        url = canonical_url(post.get("story_url"))
        if url:
            history_urls.add(url)
        key = title_key(post.get("story_title") or post.get("headline") or "")
        if key:
            history_titles.append(key)

    accepted: List[Candidate] = []
    for item in raw:
        title = (item.get("title") or "").strip()
        norm = title_key(title)
        if len(norm) < 12:
            continue
        summary = (item.get("summary") or "").strip()
        blob = f"{title} {summary}".lower()
        if any(keyword in blob for keyword in mute):
            continue
        url = canonical_url(item.get("url"))
        if url and url in history_urls:
            continue
        if any(is_similar_title(norm, old) for old in history_titles):
            continue
        duplicate = False
        for cand in accepted:
            if url and cand.url and url == cand.url:
                duplicate = True
                break
            if is_similar_title(norm, cand.title_norm):
                duplicate = True
                break
        if duplicate:
            continue
        age_minutes = max(0, int((now_ts - float(item.get("ts") or now_ts)) / 60))
        age_hours = age_minutes / 60.0
        recency = 45.0 * max(0.0, 1.0 - age_hours / max_age)
        source_score = float(SOURCE_WEIGHT.get(item.get("source") or "", 2))
        hotness = 0.0
        if item.get("points"):
            hotness = min(15.0, math.log10(int(item["points"]) + 1) * 6.0)
        score = recency + source_score + hotness + _prefer_boost(blob, prefer)
        accepted.append(
            Candidate(
                title=title,
                url=url,
                source=item.get("source") or "News",
                category=item.get("category") or "world",
                summary=summary,
                published_ts=float(item.get("ts") or now_ts),
                score=round(score, 3),
                title_norm=norm,
                age_minutes=age_minutes,
            )
        )

    if not accepted:
        return []
    ranked = _prune_category(accepted, limit)
    for index, cand in enumerate(ranked):
        cand.index = index
    return ranked


def local_date_key(date: Any) -> str:
    return date.strftime("%Y-%m-%d")
