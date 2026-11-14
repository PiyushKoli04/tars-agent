"""Orchestrator for NewsCard Studio.

    python -m core.run --action tick
    python -m core.run --action generate_preview --dry-run
    python -m core.run --action post_now --topic tech_ai
    python -m core.run --action publish_queued --queue-id card_...
    python -m core.run --action regenerate --queue-id card_...

The pipeline never skips a post because a language model failed; the rule-based
editor and the fallback template always produce a card.
"""

from __future__ import annotations

import argparse
import copy
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import storage
from core.design import (
    STYLE_NAMES,
    build_design_messages,
    inject_media,
    load_logo_data_uri,
    render_fallback,
    style_name,
    validate_design,
)
from core.env import load_env
from core.images import ImageAsset, card_credit, fetch_image
from core.llm import LLMChain, label_for
from core.news import CATEGORY_LABELS, fetch_candidates
from core.post import PostError, publish_card
from core.render import RenderError, render_card
from core.scheduler import find_due_slot

STAGE_STEPS = {
    "queued": 0,
    "fetching": 1,
    "writing": 2,
    "designing": 3,
    "rendering": 4,
    "posting": 5,
    "done": 6,
    "failed": 6,
}


class PipelineError(RuntimeError):
    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.friendly = message
        self.details = details or message


def _git(root: Path, arguments: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root)] + arguments,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class StatusWriter:
    def __init__(self, root: Path, run_id: str, action: str, dry_run: bool):
        self.root = root
        previous = storage.load_status(root)
        self.data: Dict[str, Any] = {
            "run_id": run_id,
            "action": action,
            "stage": "queued",
            "step": 0,
            "provider_used": None,
            "provider_log": None,
            "design_provider": None,
            "design_log": None,
            "image_source": None,
            "image_log": None,
            "message": "Run queued.",
            "updated_at": storage.iso_now(),
            "ig_session": previous.get("ig_session") or "unknown",
            "queue_id": None,
            "card_png": None,
            "card_jpg": None,
            "headline": None,
            "category": None,
            "style": None,
            "instagram_url": None,
            "dry_run": dry_run,
            "error": None,
            "details": None,
        }

    def update(self, stage: str, message: str, **fields: Any) -> None:
        self.data["stage"] = stage
        self.data["step"] = STAGE_STEPS.get(stage, 0)
        self.data["message"] = message
        self.data["updated_at"] = storage.iso_now()
        for key, value in fields.items():
            self.data[key] = value
        storage.save_status(self.data, self.root)
        self._push(stage)

    def _push(self, stage: str) -> None:
        if os.environ.get("NEWSCARD_STATUS_PUSH") == "0":
            return
        if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get(
            "NEWSCARD_STATUS_PUSH"
        ) != "1":
            return
        if not (self.root / ".git").exists():
            return
        relative = "data/status.json"
        try:
            added = _git(self.root, ["add", "--", relative])
            if added.returncode != 0:
                return
            difference = _git(self.root, ["diff", "--cached", "--quiet", "--", relative])
            if difference.returncode == 0:
                return
            committed = _git(
                self.root,
                [
                    "-c",
                    "user.name=NewsCard Studio",
                    "-c",
                    "user.email=actions@users.noreply.github.com",
                    "commit",
                    "-m",
                    f"status: {stage} [skip ci]",
                    "--",
                    relative,
                ],
            )
            if committed.returncode != 0:
                return
            pushed = _git(self.root, ["push"])
            if pushed.returncode != 0:
                _git(self.root, ["pull", "--rebase", "--autostash"], timeout=45)
                _git(self.root, ["push"])
        except (OSError, subprocess.SubprocessError):
            return


