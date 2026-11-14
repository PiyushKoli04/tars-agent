"""LLM provider chain using plain ``requests`` against OpenAI-compatible APIs.

The chain is deliberately defensive: no exception ever escapes to the caller.
Worst case the rule-based editor produces the story and copy, so a post can
never be missed because every model is down or misconfigured.

Design output is model-written HTML. It is treated as untrusted data only:
sanitised, validated with static checks and rendered by headless Chrome. It is
never executed as code, and the renderer loads no model-provided scripts.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from core.news import CATEGORY_HASHTAGS, CATEGORY_LABELS, CATEGORY_SCENES

RETRY_DELAY = 2.0
REQUEST_TIMEOUT = 45

DEFAULT_ORDER = ["nvidia", "opencode", "gemini", "groq"]

PROVIDER_META: Dict[str, Dict[str, str]] = {
    "nvidia": {
        "label": "NVIDIA Nemotron",
        "base_default": "https://integrate.api.nvidia.com/v1",
        "base_env": "NVIDIA_BASE_URL",
        "key_env": "NVIDIA_API_KEY",
        "model_env": "NVIDIA_MODEL",
    },
    "opencode": {
        "label": "OpenCode (GLM 5.3)",
        "base_default": "",
        "base_env": "OPENCODE_BASE_URL",
        "key_env": "OPENCODE_API_KEY",
        "model_env": "OPENCODE_MODEL",
    },
    "gemini": {
        "label": "Google Gemini",
        "base_default": "https://generativelanguage.googleapis.com/v1beta/openai",
        "base_env": "GEMINI_BASE_URL",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
    },
    "groq": {
        "label": "Groq",
        "base_default": "https://api.groq.com/openai/v1",
        "base_env": "GROQ_BASE_URL",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
    },
}

PROVIDER_LABELS = {k: v["label"] for k, v in PROVIDER_META.items()}
PROVIDER_LABELS["rule-based"] = "Rule-based editor"
PROVIDER_LABELS["fallback"] = "Fallback template"


class BadKey(Exception):
    """Authentication failed; skip this provider for the rest of the run."""


class ProviderFailure(Exception):
    """Transient or malformed provider response; move to the next provider."""


_THINK_RE = re.compile(r"<\s*think(?:ing)?\b[^>]*>.*?<\s*/\s*think(?:ing)?\s*>", re.I | re.S)
_FENCE_RE = re.compile(r"```(?:json|html|HTML|JSON)?\s*(.*?)```", re.S)


def label_for(provider_id: Optional[str]) -> str:
    if not provider_id:
        return "Rule-based editor"
    return PROVIDER_LABELS.get(provider_id, provider_id)


def strip_reasoning(text: str) -> str:
    text = _THINK_RE.sub("", text or "")
    text = re.sub(r"(?is)<\s*thinking\b[^>]*>.*?<\s*/\s*thinking\s*>", "", text)
    return text


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Repair and parse the first JSON object in a model reply."""
    if not text:
        return None
    cleaned = strip_reasoning(text).strip()
    fence = _FENCE_RE.search(cleaned)
    if fence and "{" in fence.group(1):
        cleaned = fence.group(1).strip()
    if cleaned.startswith("{"):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for position in range(start, len(cleaned)):
        char = cleaned[position]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                chunk = cleaned[start : position + 1]
                for candidate in (
                    chunk,
                    re.sub(r",\s*([}\]])", r"\1", chunk),
                ):
                    try:
                        parsed = json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(parsed, dict):
                        return parsed
                return None
    return None


