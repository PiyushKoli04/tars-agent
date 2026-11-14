"""Image provider chain: Unsplash, article og:image, Pixabay, Wikimedia, art.

Every provider is optional and isolated. The generated abstract background is
always available, so a card can render with zero image API keys. Photos are
downloaded once, resized with Pillow and embedded later as data URIs.
"""

from __future__ import annotations

import base64
import colorsys
import hashlib
import html as html_lib
import io
import os
import random
import re
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from core.storage import used_photo_keys

TIMEOUT = 10
USER_AGENT = "NewsCardStudio/1.0 (editorial card generator)"
MAX_SIDE = 1600
JPEG_QUALITY = 90

UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"
UNSPLASH_MIN_WIDTH = 1080
PIXABAY_SEARCH = "https://pixabay.com/api/"
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
ARTICLE_MIN_WIDTH = 800

PROVIDER_LABELS = {
    "unsplash": "Unsplash",
    "article": "Article photo",
    "pixabay": "Pixabay",
    "wikimedia": "Wikimedia Commons",
    "generated": "Generated background",
}


@dataclass
class ImageAsset:
    data: bytes
    source: str
    width: int
    height: int
    credit: str = ""
    caption_credit: str = ""
    photo_id: str = ""
    photographer: str = ""
    license_name: str = ""
    query: str = ""
    log: str = ""

    @property
    def provider_label(self) -> str:
        return PROVIDER_LABELS.get(self.source, self.source)

    @property
    def data_uri(self) -> str:
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def public(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "provider_label": self.provider_label,
            "width": self.width,
            "height": self.height,
            "credit": self.credit,
            "caption_credit": self.caption_credit,
            "photo_id": self.photo_id,
            "photographer": self.photographer,
            "license": self.license_name,
            "query": self.query,
            "log": self.log,
        }


class _MetaImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: List[Tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "meta":
            name = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content", "").strip()
            if content and name in (
                "og:image:secure_url",
                "og:image",
                "og:image:url",
                "twitter:image",
                "twitter:image:src",
            ):
                priority = 0 if name.startswith("og:image") else 1
                self.candidates.append((priority, content))
        elif tag.lower() == "link":
            rel = values.get("rel", "").lower()
            href = values.get("href", "").strip()
            if href and "image_src" in rel:
                self.candidates.append((2, href))


def _get(url: str, **kwargs: Any) -> requests.Response:
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("User-Agent", USER_AGENT)
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)


def _prepare_image(raw: bytes) -> Tuple[bytes, int, int]:
    with Image.open(io.BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, (247, 245, 240))
            if image.mode in ("RGBA", "LA", "P"):
                converted = image.convert("RGBA")
                background.paste(converted, mask=converted.split()[-1])
                image = background
            else:
                image = image.convert("RGB")
        else:
            image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return output.getvalue(), image.width, image.height


def _photo_key(provider: str, photo_id: str) -> str:
    return f"{provider}:{photo_id}"


def _is_used(used: set, provider: str, photo_id: str) -> bool:
    return bool(photo_id) and _photo_key(provider, photo_id) in used