def _style_number(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 20 else None


def _local_date(config: Dict[str, Any]) -> str:
    return storage.date_key(storage.local_now(config))


def _final_caption(caption: str, new_credit: str, old_credit: str = "") -> str:
    text = (caption or "").strip()
    old = (old_credit or "").strip()
    if old and old.lower() in text.lower():
        text = text.replace(old, "").strip()
    new = (new_credit or "").strip()
    if new and new.lower() not in text.lower():
        text = f"{text}\n\n{new}" if text else new
    if len(text) > 2200:
        text = text[:2197].rstrip() + "..."
    return text


def _entry_for(
    card_id: str,
    run_id: str,
    action: str,
    config: Dict[str, Any],
    pick: Dict[str, Any],
    asset: ImageAsset,
    design_result: Dict[str, Any],
    render_result: Dict[str, Any],
    candidates: List[Any],
    caption: str,
    style_number: int,
    image_query: str,
    slot_id: str,
    slot_key: str,
    mode: str,
    dry_run: bool,
) -> Dict[str, Any]:
    data = pick["data"]
    candidate = candidates[data["story_index"]]
    credit_text = card_credit(asset, bool((config.get("image") or {}).get("show_credit", True)))
    now = storage.iso_now()
    return {
        "id": card_id,
        "run_id": run_id,
        "action": action,
        "status": "pending",
        "date": _local_date(config),
        "slot": slot_id,
        "slot_key": slot_key,
        "mode": mode,
        "created_at": now,
        "posted_at": None,
        "headline": data["headline"],
        "description": data["description"],
        "caption": caption,
        "category": data["category"],
        "category_label": CATEGORY_LABELS.get(data["category"], data["category"]),
        "style": style_number,
        "style_name": style_name(style_number),
        "story_title": candidate.title,
        "story_url": candidate.url,
        "story_source": candidate.source,
        "provider": pick["provider"],
        "provider_label": pick["provider_label"],
        "provider_log": pick["log"],
        "design_provider": design_result["provider"] or "fallback",
        "design_provider_label": design_result["provider_label"],
        "design_log": design_result["log"],
        "image_source": asset.source,
        "image_credit": credit_text,
        "image_caption_credit": asset.caption_credit,
        "image_photo_id": asset.photo_id,
        "image_photographer": asset.photographer,
        "image_license": asset.license_name,
        "image_query": image_query,
        "image_log": asset.log,
        "png": render_result["png"],
        "jpg": render_result["jpg"],
        "instagram_url": "",
        "error": "",
        "error_details": "",
        "dry_run": bool(dry_run),
    }


def _queue_item(entry: Dict[str, Any], status: str = "pending", error: str = "") -> Dict[str, Any]:
    return {
        "id": entry["id"],
        "history_id": entry["id"],
        "status": status,
        "created_at": entry["created_at"],
        "updated_at": storage.iso_now(),
        "headline": entry["headline"],
        "description": entry["description"],
        "caption": entry["caption"],
        "category": entry["category"],
        "category_label": entry["category_label"],
        "style": entry["style"],
        "style_name": entry["style_name"],
        "story_title": entry["story_title"],
        "story_url": entry["story_url"],
        "story_source": entry["story_source"],
        "image_query": entry["image_query"],
        "image_source": entry["image_source"],
        "image_credit": entry["image_credit"],
        "image_caption_credit": entry["image_caption_credit"],
        "image_photo_id": entry["image_photo_id"],
        "image_log": entry["image_log"],
        "provider": entry["provider"],
        "provider_log": entry["provider_log"],
        "design_provider": entry["design_provider"],
        "design_log": entry["design_log"],
        "png": entry["png"],
        "jpg": entry["jpg"],
        "slot_key": entry["slot_key"],
        "date": entry["date"],
        "run_id": entry["run_id"],
        "mode": entry["mode"],
        "dry_run": entry["dry_run"],
        "error": error,
    }


def _find_history_entry(history: Dict[str, Any], identifier: str) -> Optional[Dict[str, Any]]:
    for entry in history.get("posts") or []:
        if isinstance(entry, dict) and entry.get("id") == identifier:
            return entry
    return None


def _find_queue_item(queue: Dict[str, Any], queue_id: str) -> Optional[Dict[str, Any]]:
    for item in queue.get("items") or []:
        if isinstance(item, dict) and item.get("id") == queue_id:
            return item
    return None


def _replace_queue_item(queue: Dict[str, Any], item: Dict[str, Any]) -> None:
    items = queue.setdefault("items", [])
    for index, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item.get("id"):
            items[index] = item
            return
    items.append(item)


def _remove_queue_item(queue: Dict[str, Any], queue_id: str) -> None:
    queue["items"] = [
        item
        for item in queue.get("items") or []
        if not (isinstance(item, dict) and item.get("id") == queue_id)
    ]


def _entry_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "id",
        "run_id",
        "action",
        "date",
        "slot_key",
        "mode",
        "created_at",
        "headline",
        "description",
        "caption",
        "category",
        "category_label",
        "style",
        "style_name",
        "story_title",
        "story_url",
        "story_source",
        "provider",
        "provider_log",
        "design_provider",
        "design_log",
        "image_source",
        "image_credit",
        "image_caption_credit",
        "image_photo_id",
        "image_query",
        "image_log",
        "png",
        "jpg",
        "dry_run",
    )
    entry = {key: item.get(key) for key in keys}
    entry.update(
        {
            "status": "pending",
            "posted_at": None,
            "instagram_url": "",
            "error": "",
            "error_details": "",
        }
    )
    return entry


