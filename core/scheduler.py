"""Stdlib-only schedule decision.

Run as the first workflow step, before pip install:

    python core/scheduler.py --action tick

Writes ``due=true|false`` plus slot metadata to stdout and GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WINDOW_MINUTES = 29
DEFAULT_TIMEZONE = "Asia/Kolkata"
COUNTED_STATUSES = {"posted", "pending"}
MANUAL_ACTIONS = {"generate_preview", "post_now", "publish_queued", "regenerate"}


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _zone(name: Any):
    text = str(name or DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        if text == "Asia/Kolkata":
            return timezone(timedelta(hours=5, minutes=30), "IST")
        try:
            return ZoneInfo(DEFAULT_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            return timezone(timedelta(hours=5, minutes=30), "IST")


def _time_parts(value: Any) -> Optional[tuple]:
    text = str(value or "").strip()
    try:
        hour_text, minute_text = text.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, TypeError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _date_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")


def _slot_key(date: str, slot_id: str) -> str:
    return f"{date}:{slot_id}"


def _config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = config_path or (_root() / "data" / "config.json")
    raw = _read(path)
    if not raw:
        return {
            "timezone": DEFAULT_TIMEZONE,
            "posting_paused": False,
            "mode": "approve",
            "schedule": [],
            "max_posts_per_day": 2,
        }
    return raw


def _history(history_path: Optional[Path] = None) -> Dict[str, Any]:
    path = history_path or (_root() / "data" / "history.json")
    raw = _read(path)
    if not isinstance(raw.get("posts"), list):
        raw["posts"] = []
    return raw


def _posts_today(history: Dict[str, Any], date: str) -> int:
    total = 0
    for post in history.get("posts") or []:
        if not isinstance(post, dict):
            continue
        if post.get("date") == date and post.get("status") in COUNTED_STATUSES:
            total += 1
    return total


def _slot_already_ran(history: Dict[str, Any], key: str) -> bool:
    for post in history.get("posts") or []:
        if not isinstance(post, dict):
            continue
        if post.get("slot_key") == key:
            return True
    return False


def _normalize_slots(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    slots: List[Dict[str, Any]] = []
    raw_slots = config.get("schedule")
    if not isinstance(raw_slots, list):
        return slots
    for index, raw in enumerate(raw_slots):
        if not isinstance(raw, dict):
            continue
        parts = _time_parts(raw.get("time"))
        if not parts:
            continue
        days = raw.get("days")
        if not isinstance(days, list):
            days = list(range(7))
        normalized_days = []
        for day in days:
            try:
                number = int(day)
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 6 and number not in normalized_days:
                normalized_days.append(number)
        slots.append(
            {
                "id": str(raw.get("id") or f"slot_{index + 1}"),
                "time": f"{parts[0]:02d}:{parts[1]:02d}",
                "days": sorted(normalized_days),
                "enabled": bool(raw.get("enabled", True)),
                "mode": str(raw.get("mode") or "global").lower(),
                "topic_override": str(raw.get("topic_override") or ""),
            }
        )
    slots.sort(key=lambda slot: slot["time"])
    return slots


def _now(config: Dict[str, Any], now: Optional[datetime]) -> datetime:
    zone = _zone(config.get("timezone"))
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def _slot_datetime(now: datetime, slot_time: str) -> datetime:
    parts = _time_parts(slot_time)
    if not parts:
        return now
    return now.replace(hour=parts[0], minute=parts[1], second=0, microsecond=0)


def find_due_slot(
    config: Dict[str, Any],
    history: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    moment = _now(config, now)
    date = _date_key(moment)
    result: Dict[str, Any] = {
        "due": False,
        "reason": "",
        "date": date,
        "now": moment.isoformat(),
        "slot_id": "",
        "slot_time": "",
        "slot_mode": "",
        "mode": str(config.get("mode") or "approve"),
        "topic": "",
        "slot_key": "",
        "max_posts_per_day": int(config.get("max_posts_per_day") or 2),
        "posts_today": _posts_today(history, date),
    }
    if bool(config.get("posting_paused")):
        result["reason"] = "Posting is paused"
        return result
    if result["posts_today"] >= result["max_posts_per_day"]:
        result["reason"] = "Daily post limit reached"
        return result
    for slot in _normalize_slots(config):
        if not slot["enabled"]:
            continue
        if moment.weekday() not in slot["days"]:
            continue
        slot_at = _slot_datetime(moment, slot["time"])
        if moment < slot_at:
            continue
        if moment > slot_at + timedelta(minutes=WINDOW_MINUTES):
            continue
        key = _slot_key(date, slot["id"])
        if _slot_already_ran(history, key):
            result["reason"] = "This slot already ran"
            continue
        slot_mode = slot["mode"] if slot["mode"] in ("auto", "approve") else result["mode"]
        result.update(
            {
                "due": True,
                "reason": "Slot is due",
                "slot_id": slot["id"],
                "slot_time": slot["time"],
                "slot_mode": slot_mode,
                "mode": slot_mode,
                "topic": slot["topic_override"],
                "slot_key": key,
            }
        )
        return result
    if not result["reason"]:
        result["reason"] = "No slot in the current 29-minute window"
    return result


def next_runs(
    config: Dict[str, Any],
    count: int = 3,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    moment = _now(config, now)
    runs: List[Dict[str, Any]] = []
    for offset in range(0, 15):
        day = (moment + timedelta(days=offset)).date()
        weekday = day.weekday()
        for slot in _normalize_slots(config):
            if not slot["enabled"] or weekday not in slot["days"]:
                continue
            parts = _time_parts(slot["time"]) or (0, 0)
            candidate = datetime(
                day.year,
                day.month,
                day.day,
                parts[0],
                parts[1],
                tzinfo=moment.tzinfo,
            )
            if candidate <= moment:
                continue
            slot_mode = slot["mode"] if slot["mode"] in ("auto", "approve") else str(
                config.get("mode") or "approve"
            )
            runs.append(
                {
                    "id": slot["id"],
                    "at": candidate.isoformat(),
                    "date": candidate.strftime("%Y-%m-%d"),
                    "time": slot["time"],
                    "mode": slot_mode,
                    "topic": slot["topic_override"],
                }
            )
        if len(runs) >= count:
            break
    runs.sort(key=lambda item: item["at"])
    return runs[:count]


def _emit(data: Dict[str, Any]) -> None:
    for key in (
        "due",
        "reason",
        "date",
        "slot_id",
        "slot_time",
        "slot_mode",
        "topic",
        "slot_key",
        "now",
    ):
        value = data.get(key, "")
        if isinstance(value, bool):
            value = "true" if value else "false"
        print(f"{key}={value}")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        try:
            with open(output_path, "a", encoding="utf-8") as handle:
                for key in (
                    "due",
                    "reason",
                    "date",
                    "slot_id",
                    "slot_time",
                    "slot_mode",
                    "topic",
                    "slot_key",
                    "now",
                ):
                    value = data.get(key, "")
                    if isinstance(value, bool):
                        value = "true" if value else "false"
                    safe = str(value).replace("\n", " ")
                    handle.write(f"{key}={safe}\n")
        except OSError as exc:
            print(f"[scheduler] could not write GITHUB_OUTPUT: {type(exc).__name__}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Decide whether a posting slot is due")
    parser.add_argument("--action", default="tick", choices=["tick", "generate_preview", "post_now", "publish_queued", "regenerate"])
    parser.add_argument("--now", default="", help="ISO timestamp for tests")
    parser.add_argument("--config", default="")
    parser.add_argument("--history", default="")
    parser.add_argument("--root", default="")
    parser.add_argument("--next", action="store_true", help="Print upcoming runs as JSON")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve() if args.root else _root()
    config_path = Path(args.config).expanduser().resolve() if args.config else root / "data" / "config.json"
    history_path = Path(args.history).expanduser().resolve() if args.history else root / "data" / "history.json"
    config = _config(config_path)
    history = _history(history_path)
    now: Optional[datetime] = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        except ValueError:
            print(f"[scheduler] invalid --now value: {args.now}", file=sys.stderr)
            return 2
    if args.next:
        print(json.dumps(next_runs(config, 5, now), indent=2))
        return 0
    if args.action in MANUAL_ACTIONS:
        _emit(
            {
                "due": True,
                "reason": "Manual dispatch",
                "date": _date_key(_now(config, now)),
                "mode": str(config.get("mode") or "approve"),
                "now": _now(config, now).isoformat(),
            }
        )
        return 0
    result = find_due_slot(config, history, now)
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