def _int_header(response: requests.Response, name: str) -> Optional[int]:
    value = response.headers.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _unsplash(
    query: str, used: set
) -> Tuple[Optional[ImageAsset], str]:
    key = (os.environ.get("UNSPLASH_ACCESS_KEY") or "").strip()
    if not key:
        return None, "no key"
    headers = {
        "Authorization": f"Client-ID {key}",
        "Accept-Version": "v1",
        "User-Agent": USER_AGENT,
    }
    try:
        response = _get(
            UNSPLASH_SEARCH,
            headers=headers,
            params={
                "query": query,
                "orientation": "portrait",
                "content_filter": "high",
                "per_page": 10,
            },
        )
    except requests.RequestException as exc:
        return None, type(exc).__name__
    if response.status_code in (401, 403):
        return None, f"HTTP {response.status_code}"
    if response.status_code == 429:
        return None, "HTTP 429"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    remaining = _int_header(response, "X-Ratelimit-Remaining")
    if remaining is not None and remaining <= 2:
        return None, f"rate limit low ({remaining})"
    try:
        payload = response.json()
        results = payload.get("results") or []
    except ValueError:
        return None, "bad JSON"
    for photo in results:
        if not isinstance(photo, dict):
            continue
        photo_id = str(photo.get("id") or "")
        width = int(photo.get("width") or 0)
        if not photo_id or width < UNSPLASH_MIN_WIDTH:
            continue
        if _is_used(used, "unsplash", photo_id):
            continue
        urls = photo.get("urls") or {}
        download = urls.get("regular") or urls.get("full") or urls.get("raw")
        if not download:
            continue
        try:
            image_response = _get(download, headers={"User-Agent": USER_AGENT})
        except requests.RequestException:
            continue
        if image_response.status_code != 200:
            continue
        try:
            data, actual_width, height = _prepare_image(image_response.content)
        except Exception:
            continue
        if actual_width < UNSPLASH_MIN_WIDTH:
            continue
        links = photo.get("links") or {}
        download_location = links.get("download_location")
        if download_location:
            try:
                registration = _get(
                    download_location,
                    headers=headers,
                    params={
                        "utm_source": "newscard_studio",
                        "utm_medium": "referral",
                    },
                )
            except requests.RequestException:
                return None, "download registration failed"
            if registration.status_code >= 400:
                return None, f"download registration HTTP {registration.status_code}"
        user = photo.get("user") or {}
        photographer = (
            str(user.get("name") or "").strip()
            or str(user.get("username") or "").strip()
            or "Unsplash contributor"
        )
        return (
            ImageAsset(
                data=data,
                source="unsplash",
                width=actual_width,
                height=height,
                credit=f"Photo by {photographer} / Unsplash",
                caption_credit=f"Photo: {photographer} on Unsplash",
                photo_id=photo_id,
                photographer=photographer,
                license_name="Unsplash License",
                query=query,
            ),
            "ok",
        )
    return None, "no suitable photo"


def _pixabay(query: str, used: set) -> Tuple[Optional[ImageAsset], str]:
    key = (os.environ.get("PIXABAY_API_KEY") or "").strip()
    if not key:
        return None, "no key"
    try:
        response = _get(
            PIXABAY_SEARCH,
            params={
                "key": key,
                "q": query,
                "image_type": "photo",
                "orientation": "vertical",
                "safesearch": "true",
                "min_width": UNSPLASH_MIN_WIDTH,
                "per_page": 10,
            },
        )
    except requests.RequestException as exc:
        return None, type(exc).__name__
    if response.status_code in (403, 429):
        return None, f"HTTP {response.status_code}"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    try:
        hits = (response.json() or {}).get("hits") or []
    except ValueError:
        return None, "bad JSON"
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        photo_id = str(hit.get("id") or "")
        width = int(hit.get("imageWidth") or 0)
        if not photo_id or width < UNSPLASH_MIN_WIDTH:
            continue
        if _is_used(used, "pixabay", photo_id):
            continue
        download = hit.get("largeImageURL") or hit.get("fullHDURL") or hit.get("webformatURL")
        if not download:
            continue
        try:
            image_response = _get(download)
        except requests.RequestException:
            continue
        if image_response.status_code != 200:
            continue
        try:
            data, actual_width, height = _prepare_image(image_response.content)
        except Exception:
            continue
        if actual_width < UNSPLASH_MIN_WIDTH:
            continue
        photographer = str(hit.get("user") or "Pixabay contributor").strip()
        return (
            ImageAsset(
                data=data,
                source="pixabay",
                width=actual_width,
                height=height,
                credit=f"Photo by {photographer} / Pixabay",
                caption_credit=f"Photo: {photographer} on Pixabay",
                photo_id=photo_id,
                photographer=photographer,
                license_name="Pixabay Content License",
                query=query,
            ),
            "ok",
        )
    return None, "no suitable photo"