def _prune(root: Path, history: Dict[str, Any], queue: Dict[str, Any]) -> None:
    posts = [post for post in history.get("posts") or [] if isinstance(post, dict)]
    history["posts"] = posts[-60:]
    storage.prune_used_photos(history, 30)
    items = [item for item in queue.get("items") or [] if isinstance(item, dict)]
    queue["items"] = items[-50:]
    keep = set()
    for entry in history["posts"]:
        for key in ("png", "jpg"):
            name = str(entry.get(key) or "")
            if name:
                keep.add(Path(name).name)
    for item in queue["items"]:
        for key in ("png", "jpg"):
            name = str(item.get(key) or "")
            if name:
                keep.add(Path(name).name)
    cutoff = time.time() - 14 * 24 * 3600
    try:
        for candidate in storage.cards_dir(root).iterdir():
            if not candidate.is_file() or candidate.suffix.lower() not in (".png", ".jpg"):
                continue
            if candidate.name in keep:
                continue
            try:
                if candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except OSError:
                continue
    except OSError:
        pass


def _persist(
    root: Path, history: Dict[str, Any], queue: Dict[str, Any]
) -> None:
    _prune(root, history, queue)
    storage.save_history(history, root)
    storage.save_queue(queue, root)


def _publish_item(
    item: Dict[str, Any],
    entry: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
) -> Dict[str, Any]:
    status.update(
        "posting",
        "Posting to Instagram",
        queue_id=item["id"],
        card_jpg=item.get("jpg"),
        card_png=item.get("png"),
        headline=item.get("headline"),
        category=item.get("category"),
        style=item.get("style"),
        image_source=item.get("image_source"),
    )
    caption = _final_caption(
        str(item.get("caption") or ""),
        str(item.get("image_caption_credit") or ""),
    )
    item["caption"] = caption
    entry["caption"] = caption
    jpg_path = storage.cards_dir(root) / Path(str(item.get("jpg") or "")).name
    try:
        result = publish_card(str(jpg_path), caption, dry_run=False, root=root)
    except PostError as exc:
        entry.update(
            {
                "status": "failed",
                "error": exc.friendly,
                "error_details": exc.details,
            }
        )
        item.update(
            {
                "status": "failed",
                "error": exc.friendly,
                "updated_at": storage.iso_now(),
            }
        )
        return {
            "ok": False,
            "message": exc.friendly,
            "details": exc.details,
            "session": "needs_refresh" if exc.session_problem else None,
        }
    except Exception as exc:  # noqa: BLE001 - posting must never crash the run
        message = "Instagram could not publish the card. Check the run details and try again later."
        details = f"{type(exc).__name__}: {exc}"
        entry.update({"status": "failed", "error": message, "error_details": details})
        item.update({"status": "failed", "error": message, "updated_at": storage.iso_now()})
        return {"ok": False, "message": message, "details": details, "session": None}
    entry.update(
        {
            "status": "posted",
            "posted_at": storage.iso_now(),
            "instagram_url": result.get("url") or "",
            "error": "",
            "error_details": "",
            "session_refreshed": bool(result.get("session_refreshed")),
        }
    )
    _remove_queue_item(queue, item["id"])
    message = "Posted to Instagram."
    if result.get("session_refreshed"):
        message += " The Instagram session was refreshed; update the IG_SESSION_JSON secret."
    return {
        "ok": True,
        "message": message,
        "details": "",
        "session": "refreshed" if result.get("session_refreshed") else "ok",
        "instagram_url": result.get("url") or "",
    }


