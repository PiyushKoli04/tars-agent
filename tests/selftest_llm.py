"""Offline self-test for the LLM provider chain.

Run from the repo root:

    python -m tests.selftest_llm

No network access is used: ``requests.post`` is replaced with fake responses.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import llm  # noqa: E402
from core.news import Candidate  # noqa: E402

ENV_KEYS = [
    "NVIDIA_API_KEY",
    "NVIDIA_MODEL",
    "NVIDIA_BASE_URL",
    "OPENCODE_API_KEY",
    "OPENCODE_MODEL",
    "OPENCODE_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_BASE_URL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GROQ_BASE_URL",
]

CONFIG = {
    "style": "auto",
    "avoid_repeat_style": True,
    "topics": {
        "tech_ai": True,
        "business": True,
        "science_space": True,
        "world": True,
        "sports": True,
        "health": True,
        "entertainment": True,
        "environment": True,
    },
    "llm": {"order": ["nvidia", "opencode", "gemini", "groq"], "disabled": []},
}

VALID = {
    "story_index": 0,
    "category": "tech_ai",
    "headline": "Satellite network opens a faster era for global internet",
    "description": "A new satellite constellation promises faster internet access worldwide with first commercial service starting this year.",
    "caption": (
        "Satellite internet is getting faster as a new constellation enters service. "
        "#space #technews #satellite #internet #orbit #science #innovation #future "
        "#global #news"
    ),
    "image_query": "satellite ground station",
    "style": 7,
}
VALID_JSON = json.dumps(VALID)


def clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def configure_all() -> None:
    clear_env()
    os.environ.update(
        {
            "NVIDIA_API_KEY": "fake-nvidia-key",
            "NVIDIA_MODEL": "fake-nemotron",
            "NVIDIA_BASE_URL": "https://fake-nvidia.test/v1",
            "OPENCODE_API_KEY": "fake-opencode-key",
            "OPENCODE_MODEL": "fake-glm",
            "OPENCODE_BASE_URL": "https://fake-opencode.test/v1",
            "GEMINI_API_KEY": "fake-gemini-key",
            "GEMINI_MODEL": "fake-gemini",
            "GEMINI_BASE_URL": "https://fake-gemini.test/v1",
            "GROQ_API_KEY": "fake-groq-key",
            "GROQ_MODEL": "fake-groq",
            "GROQ_BASE_URL": "https://fake-groq.test/v1",
        }
    )


def candidates() -> list:
    return [
        Candidate(
            title="Satellite network opens a faster era for global internet",
            url="https://example.com/satellite-network",
            source="The Verge",
            category="tech_ai",
            summary=(
                "A new satellite constellation promises faster internet access "
                "worldwide with first commercial service starting this year."
            ),
            published_ts=0,
            score=55.0,
            title_norm="satellite network opens a faster era for global internet",
            age_minutes=30,
        )
    ]


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def content_response(content: str) -> FakeResponse:
    return FakeResponse(
        200, {"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


def test_pick_chain_falls_through() -> None:
    configure_all()
    original_post = llm.requests.post
    original_delay = llm.RETRY_DELAY
    llm.RETRY_DELAY = 0
    calls = {"nvidia": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        if "fake-nvidia" in url:
            calls["nvidia"] += 1
            return FakeResponse(429, text="slow down")
        if "fake-opencode" in url:
            return FakeResponse(401, text="unauthorized")
        if "fake-gemini" in url:
            return content_response("Sure:\n```json\n{story_index: 0}\n```")
        if "fake-groq" in url:
            return content_response(
                "<thinking>hidden reasoning</thinking>\n```json\n" + VALID_JSON + "\n```"
            )
        return FakeResponse(500, text="unexpected")

    llm.requests.post = fake_post
    try:
        chain = llm.LLMChain(CONFIG)
        result = chain.pick_story(candidates(), CONFIG, last_style=3)
    finally:
        llm.requests.post = original_post
        llm.RETRY_DELAY = original_delay

    assert calls["nvidia"] == 2, f"expected one retry, got {calls['nvidia']}"
    assert result["provider"] == "groq", result
    assert result["data"]["style"] == 7
    assert "nvidia: HTTP 429" in result["log"], result["log"]
    assert "opencode: bad key" in result["log"], result["log"]
    assert "gemini: invalid JSON" in result["log"], result["log"]
    assert "groq: ok" in result["log"], result["log"]
    assert "opencode" in chain.bad_keys
    print("PASS pick chain skips 429, bad key and garbage, then succeeds")


def test_rule_based_without_keys() -> None:
    clear_env()
    chain = llm.LLMChain(CONFIG)
    assert chain.providers_available() == []
    result = chain.pick_story(candidates(), CONFIG, last_style=3)
    data = result["data"]
    assert result["provider"] == "rule-based", result
    assert result["fallback"] is True
    assert len(data["headline"].split()) <= 12
    assert len(data["description"].split()) <= 25
    tags = re.findall(r"#[A-Za-z0-9_]+", data["caption"])
    assert 8 <= len(tags) <= 12, tags
    assert data["style"] != 3
    assert "rule-based: ok" in result["log"]
    print("PASS rule-based editor works with zero LLM keys")


def test_design_sanitization_and_retry() -> None:
    clear_env()
    os.environ.update(
        {
            "GROQ_API_KEY": "fake-groq-key",
            "GROQ_MODEL": "fake-groq",
            "GROQ_BASE_URL": "https://fake-groq.test/v1",
        }
    )
    valid_html = (
        "<!DOCTYPE html><html><head><style>"
        ".canvas{width:1080px;height:1350px;overflow:hidden;padding:64px}"
        "</style></head><body><div class=\"canvas\">"
        "<h1 style=\"font-size:72px\">Orbital test</h1>"
        "<img src=\"{{IMAGE}}\" onerror=\"alert(1)\">"
        "<script>alert(2)</script>"
        "<p>Photo by Jane / Unsplash</p></div></body></html>"
    )
    calls = {"n": 0}
    original_post = llm.requests.post

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return content_response(
                "<!DOCTYPE html><html><body>no placeholder</body></html>"
            )
        return content_response(valid_html)

    def validator(html: str):
        if "{{IMAGE}}" not in html:
            return False, "placeholder missing"
        if "Orbital test" not in html:
            return False, "headline missing"
        if "<script" in html.lower():
            return False, "script tag"
        if "onerror" in html.lower():
            return False, "event handler"
        return True, ""

    llm.requests.post = fake_post
    try:
        chain = llm.LLMChain(CONFIG)
        result = chain.design_html([{"role": "user", "content": "make it"}], validator)
    finally:
        llm.requests.post = original_post
    assert result["provider"] == "groq", result
    assert "{{IMAGE}}" in result["html"]
    assert "<script" not in result["html"].lower()
    assert "onerror" not in result["html"].lower()
    assert calls["n"] == 2, calls
    print("PASS design retry + script stripping works")


def test_helpers() -> None:
    parsed = llm.extract_json('prefix ```json\n{"a": 1, "b": [2, 3],}\n``` suffix')
    assert parsed == {"a": 1, "b": [2, 3]}, parsed
    parsed = llm.extract_json('<thinking>secret</thinking>{"ok": true}')
    assert parsed == {"ok": True}, parsed
    assert llm.extract_json("no json here") is None
    html = llm.sanitize_html(
        '<!DOCTYPE html><html><script>alert(1)</script>'
        '<img src="{{IMAGE}}" onerror="x"></html>'
    )
    assert "<script" not in html.lower()
    assert "onerror" not in html.lower()
    print("PASS JSON repair and HTML sanitizer")


def main() -> None:
    tests = [
        test_pick_chain_falls_through,
        test_rule_based_without_keys,
        test_design_sanitization_and_retry,
        test_helpers,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} LLM self-tests passed.")


if __name__ == "__main__":
    main()