def _meta_value(info: Dict[str, Any], key: str) -> str:
    value = (info.get("extmetadata") or {}).get(key)
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    return ""


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?s)<[^>]+>", " ", raw or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _wikimedia(query: str, used: set) -> Tuple[Optional[ImageAsset], str]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": 15,
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": 1600,
        "format": "json",
        "origin": "*",
    }
    try:
        response = _get(WIKIMEDIA_API, params=params)
    except requests.RequestException as exc:
        return None, type(exc).__name__
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    try:
        pages = ((response.json() or {}).get("query") or {}).get("pages") or {}
    except ValueError:
        return None, "bad JSON"
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        width = int(info.get("width") or 0)
        mime = str(info.get("mime") or "")
        if width < UNSPLASH_MIN_WIDTH or mime not in ("image/jpeg", "image/png", "image/webp"):
            continue
        photo_id = str(page.get("pageid") or page.get("title") or "")
        if _is_used(used, "wikimedia", photo_id):
            continue
        license_name = _meta_value(info, "LicenseShortName") or _meta_value(info, "License")
        usage = _meta_value(info, "UsageTerms")
        combined = f"{license_name} {usage}".lower()
        public_domain = bool(
            re.search(r"\b(cc0|public domain|public-domain|pd-only|pd[- ]?us|pd-self)\b", combined)
        )
        if not public_domain:
            continue
        download = info.get("thumburl") or info.get("url")
        if not download:
            continue
        try:
            image_response = _get(download)
        except requests.RequestException:
            continue
        if image_response.status_code != 200:
            continue
        try:
            data, actual_width, height = _prepare_image(image_response.content)
        except Exception:
            continue
        if actual_width < UNSPLASH_MIN_WIDTH:
            continue
        artist = _strip_html(_meta_value(info, "Artist") or _meta_value(info, "Credit"))
        artist = artist[:80] or "Wikimedia Commons"
        license_label = license_name or "Public domain"
        return (
            ImageAsset(
                data=data,
                source="wikimedia",
                width=actual_width,
                height=height,
                credit=f"Photo by {artist} / Wikimedia Commons",
                caption_credit=f"Photo: {artist} / Wikimedia Commons ({license_label})",
                photo_id=photo_id,
                photographer=artist,
                license_name=license_label,
                query=query,
            ),
            "ok",
        )
    return None, "no PD/CC0 result"


def _article_photo(
    article_url: str, article_source: str, used: set
) -> Tuple[Optional[ImageAsset], str]:
    if not article_url:
        return None, "no article URL"
    try:
        response = _get(article_url, headers={"Accept": "text/html,application/xhtml+xml"})
    except requests.RequestException as exc:
        return None, type(exc).__name__
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    parser = _MetaImageParser()
    try:
        parser.feed(response.text[:400000])
    except Exception:
        return None, "could not parse page"
    candidates = []
    for priority, candidate in sorted(parser.candidates, key=lambda item: item[0]):
        absolute = urllib.parse.urljoin(article_url, candidate)
        if absolute.startswith(("http://", "https://")) and absolute not in candidates:
            candidates.append(absolute)
    for candidate in candidates:
        photo_id = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:20]
        if _is_used(used, "article", photo_id):
            continue
        try:
            image_response = _get(candidate, headers={"Referer": article_url})
        except requests.RequestException:
            continue
        if image_response.status_code != 200:
            continue
        try:
            data, actual_width, height = _prepare_image(image_response.content)
        except Exception:
            continue
        if actual_width < ARTICLE_MIN_WIDTH:
            continue
        source_name = article_source or "article"
        return (
            ImageAsset(
                data=data,
                source="article",
                width=actual_width,
                height=height,
                credit=f"Photo via {source_name}",
                caption_credit=f"Photo via {source_name}",
                photo_id=photo_id,
                photographer=source_name,
                license_name="Article photo (copyright may apply)",
                query="article og:image",
            ),
            "ok",
        )
    return None, "no usable og:image"


def _hex_rgb(value: str) -> Tuple[int, int, int]:
    text = re.sub(r"[^0-9A-Fa-f]", "", value or "")
    if len(text) != 6:
        text = "B7A0FF"
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def _mix(rgb: Tuple[int, int, int], other: Tuple[int, int, int], amount: float) -> Tuple[int, int, int]:
    return tuple(
        max(0, min(255, round(channel * (1 - amount) + other[index] * amount)))
        for index, channel in enumerate(rgb)
    )