def _generate(
    action: str,
    config: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    run_id: str,
    topic: str,
    style_override: Optional[int],
    slot_id: str,
    slot_key: str,
    mode: str,
    dry_run: bool,
) -> Dict[str, Any]:
    status.update("fetching", "Fetching fresh stories")
    candidates = fetch_candidates(
        config,
        history,
        topic_override=topic if topic in CATEGORY_LABELS else None,
        limit=25,
    )
    if not candidates:
        raise PipelineError(
            "No fresh stories matched your topics in the last 24 hours. Try again later or add topics.",
            "RSS and Hacker News returned no new, de-duplicated candidates.",
        )
    run_config = copy.deepcopy(config)
    if style_override is not None:
        run_config["style"] = style_override
    last_style = history.get("meta", {}).get("last_style")
    try:
        last_style_number = int(last_style) if last_style is not None else None
    except (TypeError, ValueError):
        last_style_number = None
    status.update("writing", "Choosing the strongest story")
    chain = LLMChain(run_config)
    pick = chain.pick_story(
        candidates,
        run_config,
        last_style=last_style_number,
        fixed_topic=topic if topic in CATEGORY_LABELS else None,
    )
    status.update(
        "writing",
        f"Story chosen with {pick['provider_label']}",
        provider_used=pick["provider"],
        provider_log=pick["log"],
    )
    data = pick["data"]
    candidate = candidates[data["story_index"]]
    style_number = _style_number(data.get("style")) or 1
    image_query = data["image_query"]
    status.update(
        "designing",
        f'Finding a photo for "{image_query}"',
        image_source=None,
        image_log=None,
    )
    card_id = storage.new_id("card")
    asset = fetch_image(
        image_query,
        config,
        history,
        article_url=candidate.url,
        article_source=candidate.source,
        seed=card_id,
    )
    credit_text = card_credit(asset, bool((config.get("image") or {}).get("show_credit", True)))
    caption = _final_caption(data["caption"], asset.caption_credit)
    status.update(
        "designing",
        f"Designing the card in {style_name(style_number)}",
        image_source=asset.source,
        image_log=asset.log,
    )
    logo_data_uri = load_logo_data_uri(config, root)
    payload = {
        "brand": config.get("brand") or {},
        "style": style_number,
        "headline": data["headline"],
        "description": data["description"],
        "category": data["category"],
        "category_label": CATEGORY_LABELS.get(data["category"], data["category"]),
        "credit_text": credit_text,
        "has_image": True,
        "has_logo": bool(logo_data_uri),
        "image_source": asset.provider_label,
    }
    messages = build_design_messages(payload)

    def validator(html: str) -> Tuple[bool, str]:
        return validate_design(
            html,
            headline=data["headline"],
            has_image=True,
            credit_required=credit_text,
            require_placeholder=True,
        )

    design_result = chain.design_html(messages, validator, max_calls=3)
    fallback_html = render_fallback(payload, asset.data_uri, logo_data_uri)
    final_html = (
        inject_media(design_result["html"], asset.data_uri, logo_data_uri)
        if design_result.get("html")
        else fallback_html
    )
    status.update(
        "rendering",
        "Rendering the 1080 x 1350 card",
        provider_used=design_result["provider"] or "fallback",
        design_provider=design_result["provider"] or "fallback",
        design_log=design_result["log"],
    )
    try:
        render_result = render_card(final_html, card_id, root=root, fallback_html=fallback_html)
    except RenderError as exc:
        raise PipelineError(
            "The card image could not be rendered. Check the run details and try again.",
            str(exc),
        ) from exc
    entry = _entry_for(
        card_id,
        run_id,
        action,
        config,
        pick,
        asset,
        design_result,
        render_result,
        candidates,
        caption,
        style_number,
        image_query,
        slot_id,
        slot_key,
        mode,
        dry_run,
    )
    history.setdefault("posts", []).append(entry)
    history.setdefault("meta", {})["last_style"] = style_number
    history["meta"]["last_run"] = storage.iso_now()
    storage.add_used_photo(
        history,
        asset.source,
        asset.photo_id,
        credit=asset.credit,
    )
    item = _queue_item(entry, "pending")
    _replace_queue_item(queue, item)
    _persist(root, history, queue)
    status.update(
        "rendering",
        "Card ready",
        queue_id=card_id,
        card_png=render_result["png"],
        card_jpg=render_result["jpg"],
        headline=entry["headline"],
        category=entry["category"],
        style=entry["style"],
        image_source=asset.source,
    )
    return {
        "entry": entry,
        "item": item,
        "render": render_result,
        "pick": pick,
        "design": design_result,
        "asset": asset,
    }


