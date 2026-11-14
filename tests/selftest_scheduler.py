"""Offline self-test for the schedule decision engine.

Run from the repo root:

    python -m tests.selftest_scheduler

No network access is used.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import scheduler  # noqa: E402

ZONE = scheduler._zone("Asia/Kolkata")

CONFIG = {
    "timezone": "Asia/Kolkata",
    "posting_paused": False,
    "mode": "approve",
    "max_posts_per_day": 2,
    "schedule": [
        {
            "id": "slot_morning",
            "time": "05:30",
            "days": list(range(7)),
            "enabled": True,
            "mode": "global",
            "topic_override": "",
        },
        {
            "id": "slot_evening",
            "time": "18:30",
            "days": list(range(7)),
            "enabled": True,
            "mode": "auto",
            "topic_override": "tech_ai",
        },
    ],
}


def at(hour: int, minute: int, day: int = 18) -> datetime:
    return datetime(2026, 5, day, hour, minute, tzinfo=ZONE)


def history(*posts) -> dict:
    return {"posts": list(posts), "used_photos": [], "meta": {}}


def post(slot_key: str = "", status: str = "posted", date: str = "2026-05-18") -> dict:
    return {"slot_key": slot_key, "status": status, "date": date}


def test_window() -> None:
    base = history()
    early = scheduler.find_due_slot(CONFIG, base, at(5, 29))
    assert not early["due"] and early["reason"] == "No slot in the current 29-minute window", early
    start = scheduler.find_due_slot(CONFIG, base, at(5, 30))
    assert start["due"] and start["slot_id"] == "slot_morning", start
    assert start["slot_key"] == "2026-05-18:slot_morning"
    assert start["slot_mode"] == "approve"
    inside = scheduler.find_due_slot(CONFIG, base, at(5, 59))
    assert inside["due"], inside
    late = scheduler.find_due_slot(CONFIG, base, at(6, 0))
    assert not late["due"], late
    print("PASS due window is inclusive for 29 minutes after the slot")


def test_no_duplicate_slot() -> None:
    base = history(post("2026-05-18:slot_morning"))
    result = scheduler.find_due_slot(CONFIG, base, at(5, 35))
    assert not result["due"]
    assert result["reason"] == "This slot already ran", result
    print("PASS a slot key is only posted once")


def test_daily_limit_and_pause() -> None:
    two_posts = history(post("a"), post("b"))
    limited = scheduler.find_due_slot(CONFIG, two_posts, at(5, 35))
    assert not limited["due"] and limited["reason"] == "Daily post limit reached", limited
    paused = copy.deepcopy(CONFIG)
    paused["posting_paused"] = True
    result = scheduler.find_due_slot(paused, history(), at(5, 35))
    assert not result["due"] and result["reason"] == "Posting is paused", result
    print("PASS daily limit and pause guard the schedule")


def test_days_disabled_and_mode_override() -> None:
    monday_only = copy.deepcopy(CONFIG)
    monday_only["schedule"][0]["days"] = [0]
    base = history()
    day = scheduler.find_due_slot(monday_only, base, at(5, 35, day=19))
    assert not day["due"], day
    evening = scheduler.find_due_slot(CONFIG, base, at(18, 35))
    assert evening["due"] and evening["slot_id"] == "slot_evening", evening
    assert evening["slot_mode"] == "auto", evening
    assert evening["topic"] == "tech_ai", evening
    disabled = copy.deepcopy(CONFIG)
    disabled["schedule"][0]["enabled"] = False
    result = scheduler.find_due_slot(disabled, base, at(5, 35))
    assert not result["due"], result
    print("PASS weekday filters, disabled slots and slot mode overrides work")


def test_next_runs() -> None:
    runs = scheduler.next_runs(CONFIG, 3, at(6, 0))
    assert len(runs) == 3, runs
    assert runs[0]["id"] == "slot_evening" and runs[0]["date"] == "2026-05-18", runs
    assert runs[1]["id"] == "slot_morning" and runs[1]["date"] == "2026-05-19", runs
    assert runs[0]["at"] < runs[1]["at"] < runs[2]["at"], runs
    print("PASS upcoming runs are sorted and skip past times")


def test_manual_dispatch() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        config_path = base / "config.json"
        history_path = base / "history.json"
        output_path = base / "github-output.txt"
        config_path.write_text(json.dumps(CONFIG), encoding="utf-8")
        history_path.write_text(json.dumps(history()), encoding="utf-8")
        old_output = os.environ.get("GITHUB_OUTPUT")
        os.environ["GITHUB_OUTPUT"] = str(output_path)
        try:
            code = scheduler.main(
                [
                    "--action",
                    "post_now",
                    "--now",
                    at(12, 0).isoformat(),
                    "--config",
                    str(config_path),
                    "--history",
                    str(history_path),
                ]
            )
        finally:
            if old_output is None:
                os.environ.pop("GITHUB_OUTPUT", None)
            else:
                os.environ["GITHUB_OUTPUT"] = old_output
        assert code == 0
        output = output_path.read_text(encoding="utf-8")
        assert "due=true" in output, output
        assert "reason=Manual dispatch" in output, output
        assert "date=2026-05-18" in output, output
    assert "post_now" in scheduler.MANUAL_ACTIONS
    print("PASS manual dispatch always proceeds and writes GITHUB_OUTPUT")


def main() -> None:
    tests = [
        test_window,
        test_no_duplicate_slot,
        test_daily_limit_and_pause,
        test_days_disabled_and_mode_override,
        test_next_runs,
        test_manual_dispatch,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} scheduler self-tests passed.")


if __name__ == "__main__":
    main()