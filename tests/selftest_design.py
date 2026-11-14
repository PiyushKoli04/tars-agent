"""Offline self-test for design validation, styles and fallback rendering.

Run from the repo root:

    python -m tests.selftest_design

No network access is used.
"""

from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import design  # noqa: E402

PAYLOAD = {
    "brand": {
        "name": "NewsCard Studio",
        "handle": "@newscardstudio",
        "accent_color": "#B7A0FF",
        "footer_text": "Daily signals, beautifully told.",
    },
    "style": 7,
    "headline": "Satellite network opens a faster era for global internet",
    "description": (
        "A new satellite constellation promises faster internet access worldwide "
        "with first commercial service starting this year."
    ),
    "category": "tech_ai",
    "category_label": "Tech & AI",
    "credit_text": "Context image · Photo by Jane / Unsplash",
    "has_image": True,
    "has_logo": False,
    "image_source": "Unsplash",
}

CREDIT = PAYLOAD["credit_text"]


def fallback_html() -> str:
    return design.render_fallback(
        PAYLOAD,
        "data:image/jpeg;base64,ZmFrZQ==",
        "",
    )


def test_styles() -> None:
    styles = design.load_styles()
    assert len(styles) == 20, len(styles)
    assert list(styles) == list(range(1, 21)), list(styles)
    assert len(design.STYLE_NAMES) == 20, len(design.STYLE_NAMES)
    for number in styles:
        assert design.style_name(number) == styles[number]["name"]
        assert design.style_section(number)
    assert design.style_section(21) == design.style_section(1)
    print("PASS 20 styles load with names and prompt sections")


def test_fallback_is_valid() -> None:
    html = fallback_html()
    ok, reason = design.validate_design(
        html,
        headline=PAYLOAD["headline"],
        has_image=True,
        credit_required=CREDIT,
        require_placeholder=False,
    )
    assert ok, reason
    assert PAYLOAD["headline"] in html
    assert PAYLOAD["description"] in html
    assert "data:image/jpeg;base64,ZmFrZQ==" in html
    assert CREDIT in html
    print("PASS fallback HTML passes the full design validator")


def test_headline_text_escaped() -> None:
    payload = dict(PAYLOAD)
    payload["headline"] = 'Markets <script>alert("x")</script> rally'
    html = design.render_fallback(payload, "data:image/jpeg;base64,ZmFrZQ==", "")
    assert "<script>" not in html.lower()
    assert html_lib.escape(payload["headline"]) in html
    print("PASS fallback escapes injected headline text")


def reject(html: str, expected: str, require_placeholder: bool = False, credit: str = CREDIT) -> None:
    ok, reason = design.validate_design(
        html,
        headline=PAYLOAD["headline"],
        has_image=True,
        credit_required=credit,
        require_placeholder=require_placeholder,
    )
    assert not ok, "expected rejection"
    assert expected in reason.lower(), (expected, reason)


def test_validator_rejects_unsafe_html() -> None:
    clean = fallback_html()
    reject(clean.replace("</head>", "<script>alert(1)</script></head>"), "script")
    reject(clean.replace("<body>", '<body><iframe src="https://evil.test"></iframe>'), "embedded frame")
    reject(
        clean.replace('<h1 class="headline">', '<h1 class="headline" onclick="alert(1)">'),
        "event handler",
    )
    reject(
        clean.replace("</body>", '<img src="https://evil.test/x.jpg" alt=""></body>'),
        "external <img>",
    )
    reject(
        clean.replace("</head>", '<link rel="stylesheet" href="https://evil.test/x.css"></head>'),
        "external stylesheet",
    )
    print("PASS validator rejects scripts, frames, handlers and remote assets")


def test_validator_rejects_content_problems() -> None:
    clean = fallback_html()
    reject(
        clean.replace(html_lib.escape(PAYLOAD["headline"]), "A different headline"),
        "headline",
    )
    reject(clean.replace("font-size: 84px", "font-size: 40px"), "below 56px")
    reject(clean, "credit", credit="Context image · Photo by Someone / Unsplash")
    reject(clean, "placeholder", require_placeholder=True)
    print("PASS validator rejects wrong headline, small type, missing credit/placeholder")


def test_canvas_rules() -> None:
    clean = fallback_html()
    reject(clean.replace("width: 1080px", "width: 720px"), "canvas")
    reject(clean.replace("height: 1350px", "height: 900px"), "canvas")
    reject(clean.replace("padding: 72px", "padding: 24px"), "padding")
    print("PASS validator enforces the 1080x1350 canvas and safe padding")


def main() -> None:
    tests = [
        test_styles,
        test_fallback_is_valid,
        test_headline_text_escaped,
        test_validator_rejects_unsafe_html,
        test_validator_rejects_content_problems,
        test_canvas_rules,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} design self-tests passed.")


if __name__ == "__main__":
    main()