def _set_queue_pending(
    entry: Dict[str, Any],
    item: Dict[str, Any],
    queue: Dict[str, Any],
    mode: str,
) -> None:
    entry["status"] = "dry_run" if entry.get("dry_run") else "pending"
    entry["mode"] = mode
    item["status"] = "pending"
    item["mode"] = mode
    item["updated_at"] = storage.iso_now()
    _replace_queue_item(queue, item)


def _queue_only_done(
    status: StatusWriter, entry: Dict[str, Any], dry_run: bool, mode: str, action: str
) -> None:
    if dry_run:
        message = "Dry run complete. The card was added to the queue without posting."
    elif mode == "approve":
        message = "Card is waiting for your approval in the Queue."
    else:
        message = "Card is ready in the Queue."
    status.update(
        "done",
        message,
        queue_id=entry["id"],
        card_png=entry["png"],
        card_jpg=entry["jpg"],
        headline=entry["headline"],
        category=entry["category"],
        style=entry["style"],
        image_source=entry["image_source"],
        provider_used=entry["design_provider"],
        provider_log=entry["provider_log"],
        design_provider=entry["design_provider"],
        design_log=entry["design_log"],
        image_log=entry["image_log"],
        error=None,
        details=None,
    )


def _deliver_generated(
    generated: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    mode: str,
    dry_run: bool,
    action: str,
) -> bool:
    entry = generated["entry"]
    item = generated["item"]
    if dry_run:
        _set_queue_pending(entry, item, queue, mode)
        _persist(root, history, queue)
        _queue_only_done(status, entry, True, mode, action)
        return True
    if mode == "approve" or action == "generate_preview":
        _set_queue_pending(entry, item, queue, mode)
        _persist(root, history, queue)
        _queue_only_done(status, entry, False, "approve", action)
        return True
    result = _publish_item(item, entry, history, queue, status, root)
    _persist(root, history, queue)
    if result["ok"]:
        status.update(
            "done",
            result["message"],
            queue_id=entry["id"],
            card_jpg=entry["jpg"],
            card_png=entry["png"],
            headline=entry["headline"],
            category=entry["category"],
            style=entry["style"],
            image_source=entry["image_source"],
            instagram_url=result.get("instagram_url") or "",
            provider_used=entry["design_provider"],
            provider_log=entry["provider_log"],
            design_provider=entry["design_provider"],
            design_log=entry["design_log"],
            image_log=entry["image_log"],
            ig_session=result.get("session") or "ok",
            error=None,
            details=None,
        )
        return True
    status.update(
        "failed",
        result["message"],
        queue_id=entry["id"],
        card_jpg=entry["jpg"],
        card_png=entry["png"],
        headline=entry["headline"],
        category=entry["category"],
        style=entry["style"],
        image_source=entry["image_source"],
        provider_used=entry["design_provider"],
        provider_log=entry["provider_log"],
        design_provider=entry["design_provider"],
        design_log=entry["design_log"],
        image_log=entry["image_log"],
        ig_session=result.get("session") or None,
        error=result["message"],
        details=result["details"],
    )
    return False


