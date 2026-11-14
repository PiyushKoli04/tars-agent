"""Instagram publishing with instagrapi and a saved session.

Normal runs never log in with a password. It only falls back to one fresh login
when the saved session is invalid and IG_USERNAME/IG_PASSWORD are present. The
refreshed settings are written to the gitignored tmp/ directory for the operator.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.storage import repo_root


class PostError(RuntimeError):
    def __init__(self, message: str, details: str = "", session_problem: bool = False):
        super().__init__(message)
        self.friendly = message
        self.details = details or message
        self.session_problem = session_problem


def _read_session(
    root: Optional[Path] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = (os.environ.get("IG_SESSION_JSON") or "").strip()
    source = "IG_SESSION_JSON"
    if not raw:
        base = root or repo_root()
        for candidate in (base / "tmp" / "ig_session.json", base / "ig_session.json"):
            try:
                if candidate.is_file():
                    raw = candidate.read_text(encoding="utf-8").strip()
                    source = candidate.name
                    break
            except OSError:
                continue
    if not raw:
        return None, ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        if raw.startswith("{") or raw.startswith("["):
            raise PostError(
                "The Instagram session secret is not valid JSON.",
                "IG_SESSION_JSON could not be decoded.",
                session_problem=True,
            )
        return {"sessionid": raw}, source
    if isinstance(parsed, dict):
        settings = parsed.get("settings") if isinstance(parsed.get("settings"), dict) else parsed
        if isinstance(settings, dict):
            return settings, source
    return None, source


def _client_for_session(settings: Dict[str, Any]):
    from instagrapi import Client

    client = Client()
    client.delay_range = [1, 3]
    cookies = settings.get("cookies") if isinstance(settings.get("cookies"), dict) else {}
    authorization = (
        settings.get("authorization_data")
        if isinstance(settings.get("authorization_data"), dict)
        else {}
    )
    sessionid = str(
        settings.get("sessionid")
        or cookies.get("sessionid")
        or authorization.get("sessionid")
        or ""
    ).strip()
    if not sessionid:
        raise PostError(
            "The Instagram session secret has no sessionid.",
            "IG_SESSION_JSON must be the JSON produced by tools/get_session.py.",
            session_problem=True,
        )
    if settings.get("uuids") and (cookies.get("sessionid") or authorization.get("sessionid")):
        client.set_settings(settings)
        return client
    try:
        client.login_by_sessionid(sessionid)
    except Exception as exc:
        raise PostError(
            "Instagram did not accept the saved session.",
            type(exc).__name__,
            session_problem=True,
        ) from exc
    return client


def _neutralize_instagram_expose(client) -> None:
    if callable(getattr(client, "expose", None)):
        client.expose = lambda: {}


def _classify(exc: Exception) -> Tuple[str, str, bool]:
    name = type(exc).__name__
    text = str(exc)
    lowered = f"{name} {text}".lower()
    if any(token in lowered for token in ("loginrequired", "login required", "not logged in")):
        return (
            "The Instagram session has expired. Refresh it with tools/get_session.py and update the IG_SESSION_JSON secret.",
            text,
            True,
        )
    if any(
        token in lowered
        for token in (
            "challengerequired",
            "challenge_error",
            "challenge",
            "checkpoint",
            "captcha",
            "twofactor",
        )
    ):
        return (
            "Instagram asked for a security check. Open Instagram on your phone, approve the login, then run tools/get_session.py again and update the secret.",
            text,
            True,
        )
    if any(
        token in lowered
        for token in ("ratelimit", "rate limit", "pleasewaitfewminutes", "too many requests", "429")
    ):
        return (
            "Instagram is rate-limiting this account. Wait a few hours before trying again.",
            text,
            False,
        )
    if any(token in lowered for token in ("mediarequires", "mediaerror", "video", "photo", "upload")):
        return (
            "Instagram rejected the image upload. Check the card file and try again.",
            text,
            False,
        )
    return (
        "Instagram could not publish the card. Check the run details and try again later.",
        f"{name}: {text}",
        False,
    )


def _save_refreshed(client, root: Path) -> str:
    target = root / "tmp" / "ig_session.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = client.get_settings()
    target.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return str(target)


def _fresh_login(client, root: Path) -> str:
    username = (os.environ.get("IG_USERNAME") or "").strip()
    password = (os.environ.get("IG_PASSWORD") or "").strip()
    if not username or not password:
        raise PostError(
            "The Instagram session has expired and no fallback username/password secret is set. Refresh the session locally with tools/get_session.py.",
            "No IG_USERNAME or IG_PASSWORD available for a one-time refresh.",
            session_problem=True,
        )
    from instagrapi.exceptions import TwoFactorRequired

    try:
        client.login(username, password)
    except TwoFactorRequired as exc:
        raise PostError(
            "Instagram wants a two-factor code. Run tools/get_session.py locally to create a fresh session.",
            str(exc),
            session_problem=True,
        ) from exc
    except Exception as exc:
        message, details, session_problem = _classify(exc)
        raise PostError(message, details, session_problem) from exc
    return _save_refreshed(client, root)


def publish_card(
    jpg_path: str,
    caption: str,
    dry_run: bool = False,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    if dry_run:
        return {
            "posted": False,
            "dry_run": True,
            "url": "",
            "media_id": "",
            "session_refreshed": False,
            "delay_seconds": 0,
        }
    path = Path(jpg_path)
    if not path.is_file():
        raise PostError("The card image is missing, so nothing was posted.", str(path))
    try:
        settings, source = _read_session(root)
    except PostError:
        raise
    if not settings:
        raise PostError(
            "Instagram is not connected yet. Add the IG_SESSION_JSON secret or run tools/get_session.py locally.",
            "No IG_SESSION_JSON secret and no local ig_session.json file.",
            session_problem=True,
        )
    client = _client_for_session(settings)
    _neutralize_instagram_expose(client)
    base = root or repo_root()
    refreshed = False
    delay_override = os.environ.get("NEWSCARD_POST_DELAY_SECONDS")
    if delay_override is not None:
        try:
            delay = max(0.0, min(120.0, float(delay_override)))
        except ValueError:
            delay = random.uniform(5, 20)
    else:
        delay = random.uniform(5, 20)
    time.sleep(delay)
    try:
        media = client.photo_upload(path, caption)
    except Exception as exc:
        message, details, session_problem = _classify(exc)
        if session_problem:
            try:
                client.login_required = True
            except Exception:
                pass
            try:
                _fresh_login(client, base)
                refreshed = True
                time.sleep(2)
                media = client.photo_upload(path, caption)
            except PostError:
                raise
            except Exception as second_exc:
                second_message, second_details, second_flag = _classify(second_exc)
                raise PostError(second_message, second_details, second_flag) from second_exc
        else:
            raise PostError(message, details, session_problem) from exc
    code = str(getattr(media, "code", "") or "")
    media_id = str(getattr(media, "pk", "") or getattr(media, "id", "") or "")
    url = f"https://www.instagram.com/p/{code}/" if code else "https://www.instagram.com/"
    return {
        "posted": True,
        "dry_run": False,
        "url": url,
        "media_id": media_id,
        "session_refreshed": refreshed,
        "delay_seconds": round(delay, 1),
        "session_source": source,
    }
