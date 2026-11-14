"""Offline self-test for Instagram session handling and publishing guards.

Run from the repo root:

    python -m tests.selftest_post

No network access is used. The instagrapi Client is replaced with a fake.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import post  # noqa: E402

ENV_KEYS = [
    "IG_SESSION_JSON",
    "IG_USERNAME",
    "IG_PASSWORD",
    "NEWSCARD_POST_DELAY_SECONDS",
]


class FakeMedia:
    code = "abc123"
    pk = "987654"


class FakeClient:
    instances = []

    def __init__(self):
        self.settings = None
        self.login_calls = []
        self.uploads = []
        self.delay_range = None
        FakeClient.instances.append(self)

    def set_settings(self, settings):
        self.settings = settings
        return True

    def login_by_sessionid(self, sessionid):
        self.login_calls.append(sessionid)
        return True

    def expose(self):
        raise RuntimeError(
            "ClientNotFoundError: 404 Client Error: Not Found for url: "
            "https://i.instagram.com/api/v1/qe/expose/"
        )

    def photo_upload(self, path, caption):
        self.uploads.append((str(path), caption))
        self.expose()
        return FakeMedia()

    def get_settings(self):
        return dict(self.settings or {})


def clear_env() -> dict:
    saved = {key: os.environ.get(key) for key in ENV_KEYS}
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    return saved


def restore_env(saved: dict) -> None:
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def install_fake_instagrapi() -> object:
    fake = types.ModuleType("instagrapi")
    fake.Client = FakeClient
    fake.exceptions = types.SimpleNamespace(TwoFactorRequired=type("TwoFactorRequired", (Exception,), {}))
    previous = sys.modules.get("instagrapi")
    sys.modules["instagrapi"] = fake
    return previous


def remove_fake_instagrapi(previous) -> None:
    if previous is None:
        sys.modules.pop("instagrapi", None)
    else:
        sys.modules["instagrapi"] = previous


def test_dry_run_needs_no_session() -> None:
    saved = clear_env()
    try:
        result = post.publish_card("missing.jpg", "Caption", dry_run=True)
    finally:
        restore_env(saved)
    assert result["posted"] is False and result["dry_run"] is True, result
    assert result["delay_seconds"] == 0
    print("PASS dry run returns before file and session checks")


def test_missing_file_and_session_errors() -> None:
    saved = clear_env()
    try:
        try:
            post.publish_card("missing.jpg", "Caption", dry_run=False)
        except post.PostError as exc:
            assert "missing" in exc.friendly.lower(), exc.friendly
        else:
            raise AssertionError("missing card should fail")

        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "card.jpg"
            card.write_bytes(b"not-a-real-image")
            try:
                post.publish_card(str(card), "Caption", dry_run=False, root=Path(directory))
            except post.PostError as exc:
                assert exc.session_problem, exc.details
                assert "not connected" in exc.friendly.lower(), exc.friendly
            else:
                raise AssertionError("missing session should fail")
    finally:
        restore_env(saved)
    print("PASS missing files and missing sessions raise friendly errors")


def test_session_parsing() -> None:
    saved = clear_env()
    try:
        os.environ["IG_SESSION_JSON"] = "sessionid-only"
        settings, source = post._read_session()
        assert settings == {"sessionid": "sessionid-only"}, settings
        assert source == "IG_SESSION_JSON"

        os.environ["IG_SESSION_JSON"] = '{"settings": {"sessionid": "nested", "cookies": {"sessionid": "nested"}}}'
        settings, _ = post._read_session()
        assert settings["sessionid"] == "nested", settings

        os.environ["IG_SESSION_JSON"] = "{bad json"
        try:
            post._read_session()
        except post.PostError as exc:
            assert exc.session_problem, exc.details
            assert "not valid JSON" in exc.friendly
        else:
            raise AssertionError("invalid JSON session should fail")
    finally:
        restore_env(saved)
    print("PASS session JSON, sessionid shortcuts and bad JSON are handled")


def test_publish_with_saved_session() -> None:
    saved = clear_env()
    previous = install_fake_instagrapi()
    try:
        os.environ["IG_SESSION_JSON"] = (
            '{"uuids": {"uuid": "1"}, "cookies": {"sessionid": "sid"}, '
            '"sessionid": "sid"}'
        )
        os.environ["NEWSCARD_POST_DELAY_SECONDS"] = "0"
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "card.jpg"
            card.write_bytes(b"jpeg-bytes")
            result = post.publish_card(
                str(card),
                "Caption with #hashtags",
                dry_run=False,
                root=Path(directory),
            )
        assert result["posted"] is True, result
        assert result["url"] == "https://www.instagram.com/p/abc123/", result
        assert result["media_id"] == "987654", result
        assert result["delay_seconds"] == 0
        client = FakeClient.instances[-1]
        assert client.settings is not None
        assert client.uploads and client.uploads[0][1] == "Caption with #hashtags"
        assert client.expose() == {}
    finally:
        remove_fake_instagrapi(previous)
        restore_env(saved)
    print("PASS saved settings upload a card and return the post URL")


def test_publish_with_sessionid_login() -> None:
    saved = clear_env()
    previous = install_fake_instagrapi()
    try:
        os.environ["IG_SESSION_JSON"] = "raw-session-id"
        os.environ["NEWSCARD_POST_DELAY_SECONDS"] = "0"
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "card.jpg"
            card.write_bytes(b"jpeg-bytes")
            post.publish_card(str(card), "Caption", dry_run=False, root=Path(directory))
        client = FakeClient.instances[-1]
        assert client.login_calls == ["raw-session-id"], client.login_calls
    finally:
        remove_fake_instagrapi(previous)
        restore_env(saved)
    print("PASS a bare sessionid uses login_by_sessionid")


def test_error_classification() -> None:
    class LoginRequired(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class PhotoUploadError(Exception):
        pass

    message, _, session = post._classify(LoginRequired("expired"))
    assert session and "session" in message.lower(), message
    message, _, session = post._classify(RateLimitError("429"))
    assert not session and "rate" in message.lower(), message
    message, _, session = post._classify(PhotoUploadError("bad image"))
    assert not session and "image" in message.lower(), message
    message, _, session = post._classify(ValueError("something else"))
    assert not session and "could not publish" in message.lower(), message
    print("PASS Instagram errors map to actionable messages")


def main() -> None:
    tests = [
        test_dry_run_needs_no_session,
        test_missing_file_and_session_errors,
        test_session_parsing,
        test_publish_with_saved_session,
        test_publish_with_sessionid_login,
        test_error_classification,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} post self-tests passed.")


if __name__ == "__main__":
    main()