def _analyse_regenerate(
    item: Dict[str, Any],
    config: Dict[str, Any],
    history: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    style_override: Optional[int],
) -> Tuple[bool, str, str]:
    headline = str(item.get("headline") or "")
    description = str(item.get("description") or "")
    category = str(item.get("category") or "world")
    style_number = _style_number(style_override or item.get("style")) or 1
    image_query = str(item.get("image_query") or "city skyline").strip() or "city skyline"
    status.update(
        "designing",
        f'Finding a new photo for "{image_query}"',
        image_source=None,
        image_log=None,
    )
    asset = fetch_image(
        image_query,
        config,
        history,
        article_url=str(item.get("story_url") or ""),
        article_source=str(item.get("story_source") or ""),
        seed=f"{item.get('id') or 'card'}-regen",
    )
    credit_text = card_credit(asset, bool((config.get("image") or {}).get("show_credit", True)))
    old_credit = str(item.get("image_caption_credit") or "")
    caption = _final_caption(
        str(item.get("caption") or ""),
        asset.caption_credit,
        old_credit=old_credit,
    )
    status.update(
        "designing",
        f"Redesigning in {style_name(style_number)}",
        image_source=asset.source,
        image_log=asset.log,
    )
    logo_data_uri = load_logo_data_uri(config, root)
    payload = {
        "brand": config.get("brand") or {},
        "style": style_number,
        "headline": headline,
        "description": description,
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, item.get("category_label") or category),
        "credit_text": credit_text,
        "has_image": True,
        "has_logo": bool(logo_data_uri),
        "image_source": asset.provider_label,
    }
    messages = build_design_messages(payload)

    def validator(html: str) -> Tuple[bool, str]:
        return validate_design(
            html,
            headline=headline,
            has_image=True,
            credit_required=credit_text,
            require_placeholder=True,
        )

    chain = LLMChain(config)
    design_result = chain.design_html(messages, validator, max_calls=3)
    fallback_html = render_fallback(payload, asset.data_uri, logo_data_uri)
    final_html = (
        inject_media(design_result["html"], asset.data_uri, logo_data_uri)
        if design_result.get("html")
        else fallback_html
    )
    status.update(
        "rendering",
        "Rendering the updated card",
        provider_used=design_result["provider"] or "fallback",
        design_provider=design_result["provider"] or "fallback",
        design_log=design_result["log"],
    )
    try:
        rendered = render_card(
            final_html,
            str(item["id"]),
            root=root,
            fallback_html=fallback_html,
        )
    except RenderError as exc:
        return False, "The card could not be re-rendered. Check the run details.", str(exc)
    item.update(
        {
            "status": "pending",
            "updated_at": storage.iso_now(),
            "style": style_number,
            "style_name": style_name(style_number),
            "caption": caption,
            "image_source": asset.source,
            "image_credit": credit_text,
            "image_caption_credit": asset.caption_credit,
            "image_photo_id": asset.photo_id,
            "image_log": asset.log,
            "design_provider": design_result["provider"] or "fallback",
            "design_log": design_result["log"],
            "png": rendered["png"],
            "jpg": rendered["jpg"],
            "error": "",
        }
    )
    entry = _find_history_entry(history, str(item.get("history_id") or item["id"]))
    if entry is None:
        entry = _entry_from_item(item)
        history.setdefault("posts", []).append(entry)
    entry.update(
        {
            "status": "pending",
            "style": style_number,
            "style_name": style_name(style_number),
            "caption": caption,
            "image_source": asset.source,
            "image_credit": credit_text,
            "image_caption_credit": asset.caption_credit,
            "image_photo_id": asset.photo_id,
            "image_query": image_query,
            "image_log": asset.log,
            "design_provider": design_result["provider"] or "fallback",
            "design_log": design_result["log"],
            "png": rendered["png"],
            "jpg": rendered["jpg"],
            "error": "",
            "error_details": "",
        }
    )
    storage.add_used_photo(history, asset.source, asset.photo_id, credit=asset.credit)
    history.setdefault("meta", {})["last_style"] = style_number
    history["meta"]["last_run"] = storage.iso_now()
    status.update(
        "rendering",
        "Updated card ready",
        queue_id=item["id"],
        card_png=rendered["png"],
        card_jpg=rendered["jpg"],
        headline=item["headline"],
        category=item["category"],
        style=style_number,
        image_source=asset.source,
    )
    return True, "", ""


def _action_tick(
    args: argparse.Namespace,
    config: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    run_id: str,
) -> bool:
    due = find_due_slot(config, history)
    if not due.get("due"):
        status.update("done", f"No post this time: {due.get('reason') or 'no slot is due'}.")
        return True
    if bool(config.get("posting_paused")):
        status.update("done", "Posting is paused. Resume it from the dashboard to post.")
        return True
    topic = args.topic or due.get("topic") or ""
    if topic and topic not in CATEGORY_LABELS:
        raise PipelineError("That topic is not one of the eight supported topics.")
    mode = due.get("slot_mode") or config.get("mode") or "approve"
    if args.dry_run:
        mode = "approve"
    generated = _generate(
        "tick",
        config,
        history,
        queue,
        status,
        root,
        run_id,
        topic,
        args.style,
        str(due.get("slot_id") or ""),
        str(due.get("slot_key") or ""),
        mode,
        bool(args.dry_run),
    )
    return _deliver_generated(
        generated, history, queue, status, root, mode, bool(args.dry_run), "tick"
    )