def sanitize_html(raw: str) -> str:
    """Take model HTML as untrusted input and remove executable content."""
    text = strip_reasoning(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html|HTML)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    lowered = text.lower()
    anchor = lowered.find("<!doctype")
    if anchor < 0:
        anchor = lowered.find("<html")
    if anchor > 0:
        text = text[anchor:]
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script\s*>", "", text)
    text = re.sub(r"(?is)<script\b[^>]*/?>", "", text)
    text = re.sub(r"(?is)<iframe\b[^>]*>.*?</iframe\s*>", "", text)
    text = re.sub(r"(?is)<(iframe|object|embed|frame|frameset|applet)\b[^>]*/?>", "", text)
    text = re.sub(r"""(?is)\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", "", text)
    text = re.sub(r"""(?is)javascript\s*:""", "about:blank", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def _trim_words(text: str, limit: int) -> str:
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    return " ".join(words[:limit])


def _unique_hashtags(tags: List[str], desired: int = 10) -> List[str]:
    seen: List[str] = []
    for tag in tags:
        clean = "#" + re.sub(r"[^A-Za-z0-9_]", "", tag.lstrip("#"))
        if len(clean) > 2 and clean not in seen:
            seen.append(clean)
    return seen[:desired]


def auto_style(config: Dict[str, Any], last_style: Optional[int]) -> int:
    raw = config.get("style", "auto")
    try:
        fixed = int(raw)
        if 1 <= fixed <= 20:
            return fixed
    except (TypeError, ValueError):
        pass
    avoid = bool(config.get("avoid_repeat_style", True))
    choices = list(range(1, 21))
    if avoid and last_style in choices and len(choices) > 1:
        choices = [n for n in choices if n != last_style]
    return random.choice(choices)


def rule_based_pick(
    candidates: List[Any],
    config: Dict[str, Any],
    last_style: Optional[int] = None,
) -> Dict[str, Any]:
    """No-LLM editor: newest highest-scored story, factual copy, generic tags."""
    candidate = candidates[0]
    headline = _trim_words(candidate.title.strip().rstrip("."), 12)
    description = _trim_words(
        (candidate.summary or candidate.title).strip().rstrip("."), 25
    )
    tags = _unique_hashtags(
        list(CATEGORY_HASHTAGS.get(candidate.category, []))
        + ["#news", "#today", "#brief", "#daily", "#read"],
        10,
    )
    caption = f"{headline}\n\n{description}\n\n{' '.join(tags)}"
    caption = caption[:600].rstrip()
    hashtag_count = len(re.findall(r"#[A-Za-z0-9_]+", caption))
    if hashtag_count < 8:
        extra = _unique_hashtags(tags + ["#newsupdate", "#headlines", "#worldnews"], 12)
        while len(extra) > hashtag_count and len(caption) + len(extra[-1]) + 1 <= 600:
            caption += " " + extra[hashtag_count]
            hashtag_count += 1
    return {
        "story_index": 0,
        "category": candidate.category,
        "headline": headline,
        "description": description,
        "caption": caption,
        "image_query": CATEGORY_SCENES.get(candidate.category, "city skyline"),
        "style": auto_style(config, last_style),
    }


def _validate_pick(
    data: Any,
    candidates: List[Any],
    config: Dict[str, Any],
    last_style: Optional[int],
    fixed_style: Optional[int],
    fixed_topic: Optional[str],
) -> Tuple[bool, Any]:
    if not isinstance(data, dict):
        return False, "not a JSON object"
    required = (
        "story_index",
        "category",
        "headline",
        "description",
        "caption",
        "image_query",
        "style",
    )
    for key in required:
        if key not in data:
            return False, f"missing {key}"
    index = data.get("story_index")
    if isinstance(index, bool) or not isinstance(index, int):
        return False, "story_index must be an integer"
    if index < 0 or index >= len(candidates):
        return False, "story_index out of range"
    candidate = candidates[index]
    category = data.get("category")
    if category not in CATEGORY_LABELS:
        return False, "unknown category"
    if category != candidate.category:
        return False, "category does not match the chosen story"
    if not bool((config.get("topics") or {}).get(category)):
        return False, "category is disabled"
    if fixed_topic and category != fixed_topic:
        return False, "category does not match the slot topic"
    headline = data.get("headline")
    description = data.get("description")
    caption = data.get("caption")
    image_query = data.get("image_query")
    style = data.get("style")
    if not isinstance(headline, str) or not headline.strip():
        return False, "headline is empty"
    if _word_count(headline) > 12:
        return False, "headline is longer than 12 words"
    if not isinstance(description, str) or not description.strip():
        return False, "description is empty"
    if _word_count(description) > 25:
        return False, "description is longer than 25 words"
    if not isinstance(caption, str) or not caption.strip():
        return False, "caption is empty"
    if len(caption) > 600:
        return False, "caption is longer than 600 characters"
    hashtags = re.findall(r"#[A-Za-z0-9_]{2,}", caption)
    if len(hashtags) < 8 or len(hashtags) > 12:
        return False, f"caption has {len(hashtags)} hashtags, expected 8-12"
    if not isinstance(image_query, str):
        return False, "image_query must be a string"
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", image_query)
    if len(words) < 2 or len(words) > 4:
        return False, "image_query must be 2-4 words"
    if len(image_query) > 50:
        return False, "image_query is too long"
    if isinstance(style, bool) or not isinstance(style, int):
        return False, "style must be an integer"
    if style < 1 or style > 20:
        return False, "style must be between 1 and 20"
    if fixed_style is not None and style != fixed_style:
        return False, "style does not match the locked style"
    if (
        fixed_style is None
        and bool(config.get("avoid_repeat_style", True))
        and last_style in range(1, 21)
        and style == last_style
    ):
        return False, "style repeats the previous post"
    return True, {
        "story_index": index,
        "category": category,
        "headline": re.sub(r"\s+", " ", headline).strip(),
        "description": re.sub(r"\s+", " ", description).strip(),
        "caption": caption.strip(),
        "image_query": re.sub(r"\s+", " ", image_query).strip(),
        "style": style,
    }


class LLMChain:
    """One chain per run, so bad keys are skipped across all tasks."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.chain = self._resolve_chain(config)
        self.bad_keys: set = set()

    @staticmethod
    def _resolve_chain(config: Dict[str, Any]) -> List[Dict[str, str]]:
        llm_cfg = config.get("llm") or {}
        order = llm_cfg.get("order") or list(DEFAULT_ORDER)
        disabled = set(llm_cfg.get("disabled") or [])
        chain: List[Dict[str, str]] = []
        seen = set()
        for provider_id in list(order) + list(DEFAULT_ORDER):
            if provider_id in seen or provider_id not in PROVIDER_META:
                continue
            seen.add(provider_id)
            if provider_id in disabled:
                continue
            meta = PROVIDER_META[provider_id]
            base = (os.environ.get(meta["base_env"]) or meta["base_default"]).strip()
            key = (os.environ.get(meta["key_env"]) or "").strip()
            model = (os.environ.get(meta["model_env"]) or "").strip()
            if not base or not key or not model:
                continue
            chain.append(
                {
                    "id": provider_id,
                    "label": meta["label"],
                    "base": base.rstrip("/"),
                    "key": key,
                    "model": model,
                }
            )
        return chain

    def providers_available(self) -> List[str]:
        return [p["id"] for p in self.chain]

    def _chat(
        self,
        provider: Dict[str, str],
        messages: List[Dict[str, str]],
        json_mode: bool,
        max_tokens: int,
        temperature: float,
    ) -> str:
        url = provider["base"] + "/chat/completions"
        payload: Dict[str, Any] = {
            "model": provider["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {provider['key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "NewsCardStudio/1.0",
        }
        last_reason = "request failed"
        attempt = 0
        retried_without_format = False
        while attempt < 2:
            try:
                response = requests.post(
                    url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                )
            except requests.Timeout:
                last_reason = "timeout"
                attempt += 1
                if attempt < 2:
                    time.sleep(RETRY_DELAY)
                continue
            except requests.RequestException:
                last_reason = "network error"
                attempt += 1
                if attempt < 2:
                    time.sleep(RETRY_DELAY)
                continue
            status = response.status_code
            if status in (401, 403):
                raise BadKey(f"HTTP {status}")
            if (
                status == 400
                and json_mode
                and not retried_without_format
                and "response_format" in payload
            ):
                retried_without_format = True
                payload.pop("response_format", None)
                continue
            if status == 429 or 500 <= status < 600:
                last_reason = f"HTTP {status}"
                attempt += 1
                if attempt < 2:
                    time.sleep(RETRY_DELAY)
                continue
            if status >= 400:
                raise ProviderFailure(f"HTTP {status}")
            try:
                body = response.json()
                choice = (body.get("choices") or [])[0]
                message = choice.get("message") or {}
                content = message.get("content")
                if content is None:
                    content = choice.get("text")
            except Exception:  # noqa: BLE001
                raise ProviderFailure("malformed response")
            if isinstance(content, list):
                chunks = []
                for part in content:
                    if isinstance(part, dict):
                        chunks.append(str(part.get("text") or ""))
                    elif isinstance(part, str):
                        chunks.append(part)
                content = "".join(chunks)
            if not isinstance(content, str) or not content.strip():
                raise ProviderFailure("empty response")
            return content
        raise ProviderFailure(last_reason)

    def pick_story(
        self,
        candidates: List[Any],
        config: Dict[str, Any],
        last_style: Optional[int] = None,
        fixed_topic: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Task 1. Always returns validated data; falls back to rule-based."""
        if not candidates:
            raise ValueError("pick_story requires at least one candidate")
        fixed_style: Optional[int]
        try:
            fixed_style = int(config.get("style", "auto")) if str(config.get("style", "auto")).isdigit() else None
        except (TypeError, ValueError):
            fixed_style = None
        log: List[str] = []
        messages = self._pick_messages(candidates, config, last_style, fixed_style, fixed_topic)
        for provider in self.chain:
            provider_id = provider["id"]
            if provider_id in self.bad_keys:
                log.append(f"{provider_id}: bad key")
                continue
            try:
                content = self._chat(
                    provider, messages, json_mode=True, max_tokens=1200, temperature=0.7
                )
            except BadKey:
                self.bad_keys.add(provider_id)
                log.append(f"{provider_id}: bad key")
                continue
            except ProviderFailure as exc:
                log.append(f"{provider_id}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                log.append(f"{provider_id}: {type(exc).__name__}")
                continue
            parsed = extract_json(content)
            if parsed is None:
                log.append(f"{provider_id}: invalid JSON")
                continue
            ok, result = _validate_pick(
                parsed, candidates, config, last_style, fixed_style, fixed_topic
            )
            if not ok:
                log.append(f"{provider_id}: invalid output ({result})")
                continue
            log.append(f"{provider_id}: ok")
            return {
                "data": result,
                "provider": provider_id,
                "provider_label": provider["label"],
                "log": ", ".join(log),
                "fallback": False,
            }
        fallback = rule_based_pick(candidates, config, last_style)
        log.append("rule-based: ok")
        return {
            "data": fallback,
            "provider": "rule-based",
            "provider_label": "Rule-based editor",
            "log": ", ".join(log),
            "fallback": True,
        }

    def design_html(
        self,
        messages: List[Dict[str, str]],
        validator: Callable[[str], Tuple[bool, str]],
        max_calls: int = 3,
    ) -> Dict[str, Any]:
        """Task 2. Retry invalid HTML once per provider within ``max_calls``.

        The caller renders the fallback template when ``html`` is None.
        """
        log: List[str] = []
        calls = 0
        for provider in self.chain:
            if calls >= max_calls:
                break
            provider_id = provider["id"]
            if provider_id in self.bad_keys:
                log.append(f"{provider_id}: bad key")
                continue
            attempts = 0
            correction = ""
            while attempts < 2 and calls < max_calls:
                attempts += 1
                calls += 1
                attempt_messages = list(messages)
                if correction:
                    attempt_messages.append({"role": "user", "content": correction})
                try:
                    content = self._chat(
                        provider,
                        attempt_messages,
                        json_mode=False,
                        max_tokens=4000,
                        temperature=0.6,
                    )
                except BadKey:
                    self.bad_keys.add(provider_id)
                    log.append(f"{provider_id}: bad key")
                    break
                except ProviderFailure as exc:
                    log.append(f"{provider_id}: {exc}")
                    break
                except Exception as exc:  # noqa: BLE001
                    log.append(f"{provider_id}: {type(exc).__name__}")
                    break
                html = sanitize_html(content)
                ok, reason = validator(html)
                if ok:
                    log.append(f"{provider_id}: ok")
                    return {
                        "html": html,
                        "provider": provider_id,
                        "provider_label": provider["label"],
                        "log": ", ".join(log),
                    }
                log.append(f"{provider_id}: rejected design ({reason})")
                correction = (
                    "The previous HTML failed validation: "
                    f"{reason}. Return a corrected, single self-contained HTML "
                    "document only. Keep the supplied headline verbatim and keep "
                    "the {{IMAGE}} placeholder."
                )
        log.append("fallback template")
        return {
            "html": None,
            "provider": None,
            "provider_label": "Fallback template",
            "log": ", ".join(log),
        }

    def _pick_messages(
        self,
        candidates: List[Any],
        config: Dict[str, Any],
        last_style: Optional[int],
        fixed_style: Optional[int],
        fixed_topic: Optional[str],
    ) -> List[Dict[str, str]]:
        enabled = [
            f"{key}={label}"
            for key, label in CATEGORY_LABELS.items()
            if (config.get("topics") or {}).get(key) or key == fixed_topic
        ]
        fixed_topic_line = (
            f"\nTopic is locked to {fixed_topic}. Pick a {fixed_topic} story."
            if fixed_topic
            else ""
        )
        style_line = (
            f"Return style={fixed_style} exactly (the user locked this style)."
            if fixed_style is not None
            else (
                f"Choose the most fitting style number 1-20. Do NOT use style "
                f"{last_style} (used for the previous card)."
                if last_style in range(1, 21)
                and bool(config.get("avoid_repeat_style", True))
                else "Choose the most fitting style number 1-20."
            )
        )
        lines = []
        for cand in candidates:
            prompt = cand.to_prompt()
            summary = prompt["summary"].replace("\n", " ").strip()
            lines.append(
                f"{prompt['index']} | {prompt['source']} | {prompt['age']} | "
                f"{prompt['category']} | {prompt['title']} | {summary}"
            )
        system = (
            "You are the editor of NewsCard Studio, an Instagram news-card account. "
            "Pick exactly one story and write compact, factual card copy. "
            "Use only facts present in the chosen candidate. Never invent numbers, "
            "quotes, people or sources. Never write clickbait. "
            "Reply with ONE JSON object and nothing else."
        )
        user = (
            f"ENABLED CATEGORIES: {', '.join(enabled)}.{fixed_topic_line}\n\n"
            "CANDIDATES (index | source | age | category | title | summary):\n"
            + "\n".join(lines)
            + "\n\nRULES\n"
            "- story_index: integer index of the chosen candidate.\n"
            "- category: copy the chosen candidate's category exactly.\n"
            "- headline: max 12 words, sentence case, factual, no emojis, no clickbait.\n"
            "- description: max 25 words, factual, drawn only from the candidate summary/title.\n"
            "- caption: max 600 characters, Instagram-ready, includes the source name and "
            "8-12 hashtags (count them); no invented facts.\n"
            "- image_query: 2-4 concrete visual words for a stock photo (a scene or object, "
            "never a person's name, never abstract). Example: server room, stock market screen, "
            "rocket launch.\n"
            f"- {style_line}\n\n"
            "Reply with JSON only, exactly these keys:\n"
            '{"story_index":0,"category":"tech_ai","headline":"","description":"",'
            '"caption":"","image_query":"","style":1}'
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def chain_summary(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Small helper for README/debugging and the dashboard docs."""
    order = (config.get("llm") or {}).get("order") or DEFAULT_ORDER
    disabled = set((config.get("llm") or {}).get("disabled") or [])
    result = []
    for provider_id in order:
        if provider_id not in PROVIDER_META:
            continue
        meta = PROVIDER_META[provider_id]
        base = (os.environ.get(meta["base_env"]) or meta["base_default"]).strip()
        result.append(
            {
                "id": provider_id,
                "label": meta["label"],
                "configured": bool(
                    base
                    and os.environ.get(meta["key_env"])
                    and os.environ.get(meta["model_env"])
                ),
                "disabled": provider_id in disabled,
            }
        )
    return result