def generated_background(
    brand: Dict[str, Any], seed: str = ""
) -> Tuple[bytes, int, int]:
    width, height = 1080, 1350
    accent = _hex_rgb(str(brand.get("accent_color") or "#B7A0FF"))
    white = (255, 255, 255)
    warm = (247, 245, 240)
    rng = random.Random(hashlib.sha256((seed or "newscard").encode("utf-8")).hexdigest())
    base = _mix(accent, warm, 0.90)
    image = Image.new("RGB", (width, height), base)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in accent))
    companions = []
    for shift, weight in ((0.06, 0.55), (-0.08, 0.45), (0.15, 0.35)):
        tint = colorsys.hsv_to_rgb((hue + shift) % 1.0, min(0.55, saturation * 0.8), 0.96)
        companions.append(tuple(round(channel * 255) for channel in tint))
    blob_one = _mix(accent, white, 0.45)
    blob_two = _mix(companions[0], white, 0.35)
    blob_three = _mix(companions[1], white, 0.25)
    draw.ellipse(
        (width * 0.42, -height * 0.22, width * 1.42, height * 0.52),
        fill=(*blob_one, 210),
    )
    draw.ellipse(
        (-width * 0.36, height * 0.46, width * 0.58, height * 1.22),
        fill=(*blob_two, 190),
    )
    draw.ellipse(
        (width * 0.55, height * 0.70, width * 1.30, height * 1.18),
        fill=(*blob_three, 160),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=90))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    line_color = (*_mix(accent, (17, 17, 17), 0.45), 54)
    for index in range(5):
        inset = 70 + index * 54
        draw.arc(
            (inset, height * 0.18 + index * 20, width - inset, height * 0.92 - index * 12),
            start=200,
            end=340,
            fill=line_color,
            width=2,
        )
    dot_color = (*_mix(accent, (17, 17, 17), 0.55), 32)
    start_x = 92 + rng.randrange(0, 40)
    start_y = 118 + rng.randrange(0, 40)
    for row in range(9):
        for col in range(7):
            draw.ellipse(
                (
                    start_x + col * 46,
                    height - start_y - row * 46,
                    start_x + col * 46 + 4,
                    height - start_y - row * 46 + 4,
                ),
                fill=dot_color,
            )
    noise = Image.effect_noise((width, height), 18).convert("L").convert("RGB")
    image = Image.blend(image.convert("RGB"), noise, 0.035)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return output.getvalue(), width, height


def _generated(query: str, config: Dict[str, Any], seed: str) -> ImageAsset:
    brand = config.get("brand") or {}
    data, width, height = generated_background(brand, seed)
    return ImageAsset(
        data=data,
        source="generated",
        width=width,
        height=height,
        credit="",
        caption_credit="",
        photo_id="",
        photographer="",
        license_name="Generated",
        query=query,
    )


def fetch_image(
    query: str,
    config: Dict[str, Any],
    history: Dict[str, Any],
    article_url: str = "",
    article_source: str = "",
    seed: str = "",
) -> ImageAsset:
    """Run the configured image chain. Never raises; generated is last resort."""
    image_cfg = config.get("image") or {}
    used = used_photo_keys(history)
    order = [str(name).lower() for name in (image_cfg.get("order") or [])]
    known = ["unsplash", "article", "pixabay", "wikimedia", "generated"]
    order = [name for name in order if name in known]
    for name in known:
        if name not in order:
            order.append(name)
    if "generated" in order:
        order = [name for name in order if name != "generated"] + ["generated"]
    disabled = set(str(name).lower() for name in (image_cfg.get("disabled") or []))
    logs: List[str] = []
    for name in order:
        if name == "generated":
            continue
        if name in disabled:
            logs.append(f"{name}: disabled")
            continue
        if name == "article" and not bool(image_cfg.get("prefer_article_photo")):
            logs.append("article: disabled")
            continue
        try:
            if name == "unsplash":
                asset, reason = _unsplash(query, used)
            elif name == "article":
                asset, reason = _article_photo(article_url, article_source, used)
            elif name == "pixabay":
                asset, reason = _pixabay(query, used)
            elif name == "wikimedia":
                asset, reason = _wikimedia(query, used)
            else:
                asset, reason = None, "unknown provider"
        except Exception as exc:
            asset, reason = None, type(exc).__name__
        if asset is not None:
            logs.append(f"{name}: ok")
            asset.log = ", ".join(logs)
            return asset
        logs.append(f"{name}: {reason}")
    try:
        asset = _generated(query, config, seed)
        logs.append("generated: ok")
        asset.log = ", ".join(logs)
        return asset
    except Exception as exc:
        logs.append(f"generated: {type(exc).__name__}")
        raise RuntimeError("image generation failed") from exc


def card_credit(asset: ImageAsset, show_credit: bool) -> str:
    if not asset.credit:
        return ""
    if show_credit or asset.source == "unsplash":
        return f"Context image · {asset.credit}"
    return ""