def _action_generate_preview(
    args: argparse.Namespace,
    config: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    run_id: str,
) -> bool:
    topic = args.topic or ""
    if topic and topic not in CATEGORY_LABELS:
        raise PipelineError("That topic is not one of the eight supported topics.")
    generated = _generate(
        "generate_preview",
        config,
        history,
        queue,
        status,
        root,
        run_id,
        topic,
        args.style,
        "",
        "",
        "approve",
        False,
    )
    _set_queue_pending(generated["entry"], generated["item"], queue, "approve")
    _persist(root, history, queue)
    _queue_only_done(status, generated["entry"], False, "approve", "generate_preview")
    return True


def _action_post_now(
    args: argparse.Namespace,
    config: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    run_id: str,
) -> bool:
    if bool(config.get("posting_paused")) and not args.dry_run:
        raise PipelineError(
            "Posting is paused. Resume posting from the dashboard, then try again."
        )
    topic = args.topic or ""
    if topic and topic not in CATEGORY_LABELS:
        raise PipelineError("That topic is not one of the eight supported topics.")
    generated = _generate(
        "post_now",
        config,
        history,
        queue,
        status,
        root,
        run_id,
        topic,
        args.style,
        "",
        "",
        "auto",
        bool(args.dry_run),
    )
    return _deliver_generated(
        generated, history, queue, status, root, "auto", bool(args.dry_run), "post_now"
    )


def _action_publish_queued(
    args: argparse.Namespace,
    config: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    run_id: str,
) -> bool:
    if bool(config.get("posting_paused")):
        raise PipelineError(
            "Posting is paused. Resume posting from the dashboard, then approve the card again."
        )
    items = [
        item
        for item in queue.get("items") or []
        if isinstance(item, dict) and item.get("status") in ("pending", "failed")
    ]
    item = _find_queue_item(queue, args.queue_id) if args.queue_id else (items[0] if items else None)
    if item is None or item.get("status") not in ("pending", "failed"):
        raise PipelineError(
            "There is no card to publish. It may already have been posted or discarded.",
            f"queue_id={args.queue_id or '(first pending)'}",
        )
    if args.dry_run:
        status.update(
            "done",
            "Dry run: the card would be published.",
            queue_id=item["id"],
            card_jpg=item.get("jpg"),
            headline=item.get("headline"),
            details=None,
        )
        return True
    if item.get("slot_key"):
        for other in history.get("posts") or []:
            if (
                isinstance(other, dict)
                and other.get("slot_key") == item.get("slot_key")
                and other.get("status") == "posted"
                and other.get("id") != item.get("id")
            ):
                raise PipelineError(
                    "That slot already has a posted card, so this one was not published.",
                    f"slot_key={item.get('slot_key')}",
                )
    jpg_path = storage.cards_dir(root) / Path(str(item.get("jpg") or "")).name
    if not jpg_path.is_file():
        raise PipelineError(
            "The card image is missing. Tap Regenerate on the queue card, then approve again.",
            f"missing={jpg_path.name}",
        )
    entry = _find_history_entry(history, str(item.get("history_id") or item.get("id")))
    if entry is None:
        entry = _entry_from_item(item)
        history.setdefault("posts", []).append(entry)
    entry.update(
        {
            "caption": item.get("caption") or entry.get("caption"),
            "style": item.get("style") or entry.get("style"),
            "style_name": item.get("style_name") or entry.get("style_name"),
            "mode": "approve",
        }
    )
    result = _publish_item(item, entry, history, queue, status, root)
    _persist(root, history, queue)
    if result["ok"]:
        status.update(
            "done",
            result["message"],
            queue_id=item["id"],
            card_jpg=item.get("jpg"),
            card_png=item.get("png"),
            headline=item.get("headline"),
            category=item.get("category"),
            style=item.get("style"),
            image_source=item.get("image_source"),
            instagram_url=result.get("instagram_url") or "",
            ig_session=result.get("session") or "ok",
            provider_used=item.get("design_provider"),
            design_provider=item.get("design_provider"),
            design_log=item.get("design_log"),
            provider_log=item.get("provider_log"),
            image_log=item.get("image_log"),
            error=None,
            details=None,
        )
        return True
    status.update(
        "failed",
        result["message"],
        queue_id=item["id"],
        card_jpg=item.get("jpg"),
        card_png=item.get("png"),
        headline=item.get("headline"),
        category=item.get("category"),
        style=item.get("style"),
        image_source=item.get("image_source"),
        ig_session=result.get("session") or None,
        provider_used=item.get("design_provider"),
        design_provider=item.get("design_provider"),
        design_log=item.get("design_log"),
        provider_log=item.get("provider_log"),
        image_log=item.get("image_log"),
        error=result["message"],
        details=result["details"],
    )
    return False


