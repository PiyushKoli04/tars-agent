"""JSON storage and configuration validation for NewsCard Studio.

Positional arguments mirror the repository layout: ``data/`` holds JSON state
and ``docs/cards/`` holds published card files. Tests can point the whole
pipeline at a temporary directory with ``NEWSCARD_ROOT``.
"""

from __future__ import annotations

import copy
import json
import os
import random
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CATEGORIES = [
    "tech_ai",
    "business",
    "science_space",
    "world",
    "sports",
    "health",
    "entertainment",
    "environment",
]

STYLE_NUMBERS = list(range(1, 21))
LLM_PROVIDERS = ["nvidia", "opencode", "gemini", "groq"]
IMAGE_PROVIDERS = ["unsplash", "article", "pixabay", "wikimedia", "generated"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "timezone": "Asia/Kolkata",
    "posting_paused": False,
    "mode": "approve",
    "schedule": [
        {
            "id": "slot_morning",
            "time": "05:30",
            "days": [0, 1, 2, 3, 4, 5, 6],
            "enabled": True,
            "mode": "global",
            "topic_override": "",
        },
        {
            "id": "slot_evening",
            "time": "18:30",
            "days": [0, 1, 2, 3, 4, 5, 6],
            "enabled": True,
            "mode": "global",
            "topic_override": "",
        },
    ],
    "topics": {key: True for key in CATEGORIES},
    "prefer_keywords": [],
    "mute_keywords": [],
    "style": "auto",
    "avoid_repeat_style": True,
    "brand": {
        "name": "NewsCard Studio",
        "handle": "@newscardstudio",
        "accent_color": "#B7A0FF",
        "footer_text": "Daily signals, beautifully told.",
        "logo_path": "",
    },
    "llm": {"order": list(LLM_PROVIDERS), "disabled": []},
    "image": {
        "order": list(IMAGE_PROVIDERS),
        "disabled": [],
        "prefer_article_photo": False,
        "show_credit": True,
    },
    "max_posts_per_day": 2,
    "news": {"max_age_hours": 24},
}

DEFAULT_HISTORY: Dict[str, Any] = {
    "posts": [],
    "used_photos": [],
    "meta": {"last_style": None, "last_run": None},
}

DEFAULT_QUEUE: Dict[str, Any] = {"items": []}

DEFAULT_STATUS: Dict[str, Any] = {
    "run_id": None,
    "action": None,
    "stage": "idle",
    "step": 0,
    "provider_used": None,
    "provider_log": None,
    "image_source": None,
    "message": "Waiting for the first run.",
    "updated_at": None,
    "ig_session": "unknown",
}


def repo_root() -> Path:
    override = os.environ.get("NEWSCARD_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def data_dir(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / "data"


def docs_dir(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / "docs"


def cards_dir(root: Optional[Path] = None) -> Path:
    return docs_dir(root) / "cards"


def _deep_defaults(raw: Any, default: Any) -> Any:
    if isinstance(default, dict):
        source = raw if isinstance(raw, dict) else {}
        return {key: _deep_defaults(source.get(key), value) for key, value in default.items()}
    if isinstance(default, list):
        return copy.deepcopy(raw) if isinstance(raw, list) else copy.deepcopy(default)
    return default if raw is None else raw


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[storage] could not read {path.name}: {type(exc).__name__}")
        return copy.deepcopy(default)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temporary: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
        ) as handle:
            handle.write(payload)
            temporary = handle.name
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def local_now(config: Dict[str, Any]) -> datetime:
    zone = _valid_timezone(config.get("timezone"))
    return datetime.now(zone)


def _valid_timezone(value: Any):
    text = str(value or "Asia/Kolkata")
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        if text == "Asia/Kolkata":
            return timezone(timedelta(hours=5, minutes=30), "IST")
        try:
            return ZoneInfo("Asia/Kolkata")
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            return timezone(timedelta(hours=5, minutes=30), "IST")


def new_id(prefix: str = "card") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{random.randrange(16**4):04x}"


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _clean_string(value: Any, default: str = "", limit: int = 120) -> str:
    if not isinstance(value, str):
        return default
    return value.strip()[:limit]


def _clean_string_list(value: Any, limit: int = 40, item_limit: int = 60) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value[:limit]:
        text = _clean_string(item, "", item_limit)
        if text and text not in result:
            result.append(text)
    return result


def _normalize_time(value: Any, default: str = "05:30") -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or "").strip())
    if not match:
        return default
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute not in (0, 30):
        rounded = 30 if minute >= 15 else 0
        if minute >= 45:
            hour = (hour + 1) % 24
            rounded = 0
        minute = rounded
        hour = max(0, min(23, hour))
    return f"{hour:02d}:{minute:02d}"


