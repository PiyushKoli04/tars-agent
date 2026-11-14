"""Style library, design prompt construction, static validation and fallback."""

from __future__ import annotations

import base64
import html as html_lib
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STYLES_PATH = TEMPLATE_DIR / "styles.md"
FALLBACK_PATH = TEMPLATE_DIR / "fallback.html"

STYLE_NAMES: List[str] = [
    "Quiet Broadsheet",
    "Midnight Terminal",
    "Soft Editorial",
    "Bold Poster",
    "Newsprint Classic",
    "Swiss Grid",
    "Monochrome Minimal",
    "Magazine Cover",
    "Data Story",
    "Brutalist Type",
    "Warm Documentary",
    "Paper Cut",
    "Modern Luxe",
    "Zine Collage",
    "Blueprint",
    "Tabloid Sport",
    "Financial Daily",
    "Retro Print",
    "Cosmic Dark",
    "Gallery White",
]

_FALLBACK_STYLE_PROMPT = (
    "A calm editorial layout with the brand accent, a large photo, a serif "
    "headline, small category label, brand name and credit line. Use generous "
    "white space and high contrast."
)

_HEADING_RE = re.compile(r"(?m)^##\s+Style\s+(\d{1,2})\s*[—–-]\s*(.+?)\s*$")
_CSS_COMMENT_RE = re.compile(r"(?s)/\*.*?\*/")
_RULE_RE = re.compile(r"(?s)([^{}]+)\{([^{}]*)\}")
_FONT_RE = re.compile(r"font-size\s*:\s*([^;}\"']+)", re.I)


def style_name(number: int) -> str:
    try:
        index = int(number) - 1
    except (TypeError, ValueError):
        return "Auto"
    if 0 <= index < len(STYLE_NAMES):
        return STYLE_NAMES[index]
    return "Auto"


def load_styles(path: Optional[Path] = None) -> Dict[int, Dict[str, str]]:
    source = path or STYLES_PATH
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        text = ""
    matches = list(_HEADING_RE.finditer(text))
    styles: Dict[int, Dict[str, str]] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        if not 1 <= number <= 20 or number in styles:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        prompt = text[match.end() : end].strip()
        name = match.group(2).strip()
        if prompt:
            styles[number] = {"name": name, "prompt": prompt}
    for number in range(1, 21):
        if number not in styles:
            styles[number] = {
                "name": style_name(number),
                "prompt": _FALLBACK_STYLE_PROMPT,
            }
    return styles


def style_section(number: int) -> str:
    styles = load_styles()
    chosen = styles.get(int(number)) or styles.get(1)
    if not chosen:
        return _FALLBACK_STYLE_PROMPT
    return f"STYLE NAME: {chosen['name']}\n\n{chosen['prompt']}"


def load_logo_data_uri(config: Dict[str, Any], root: Optional[Path] = None) -> str:
    logo_path = str((config.get("brand") or {}).get("logo_path") or "").strip()
    if not logo_path:
        return ""
    base = (root or Path(__file__).resolve().parent.parent).resolve()
    candidate = (base / logo_path).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return ""
    if not candidate.is_file():
        return ""
    suffix = candidate.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")
    try:
        encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:{mime};base64,{encoded}"


