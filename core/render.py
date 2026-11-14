"""Headless Chrome screenshot plus Pillow JPEG conversion and sanity checks."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageStat

from core.storage import cards_dir

WIDTH = 1080
HEIGHT = 1350
CHROME_TIMEOUT = 60
MIN_STDDEV = 5.0


class RenderError(RuntimeError):
    pass


def find_chrome() -> Optional[str]:
    override = os.environ.get("CHROME_PATH")
    if override and Path(override).exists():
        return override
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    windows_paths = []
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            windows_paths.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
            windows_paths.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        windows_paths.append(str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    windows_paths.extend(
        [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    )
    for path in windows_paths:
        if Path(path).is_file():
            return path
    return None


def _chrome_command(chrome: str, html_path: Path, png_path: Path, profile: Path) -> List[str]:
    command = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--force-device-scale-factor=1",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=6000",
        f"--user-data-dir={profile}",
        f"--window-size={WIDTH},{HEIGHT}",
        f"--screenshot={png_path}",
        html_path.resolve().as_uri(),
    ]
    return command


def _attempt_render(html: str, chrome: str, workdir: Path) -> bytes:
    html_path = workdir / "card.html"
    png_path = workdir / "card.png"
    profile = workdir / "profile"
    html_path.write_text(html, encoding="utf-8")
    command = _chrome_command(chrome, html_path, png_path, profile)
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CHROME_TIMEOUT,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Chrome timed out while rendering") from exc
    except OSError as exc:
        raise RenderError(f"Chrome could not start: {type(exc).__name__}") from exc
    if not png_path.exists():
        tail = (completed.stderr or completed.stdout or "")[-500:].strip()
        raise RenderError(f"Chrome produced no screenshot. {tail}")
    return png_path.read_bytes()


def _check_png(raw: bytes) -> Dict[str, Any]:
    import io

    with Image.open(io.BytesIO(raw)) as opened:
        image = opened.convert("RGB")
    if image.size != (WIDTH, HEIGHT):
        raise RenderError(f"screenshot is {image.width}x{image.height}, expected 1080x1350")
    stddev = float(ImageStat.Stat(image.convert("L")).stddev[0])
    if stddev < MIN_STDDEV:
        raise RenderError("screenshot looks blank")
    colors = image.getcolors(maxcolors=200000)
    if colors is not None and len(colors) < 8:
        raise RenderError("screenshot has too few colours")
    return {
        "width": image.width,
        "height": image.height,
        "stddev": round(stddev, 2),
        "colors": len(colors) if colors else 0,
        "image": image,
    }


def render_card(
    html: str,
    name: str,
    root: Optional[Path] = None,
    fallback_html: str = "",
) -> Dict[str, Any]:
    chrome = find_chrome()
    if not chrome:
        raise RenderError(
            "Chrome was not found. Install Google Chrome or set CHROME_PATH."
        )
    target_dir = cards_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    png_path = target_dir / f"{name}.png"
    jpg_path = target_dir / f"{name}.jpg"
    attempts: List[str] = []
    chosen_html = html
    rendered: Optional[Dict[str, Any]] = None
    for index in range(2):
        workdir = Path(tempfile.mkdtemp(prefix="newscard_render_"))
        try:
            raw = _attempt_render(chosen_html, chrome, workdir)
            info = _check_png(raw)
            rendered = info
            attempts.append("model design" if index == 0 else "fallback design")
            break
        except RenderError as exc:
            attempts.append(str(exc))
            if index == 0 and fallback_html and fallback_html != chosen_html:
                chosen_html = fallback_html
                continue
            raise RenderError(
                "Card rendering failed after fallback: " + "; ".join(attempts)
            ) from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    if rendered is None:
        raise RenderError("Card rendering produced no image")
    image = rendered["image"]
    png_path.write_bytes(_attempt_bytes(image, "PNG"))
    jpg_path.write_bytes(_attempt_bytes(image, "JPEG"))
    return {
        "png": png_path.name,
        "jpg": jpg_path.name,
        "png_path": str(png_path),
        "jpg_path": str(jpg_path),
        "width": image.width,
        "height": image.height,
        "stddev": rendered["stddev"],
        "colors": rendered["colors"],
        "attempts": attempts,
        "chrome": chrome,
    }


def _attempt_bytes(image: Image.Image, fmt: str) -> bytes:
    import io

    output = io.BytesIO()
    if fmt == "PNG":
        image.save(output, format="PNG", optimize=True)
    else:
        image.save(output, format="JPEG", quality=92, optimize=True, subsampling=0)
    return output.getvalue()