def _normalize_days(value: Any) -> List[int]:
    if not isinstance(value, list):
        return list(range(7))
    days: List[int] = []
    for item in value:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in days:
            days.append(day)
    return sorted(days) if days else list(range(7))


def _normalize_schedule(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raw = copy.deepcopy(DEFAULT_CONFIG["schedule"])
    slots: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        slot_id = _clean_string(item.get("id"), "", 60)
        if not slot_id:
            slot_id = f"slot_{index + 1}"
        base_id = slot_id
        suffix = 2
        while slot_id in seen_ids:
            slot_id = f"{base_id}_{suffix}"
            suffix += 1
        seen_ids.add(slot_id)
        mode = _clean_string(item.get("mode"), "global", 12).lower()
        if mode not in ("global", "auto", "approve"):
            mode = "global"
        topic = _clean_string(item.get("topic_override"), "", 30)
        if topic not in CATEGORIES:
            topic = ""
        slots.append(
            {
                "id": slot_id,
                "time": _normalize_time(item.get("time")),
                "days": _normalize_days(item.get("days")),
                "enabled": _as_bool(item.get("enabled"), True),
                "mode": mode,
                "topic_override": topic,
            }
        )
    slots.sort(key=lambda slot: slot["time"])
    return slots


def _normalize_accent(value: Any) -> str:
    text = _clean_string(value, "#B7A0FF", 7).upper()
    return text if re.fullmatch(r"#[0-9A-F]{6}", text) else "#B7A0FF"


def _normalize_order(value: Any, allowed: List[str]) -> List[str]:
    order: List[str] = []
    if isinstance(value, list):
        for item in value:
            provider = _clean_string(item, "", 30).lower()
            if provider in allowed and provider not in order:
                order.append(provider)
    for provider in allowed:
        if provider not in order:
            order.append(provider)
    return order


def normalize_config(raw: Any) -> Dict[str, Any]:
    merged = _deep_defaults(raw, DEFAULT_CONFIG)
    config: Dict[str, Any] = {
        "timezone": _clean_string(merged.get("timezone"), "Asia/Kolkata", 64)
        or "Asia/Kolkata",
        "posting_paused": _as_bool(merged.get("posting_paused"), False),
        "mode": "auto"
        if _clean_string(merged.get("mode"), "approve", 10).lower() == "auto"
        else "approve",
        "schedule": _normalize_schedule(merged.get("schedule")),
        "topics": {},
        "prefer_keywords": _clean_string_list(merged.get("prefer_keywords")),
        "mute_keywords": _clean_string_list(merged.get("mute_keywords")),
        "style": "auto",
        "avoid_repeat_style": _as_bool(merged.get("avoid_repeat_style"), True),
        "brand": {},
        "llm": {},
        "image": {},
        "max_posts_per_day": _as_int(merged.get("max_posts_per_day"), 2, 1, 10),
        "news": {
            "max_age_hours": _as_int(
                (merged.get("news") or {}).get("max_age_hours"), 24, 1, 72
            )
        },
    }
    _valid_timezone(config["timezone"])
    raw_topics = merged.get("topics") if isinstance(merged.get("topics"), dict) else {}
    for key in CATEGORIES:
        config["topics"][key] = _as_bool(raw_topics.get(key), True)
    style_raw = merged.get("style", "auto")
    if str(style_raw).strip().lower() != "auto":
        try:
            style_number = int(style_raw)
            if 1 <= style_number <= 20:
                config["style"] = style_number
        except (TypeError, ValueError):
            pass
    brand_raw = merged.get("brand") if isinstance(merged.get("brand"), dict) else {}
    logo_path = _clean_string(brand_raw.get("logo_path"), "", 200)
    if logo_path and (logo_path.startswith(("http://", "https://")) or ".." in logo_path):
        logo_path = ""
    config["brand"] = {
        "name": _clean_string(brand_raw.get("name"), "NewsCard Studio", 60)
        or "NewsCard Studio",
        "handle": _clean_string(brand_raw.get("handle"), "@newscardstudio", 40),
        "accent_color": _normalize_accent(brand_raw.get("accent_color")),
        "footer_text": _clean_string(
            brand_raw.get("footer_text"), "Daily signals, beautifully told.", 100
        ),
        "logo_path": logo_path,
    }
    llm_raw = merged.get("llm") if isinstance(merged.get("llm"), dict) else {}
    config["llm"] = {
        "order": _normalize_order(llm_raw.get("order"), LLM_PROVIDERS),
        "disabled": [
            provider
            for provider in _normalize_order(llm_raw.get("disabled"), LLM_PROVIDERS)
            if provider in (_clean_string_list(llm_raw.get("disabled"), 20) or [])
        ],
    }
    image_raw = merged.get("image") if isinstance(merged.get("image"), dict) else {}
    image_order = _normalize_order(image_raw.get("order"), IMAGE_PROVIDERS)
    if "generated" in image_order:
        image_order = [name for name in image_order if name != "generated"] + ["generated"]
    disabled_images = {
        _clean_string(item, "", 30).lower()
        for item in (image_raw.get("disabled") or [])
        if isinstance(item, str)
    }
    config["image"] = {
        "order": image_order,
        "disabled": [name for name in IMAGE_PROVIDERS if name in disabled_images],
        "prefer_article_photo": _as_bool(image_raw.get("prefer_article_photo"), False),
        "show_credit": _as_bool(image_raw.get("show_credit"), True),
    }
    return config


def load_config(root: Optional[Path] = None, persist: bool = True) -> Dict[str, Any]:
    path = data_dir(root) / "config.json"
    raw = read_json(path, {})
    normalized = normalize_config(raw)
    if persist and normalized != raw:
        try:
            write_json(path, normalized)
        except OSError as exc:
            print(f"[storage] could not save config: {type(exc).__name__}")
    return normalized


def load_history(root: Optional[Path] = None) -> Dict[str, Any]:
    raw = read_json(data_dir(root) / "history.json", DEFAULT_HISTORY)
    if not isinstance(raw, dict):
        raw = copy.deepcopy(DEFAULT_HISTORY)
    history = _deep_defaults(raw, DEFAULT_HISTORY)
    for key in ("posts", "used_photos"):
        if not isinstance(history.get(key), list):
            history[key] = []
    if not isinstance(history.get("meta"), dict):
        history["meta"] = {"last_style": None, "last_run": None}
    return history


def load_queue(root: Optional[Path] = None) -> Dict[str, Any]:
    raw = read_json(data_dir(root) / "queue.json", DEFAULT_QUEUE)
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raw = copy.deepcopy(DEFAULT_QUEUE)
    items = [item for item in raw["items"] if isinstance(item, dict)]
    return {"items": items}


def load_status(root: Optional[Path] = None) -> Dict[str, Any]:
    raw = read_json(data_dir(root) / "status.json", DEFAULT_STATUS)
    merged = copy.deepcopy(DEFAULT_STATUS)
    if isinstance(raw, dict):
        merged.update(raw)
    return merged


def save_config(config: Dict[str, Any], root: Optional[Path] = None) -> None:
    write_json(data_dir(root) / "config.json", config)


def save_history(history: Dict[str, Any], root: Optional[Path] = None) -> None:
    write_json(data_dir(root) / "history.json", history)


def save_queue(queue: Dict[str, Any], root: Optional[Path] = None) -> None:
    write_json(data_dir(root) / "queue.json", queue)


def save_status(status: Dict[str, Any], root: Optional[Path] = None) -> None:
    write_json(data_dir(root) / "status.json", status)


def used_photo_keys(history: Dict[str, Any], days: int = 30) -> set:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    keys = set()
    for item in history.get("used_photos") or []:
        if not isinstance(item, dict):
            continue
        used_at = parse_iso(item.get("used_at"))
        if used_at is None or used_at < cutoff:
            continue
        provider = _clean_string(item.get("provider"), "", 20)
        photo_id = _clean_string(item.get("id"), "", 200)
        if provider and photo_id:
            keys.add(f"{provider}:{photo_id}")
    return keys


def add_used_photo(
    history: Dict[str, Any],
    provider: str,
    photo_id: str,
    credit: str = "",
    used_at: Optional[str] = None,
) -> None:
    if not provider or not photo_id:
        return
    history.setdefault("used_photos", []).append(
        {
            "provider": provider,
            "id": photo_id,
            "credit": credit,
            "used_at": used_at or iso_now(),
        }
    )


def prune_used_photos(history: Dict[str, Any], days: int = 30) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept = []
    for item in history.get("used_photos") or []:
        if not isinstance(item, dict):
            continue
        used_at = parse_iso(item.get("used_at"))
        if used_at is not None and used_at >= cutoff:
            kept.append(item)
    history["used_photos"] = kept


def card_public_path(name: str) -> str:
    return f"cards/{Path(name).name}"


def date_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")