def build_design_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    brand = payload.get("brand") or {}
    style_number = int(payload.get("style") or 1)
    headline = str(payload.get("headline") or "").strip()
    description = str(payload.get("description") or "").strip()
    category = str(payload.get("category_label") or payload.get("category") or "").strip()
    credit_text = str(payload.get("credit_text") or "").strip()
    has_image = bool(payload.get("has_image", True))
    has_logo = bool(payload.get("has_logo"))
    image_source = str(payload.get("image_source") or "photo")
    accent = str(brand.get("accent_color") or "#B7A0FF")
    name = str(brand.get("name") or "NewsCard Studio")
    handle = str(brand.get("handle") or "@newscardstudio")
    footer = str(brand.get("footer_text") or "")
    style_text = style_section(style_number)
    credit_rule = (
        f'- Show this credit line exactly, in small legible type inside the safe margin: '
        f'"{credit_text}". It marks the photo as context, not coverage of the event.'
        if credit_text
        else "- Do not add any photo credit line because this image needs none."
    )
    system = (
        "You are a senior art director. You design one Instagram news card as a "
        "single self-contained HTML document. Return HTML only, with no markdown "
        "fences and no commentary. Never use scripts, iframes, forms, event "
        "handlers or external images. The card content must stay factual."
    )
    user = (
        f"{style_text}\n\n"
        "CONTENT (do not add facts that are not present here):\n"
        f'{{"headline": {_json_string(headline)}, "description": {_json_string(description)}, '
        f'"category": {_json_string(category)}}}\n\n'
        "BRAND:\n"
        f'{{"name": {_json_string(name)}, "handle": {_json_string(handle)}, '
        f'"footer": {_json_string(footer)}, "accent": {_json_string(accent)}}}\n\n'
        f"PHOTO: a {image_source} context image is available. Put the exact placeholder "
        "{{IMAGE}} once as the src of your main <img> tag or in a CSS background. "
        "Never hotlink any other image. "
        + (
            "A logo is available as the optional placeholder {{LOGO}}; use it once "
            "only if the layout wants a small mark."
            if has_logo
            else "There is no logo file; use the brand name in type instead."
        )
        + "\n\n"
        "TECHNICAL REQUIREMENTS:\n"
        "- One complete HTML document with <!DOCTYPE html>, <html>, <head>, <body>.\n"
        "- Inline CSS only. Google Fonts <link> tags are the only external resource.\n"
        "- The root canvas must be exactly 1080px wide and 1350px tall, with "
        "box-sizing: border-box, overflow: hidden, and fixed padding of at least 64px "
        "on all four sides.\n"
        "- Headline font size must be at least 56px; make it the dominant element.\n"
        "- Set margin: 0 on body. No scrollbars, no fixed browser chrome.\n"
        "- No <script>, no event handler attributes, no iframes/objects/embeds, "
        "no external images, no CSS url() to remote files, no gradients.\n"
        f"- Render the headline text verbatim, exactly once, visible on the card: "
        f'"{headline}". Do not paraphrase or split words with added characters.\n'
        "- Keep description short and readable. Use only the supplied content.\n"
        "- Do not write the words 'Style', 'Prompt' or 'Layout' on the card.\n"
        f"{credit_rule}\n"
        "- All text must sit inside the 64px safe margin. High contrast, legible "
        "at phone size. No fabricated numbers, quotes, dates or sources.\n\n"
        + (
            "Reply with the HTML document only."
            if has_image
            else "Reply with the HTML document only."
        )
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _json_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "span",
        "td",
        "th",
        "tr",
        "ul",
        "ol",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.tags: List[str] = []
        self.in_style = 0
        self.in_script = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        lower = tag.lower()
        self.tags.append(lower)
        if lower == "style":
            self.in_style += 1
        elif lower == "script":
            self.in_script += 1
        if lower in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "style" and self.in_style:
            self.in_style -= 1
        elif lower == "script" and self.in_script:
            self.in_script -= 1
        if lower in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.in_style and not self.in_script:
            self.parts.append(data)

    def text(self) -> str:
        return normalize_text("".join(self.parts))


class _ParseCheck(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen_tags: List[str] = []
        self.failed = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.seen_tags.append(tag.lower())

    def error(self, message: str) -> None:
        self.failed = True


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def _parse_html(html: str) -> Tuple[bool, Optional[_TextExtractor], str]:
    extractor = _TextExtractor()
    checker = _ParseCheck()
    try:
        extractor.feed(html)
        extractor.close()
        checker.feed(html)
        checker.close()
    except Exception:
        return False, None, "HTML could not be parsed"
    if not extractor.tags:
        return False, None, "HTML has no elements"
    if "html" not in extractor.tags:
        return False, None, "missing <html> element"
    if "body" not in extractor.tags:
        return False, None, "missing <body> element"
    return True, extractor, ""


def _style_text(html: str) -> str:
    chunks = re.findall(r"(?is)<style[^>]*>(.*?)</style\s*>", html)
    return _CSS_COMMENT_RE.sub("", "\n".join(chunks))


def _rules(html: str) -> List[Tuple[str, Dict[str, str]]]:
    rules: List[Tuple[str, Dict[str, str]]] = []
    for selector, body in _RULE_RE.findall(_style_text(html)):
        declarations: Dict[str, str] = {}
        for part in body.split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            key = key.strip().lower()
            if key:
                declarations[key] = re.sub(r"\s*!important\s*$", "", value.strip(), flags=re.I)
        rules.append((selector.strip(), declarations))
    return rules


def _px(value: str) -> Optional[float]:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*px", value or "", re.I)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _padding_min(declarations: Dict[str, str]) -> Optional[float]:
    if "padding" in declarations:
        values = re.findall(r"(-?\d+(?:\.\d+)?)\s*px", declarations["padding"], re.I)
        if not values:
            return None
        try:
            return min(float(item) for item in values)
        except ValueError:
            return None
    sides = []
    for side in ("top", "right", "bottom", "left"):
        key = f"padding-{side}"
        if key not in declarations:
            return None
        parsed = _px(declarations[key])
        if parsed is None:
            return None
        sides.append(parsed)
    return min(sides) if sides else None


def _canvas_check(html: str) -> Tuple[bool, str]:
    found_dimensions = False
    for selector, declarations in _rules(html):
        width = _px(declarations.get("width", ""))
        height = _px(declarations.get("height", ""))
        if width != 1080 or height != 1350:
            continue
        found_dimensions = True
        if "hidden" not in declarations.get("overflow", "").lower():
            continue
        if "border-box" not in declarations.get("box-sizing", "").lower():
            continue
        padding = _padding_min(declarations)
        if padding is None or padding < 64:
            continue
        if selector:
            return True, ""
    if found_dimensions:
        return False, "canvas needs box-sizing border-box, overflow hidden and 64px+ padding"
    return False, "no 1080x1350 canvas rule found"


def _headline_font_size(html: str, headline: str) -> Optional[float]:
    sizes: List[float] = []
    for selector, declarations in _rules(html):
        lowered = selector.lower()
        if any(
            token in lowered
            for token in ("headline", "h1", "card-title", "story-title", "title-main", "display")
        ):
            value = declarations.get("font-size")
            if value:
                sizes.append(_px(value) or 0)
    for match in re.finditer(r"<([a-zA-Z][\w:-]*)([^>]*)>", html):
        tag = match.group(1).lower()
        attrs = match.group(2)
        class_id = " ".join(
            re.findall(r"""(?:class|id)\s*=\s*["']([^"']*)["']""", attrs, re.I)
        ).lower()
        if tag not in ("h1", "h2") and not any(
            token in class_id for token in ("headline", "title", "display")
        ):
            continue
        style_match = re.search(r"""style\s*=\s*["']([^"']*)["']""", attrs, re.I)
        if not style_match:
            continue
        for value in _FONT_RE.findall(style_match.group(1)):
            parsed = _px(value)
            if parsed:
                sizes.append(parsed)
    usable = [size for size in sizes if size > 0]
    return max(usable) if usable else None


def _external_resource_check(html: str) -> Optional[str]:
    for tag in re.findall(r"(?is)<img\b[^>]*>", html):
        src = re.search(r"""\bsrc\s*=\s*["']([^"']*)["']""", tag, re.I)
        if not src:
            continue
        value = src.group(1).strip()
        if value.startswith(("http://", "https://", "//")):
            return "external <img> src"
    for match in re.finditer(r"""(?is)url\(\s*['"]?([^'")]+)""", _style_text(html)):
        value = match.group(1).strip()
        if value.startswith(("http://", "https://", "//")):
            return "external CSS url()"
    for tag in re.findall(r"(?is)<link\b[^>]*>", html):
        href = re.search(r"""\bhref\s*=\s*["']([^"']*)["']""", tag, re.I)
        if not href:
            continue
        value = href.group(1).strip()
        if value.startswith(("http://", "https://", "//")):
            if not value.startswith(
                (
                    "https://fonts.googleapis.com",
                    "https://fonts.gstatic.com",
                    "http://fonts.googleapis.com",
                    "http://fonts.gstatic.com",
                )
            ):
                return "external stylesheet"
    return None


def validate_design(
    html: str,
    headline: str,
    has_image: bool = True,
    credit_required: str = "",
    require_placeholder: bool = True,
) -> Tuple[bool, str]:
    if not html or not html.strip():
        return False, "empty HTML"
    if len(html) > 500_000:
        return False, "HTML is too large"
    lowered = html.lower()
    if "<script" in lowered:
        return False, "script tag present"
    if re.search(r"(?is)<(iframe|object|embed|frame|frameset|applet)\b", html):
        return False, "embedded frame present"
    if "javascript:" in lowered:
        return False, "javascript URL present"
    if re.search(r"""(?is)\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", html):
        return False, "event handler present"
    parsed, extractor, reason = _parse_html(html)
    if not parsed or extractor is None:
        return False, reason or "could not parse HTML"
    text = extractor.text()
    normalized_headline = normalize_text(headline)
    if not normalized_headline:
        return False, "empty headline"
    if normalized_headline not in text:
        return False, "headline is missing or altered"
    if has_image and require_placeholder and "{{IMAGE}}" not in html:
        return False, "{{IMAGE}} placeholder missing"
    if credit_required and normalize_text(credit_required) not in text:
        return False, "photo credit line missing"
    external = _external_resource_check(html)
    if external:
        return False, external
    canvas_ok, canvas_reason = _canvas_check(html)
    if not canvas_ok:
        return False, canvas_reason
    font_size = _headline_font_size(html, headline)
    if font_size is None:
        return False, "headline font size could not be verified"
    if font_size < 56:
        return False, f"headline font size is {font_size:g}px, below 56px"
    return True, ""


def _image_block(data_uri: str, accent: str) -> str:
    if not data_uri:
        return (
            f'<div style="width:100%;height:100%;background:{accent};" '
            'aria-hidden="true"></div>'
        )
    return f'<img src="{data_uri}" alt="">'


def _logo_block(data_uri: str) -> str:
    if not data_uri:
        return ""
    return f'<img class="logo" src="{data_uri}" alt="">'


def render_fallback(
    payload: Dict[str, Any],
    image_data_uri: str = "",
    logo_data_uri: str = "",
    style_number: int = 1,
) -> str:
    try:
        template = FALLBACK_PATH.read_text(encoding="utf-8")
    except OSError:
        template = (
            "<!DOCTYPE html><html><head><style>"
            ".card{width:1080px;height:1350px;box-sizing:border-box;overflow:hidden;"
            "padding:72px}.headline{font-size:84px}</style></head><body>"
            '<div class="card"><h1 class="headline">{{HEADLINE}}</h1>'
            "<img src=\"{{IMAGE}}\" alt=\"\"></div></body></html>"
        )
    brand = payload.get("brand") or {}
    accent = str(brand.get("accent_color") or "#B7A0FF")
    credit = str(payload.get("credit_text") or "").strip()
    replacements = {
        "{{ACCENT}}": html_lib.escape(accent),
        "{{IMAGE_BLOCK}}": _image_block(image_data_uri, accent),
        "{{LOGO_BLOCK}}": _logo_block(logo_data_uri),
        "{{CATEGORY}}": html_lib.escape(
            str(payload.get("category_label") or payload.get("category") or "News")
        ),
        "{{HEADLINE}}": html_lib.escape(str(payload.get("headline") or "")),
        "{{DESCRIPTION}}": html_lib.escape(str(payload.get("description") or "")),
        "{{BRAND_NAME}}": html_lib.escape(str(brand.get("name") or "NewsCard Studio")),
        "{{HANDLE}}": html_lib.escape(str(brand.get("handle") or "")),
        "{{FOOTER_TEXT}}": html_lib.escape(str(brand.get("footer_text") or "")),
        "{{CREDIT_BLOCK}}": html_lib.escape(credit),
        "{{IMAGE}}": html_lib.escape(image_data_uri),
    }
    result = template
    for token, value in replacements.items():
        result = result.replace(token, value)
    return result


_TRANSPARENT_PIXEL = (
    "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
)


def inject_media(html: str, image_data_uri: str = "", logo_data_uri: str = "") -> str:
    result = html.replace("{{IMAGE}}", image_data_uri or _TRANSPARENT_PIXEL)
    result = result.replace("{{LOGO}}", logo_data_uri or _TRANSPARENT_PIXEL)
    return result