def _action_regenerate(
    args: argparse.Namespace,
    config: Dict[str, Any],
    history: Dict[str, Any],
    queue: Dict[str, Any],
    status: StatusWriter,
    root: Path,
    run_id: str,
) -> bool:
    items = [item for item in queue.get("items") or [] if isinstance(item, dict)]
    item = _find_queue_item(queue, args.queue_id) if args.queue_id else (items[0] if items else None)
    if item is None:
        raise PipelineError(
            "There is no queued card to regenerate. Generate a preview first."
        )
    status.update(
        "queued",
        "Regenerating the queued card",
        queue_id=item["id"],
        headline=item.get("headline"),
        category=item.get("category"),
        style=item.get("style"),
        image_source=item.get("image_source"),
    )
    ok, message, details = _analyse_regenerate(
        item, config, history, status, root, args.style
    )
    if not ok:
        _replace_queue_item(queue, item)
        entry = _find_history_entry(history, str(item.get("history_id") or item["id"]))
        if entry is not None:
            entry.update({"status": "failed", "error": message, "error_details": details})
        _persist(root, history, queue)
        raise PipelineError(message, details)
    _replace_queue_item(queue, item)
    _persist(root, history, queue)
    status.update(
        "done",
        "Card regenerated and waiting for approval.",
        queue_id=item["id"],
        card_png=item.get("png"),
        card_jpg=item.get("jpg"),
        headline=item.get("headline"),
        category=item.get("category"),
        style=item.get("style"),
        image_source=item.get("image_source"),
        provider_used=item.get("design_provider"),
        design_provider=item.get("design_provider"),
        design_log=item.get("design_log"),
        provider_log=item.get("provider_log"),
        image_log=item.get("image_log"),
        error=None,
        details=None,
    )
    return True


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NewsCard Studio pipeline")
    parser.add_argument(
        "--action",
        default="tick",
        choices=[
            "tick",
            "generate_preview",
            "post_now",
            "publish_queued",
            "regenerate",
        ],
    )
    parser.add_argument("--topic", default="")
    parser.add_argument("--style", type=int, default=0)
    parser.add_argument("--queue-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    load_env()
    args = _parse_args(argv)
    if args.style and not 1 <= args.style <= 20:
        print("[run] --style must be 1-20", file=sys.stderr)
        return 2
    root = storage.repo_root()
    config = storage.load_config(root)
    history = storage.load_history(root)
    queue = storage.load_queue(root)
    run_id = storage.new_id("run")
    dry_run = bool(args.dry_run) or args.action == "generate_preview"
    status = StatusWriter(root, run_id, args.action, dry_run)
    status.update("queued", "Run queued.")
    print(
        f"[run] {run_id} action={args.action} dry_run={dry_run} "
        f"providers={', '.join(LLMChain(config).providers_available()) or 'rule-based'}"
    )
    try:
        if args.action == "tick":
            ok = _action_tick(args, config, history, queue, status, root, run_id)
        elif args.action == "generate_preview":
            ok = _action_generate_preview(
                args, config, history, queue, status, root, run_id
            )
        elif args.action == "post_now":
            ok = _action_post_now(args, config, history, queue, status, root, run_id)
        elif args.action == "publish_queued":
            ok = _action_publish_queued(
                args, config, history, queue, status, root, run_id
            )
        else:
            ok = _action_regenerate(args, config, history, queue, status, root, run_id)
    except PipelineError as exc:
        print(f"[run] failed: {exc.friendly}")
        status.update("failed", exc.friendly, error=exc.friendly, details=exc.details)
        return 1
    except Exception as exc:  # noqa: BLE001 - the run must leave a readable status
        details = f"{type(exc).__name__}: {exc}"
        print(f"[run] unexpected failure: {details}")
        status.update(
            "failed",
            "Something went wrong during the run. Check the details and try again.",
            error="Unexpected pipeline error",
            details=details,
        )
        return 1
    finally:
        _persist(root, history, queue)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
