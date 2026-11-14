"""Offline end-to-end self-test for the pipeline orchestration.

Run from the repo root:

    python -m tests.selftest_pipeline

The LLM, image, news and Chrome renderer are replaced with fakes. The test
exercises the real JSON storage, queue/history/status contracts and run.py.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import run, storage  # noqa: E402
from core.images import ImageAsset  # noqa: E402
from core.news import Candidate  # noqa: E402

STORY = {
    "story_index": 0,
    "category": "tech_ai",
    "headline": "Satellite network opens a faster era for global internet",
    "description": (
        "A new satellite constellation promises faster internet access worldwide "
        "with first commercial service starting this year."
    ),
    "caption": (
        "Satellite internet is getting faster as a new constellation enters service. "
        "#space #technews #satellite #internet #orbit #science #innovation #future"
    ),
    "image_query": "satellite ground station",
    "style": 7,
}


def candidate() -> Candidate:
    return Candidate(
        title=STORY["headline"],
        url="https://example.com/satellite-network",
        source="The Verge",
        category="tech_ai",
        summary=STORY["description"],
        published_ts=0,
        score=55.0,
        title_norm="satellite network opens a faster era for global internet",
        age_minutes=30,
    )


class FakeChain:
    def __init__(self, config):
        self.config = config

    def providers_available(self):
        return ["fake-llm"]

    def pick_story(self, candidates, config, last_style=None, fixed_topic=None):
        return {
            "provider": "fake-llm",
            "provider_label": "Fake LLM",
            "log": "fake-llm: ok",
            "data": dict(STORY),
        }

    def design_html(self, messages, validator, max_calls=3):
        return {
            "provider": "fake-designer",
            "provider_label": "Fake Designer",
            "log": "fake-designer: deliberate fallback",
            "html": "",
        }


def fake_asset(query: str) -> ImageAsset:
    return ImageAsset(
        data=b"fake-jpeg-bytes",
        source="generated",
        width=1080,
        height=1350,
        credit="",
        caption_credit="",
        photo_id="",
        photographer="",
        license_name="Generated",
        query=query,
        log="generated: ok",
    )


def fake_render(html: str, name: str, root=None, fallback_html: str = "") -> dict:
    cards = storage.cards_dir(root)
    cards.mkdir(parents=True, exist_ok=True)
    png = cards / f"{name}.png"
    jpg = cards / f"{name}.jpg"
    png.write_bytes(b"fake-png")
    jpg.write_bytes(b"fake-jpg")
    return {
        "png": png.name,
        "jpg": jpg.name,
        "png_path": str(png),
        "jpg_path": str(jpg),
        "width": 1080,
        "height": 1350,
        "designer": "fallback",
    }


def save_state(root: Path, schedule=None) -> None:
    config = storage.normalize_config(
        {
            "timezone": "Asia/Kolkata",
            "mode": "approve",
            "schedule": [] if schedule is None else schedule,
            "brand": {
                "name": "NewsCard Studio",
                "handle": "@newscardstudio",
                "accent_color": "#B7A0FF",
                "footer_text": "Daily signals, beautifully told.",
            },
        }
    )
    storage.save_config(config, root)
    storage.save_history({"posts": [], "used_photos": [], "meta": {"last_style": None}}, root)
    storage.save_queue({"items": []}, root)


def main() -> None:
    saved_root = os.environ.get("NEWSCARD_ROOT")
    saved_actions = os.environ.get("GITHUB_ACTIONS")
    saved_push = os.environ.get("NEWSCARD_STATUS_PUSH")
    original_fetch_candidates = run.fetch_candidates
    original_fetch_image = run.fetch_image
    original_render_card = run.render_card
    original_chain = run.LLMChain
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.environ["NEWSCARD_ROOT"] = str(root)
            os.environ.pop("GITHUB_ACTIONS", None)
            os.environ.pop("NEWSCARD_STATUS_PUSH", None)
            save_state(root)

            run.fetch_candidates = lambda *args, **kwargs: [candidate()]
            run.fetch_image = lambda query, *args, **kwargs: fake_asset(query)
            run.render_card = fake_render
            run.LLMChain = FakeChain

            code = run.main(["--action", "generate_preview", "--style", "7"])
            assert code == 0, code
            status = storage.load_status(root)
            queue = storage.load_queue(root)
            history = storage.load_history(root)
            assert status["stage"] == "done", status
            assert status["queue_id"], status
            assert len(queue["items"]) == 1, queue
            item = queue["items"][0]
            assert item["status"] == "pending", item
            assert item["style"] == 7, item
            assert item["style_name"], item
            assert item["headline"] == STORY["headline"], item
            assert item["image_source"] == "generated", item
            assert len(history["posts"]) == 1, history
            entry = history["posts"][0]
            assert entry["status"] == "pending", entry
            assert entry["id"] == item["history_id"], (entry["id"], item["history_id"])
            assert history["meta"]["last_style"] == 7, history["meta"]
            assert (storage.cards_dir(root) / item["png"]).is_file()
            assert (storage.cards_dir(root) / item["jpg"]).is_file()
            assert status["card_jpg"] == item["jpg"], status
            print("PASS generate_preview queues a real card entry and files")

            code = run.main(
                ["--action", "publish_queued", "--queue-id", item["id"], "--dry-run"]
            )
            assert code == 0, code
            status = storage.load_status(root)
            queue = storage.load_queue(root)
            history = storage.load_history(root)
            assert status["stage"] == "done", status
            assert status["dry_run"] is True, status
            assert "would be published" in status["message"], status
            assert len(queue["items"]) == 1 and queue["items"][0]["status"] == "pending", queue
            assert history["posts"][0]["status"] == "pending", history
            print("PASS publish_queued dry run leaves the queue and history untouched")

            config = storage.load_config(root)
            config["schedule"] = []
            storage.save_config(config, root)
            code = run.main(["--action", "tick"])
            assert code == 0, code
            status = storage.load_status(root)
            assert status["stage"] == "done", status
            assert status["message"].startswith("No post this time"), status
            assert len(storage.load_queue(root)["items"]) == 1
            print("PASS tick without a due slot exits cleanly and does not generate")

            run.fetch_candidates = lambda *args, **kwargs: []
            code = run.main(["--action", "generate_preview"])
            assert code == 1, code
            status = storage.load_status(root)
            assert status["stage"] == "failed", status
            assert "No fresh stories" in status["message"], status
            assert len(storage.load_queue(root)["items"]) == 1
            print("PASS an empty candidate set writes a friendly failed status")
    finally:
        run.fetch_candidates = original_fetch_candidates
        run.fetch_image = original_fetch_image
        run.render_card = original_render_card
        run.LLMChain = original_chain
        if saved_root is None:
            os.environ.pop("NEWSCARD_ROOT", None)
        else:
            os.environ["NEWSCARD_ROOT"] = saved_root
        if saved_actions is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = saved_actions
        if saved_push is None:
            os.environ.pop("NEWSCARD_STATUS_PUSH", None)
        else:
            os.environ["NEWSCARD_STATUS_PUSH"] = saved_push


if __name__ == "__main__":
    main()