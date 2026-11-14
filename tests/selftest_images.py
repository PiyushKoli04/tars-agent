"""Offline self-test for image preparation, generated art and credits.

Run from the repo root:

    python -m tests.selftest_images

No network access is used.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import images  # noqa: E402


def jpeg_bytes(size: tuple = (80, 120), color: tuple = (200, 100, 50)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_image() -> None:
    prepared, width, height = images._prepare_image(jpeg_bytes((80, 120)))
    assert (width, height) == (80, 120), (width, height)
    with Image.open(io.BytesIO(prepared)) as opened:
        assert opened.format == "JPEG"
        assert opened.size == (80, 120)
    print("PASS prepare keeps small images and converts to RGB JPEG")


def test_prepare_resizes_large_image() -> None:
    prepared, width, height = images._prepare_image(jpeg_bytes((2400, 1200)))
    assert width == 1600 and height == 800, (width, height)
    with Image.open(io.BytesIO(prepared)) as opened:
        assert opened.size == (1600, 800)
    print("PASS prepare downscales to the 1600px maximum")


def test_prepare_handles_transparency() -> None:
    source = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    prepared, width, height = images._prepare_image(buffer.getvalue())
    with Image.open(io.BytesIO(prepared)) as opened:
        assert opened.mode == "RGB"
        pixel = opened.getpixel((25, 25))
        assert all(abs(actual - expected) < 12 for actual, expected in zip(pixel, (247, 245, 240))), pixel
    assert (width, height) == (50, 50)
    print("PASS transparent pixels flatten to the warm background")


def test_generated_background() -> None:
    data, width, height = images.generated_background({"accent_color": "#B7A0FF"}, "seed-a")
    assert width == 1080 and height == 1350, (width, height)
    with Image.open(io.BytesIO(data)) as opened:
        assert opened.format == "JPEG"
        assert opened.size == (1080, 1350)
    different, _, _ = images.generated_background({"accent_color": "#B7A0FF"}, "seed-b")
    with Image.open(io.BytesIO(different)) as opened:
        assert opened.format == "JPEG"
        assert opened.size == (1080, 1350)
    print("PASS generated art is produced at 1080x1350")


def test_card_credit() -> None:
    unsplash = images.ImageAsset(
        data=b"x",
        source="unsplash",
        width=1200,
        height=800,
        credit="Photo by Jane / Unsplash",
        caption_credit="Photo: Jane / Unsplash",
    )
    assert "Jane / Unsplash" in images.card_credit(unsplash, True)
    assert "Jane / Unsplash" in images.card_credit(unsplash, False)
    stock = images.ImageAsset(
        data=b"x",
        source="pixabay",
        width=1200,
        height=800,
        credit="Photo by John / Pixabay",
    )
    assert images.card_credit(stock, False) == ""
    assert "John / Pixabay" in images.card_credit(stock, True)
    assert images.card_credit(images.ImageAsset(data=b"x", source="generated", width=1, height=1), True) == ""
    print("PASS Unsplash credit is mandatory and optional credits follow config")


def test_fetch_image_chain_falls_back() -> None:
    config = {
        "image": {
            "order": ["unsplash", "generated"],
            "disabled": [],
            "prefer_article_photo": False,
            "show_credit": True,
        }
    }
    fallback = images.ImageAsset(
        data=b"fake-jpeg",
        source="generated",
        width=1080,
        height=1350,
        license_name="Generated",
    )

    def fake_generated(query, config, seed):
        fallback.query = query
        return fallback

    original = images._unsplash
    original_generated = images._generated
    images._unsplash = lambda query, used: (_ for _ in ()).throw(RuntimeError("offline"))
    images._generated = fake_generated
    try:
        asset = images.fetch_image("city skyline", config, {}, seed="test-seed")
    finally:
        images._unsplash = original
        images._generated = original_generated
    assert asset.source == "generated"
    assert "unsplash: RuntimeError" in asset.log, asset.log
    assert "generated: ok" in asset.log, asset.log
    print("PASS image chain isolates provider errors and falls back")


def main() -> None:
    tests = [
        test_prepare_image,
        test_prepare_resizes_large_image,
        test_prepare_handles_transparency,
        test_generated_background,
        test_card_credit,
        test_fetch_image_chain_falls_back,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} image self-tests passed.")


if __name__ == "__main__":
    main()