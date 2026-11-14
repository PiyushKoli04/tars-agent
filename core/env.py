"""Small, dependency-free loader for local ``.env`` files.

The file is for local testing and manual runs only. GitHub Actions gets its
configuration from repository secrets, and real environment variables always
take precedence over values from ``.env``.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def parse_env_text(text: str) -> Dict[str, str]:
    """Parse simple KEY=value lines without evaluating shell syntax."""
    values: Dict[str, str] = {}
    for raw_line in text.lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = re.sub(
                    r"\\([nrt\"\\])",
                    lambda match: _ESCAPES.get(match.group(1), match.group(1)),
                    value,
                )
        values[key] = value
    return values


def load_env(
    path: Optional[Path] = None, override: bool = False
) -> Optional[Path]:
    """Load ``.env`` into ``os.environ`` and return the file path if present.

    Values already present in the process environment are never overwritten
    unless ``override=True`` is passed explicitly.
    """
    env_path = (path or (project_root() / ".env")).expanduser()
    try:
        if not env_path.is_file():
            return None
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for key, value in parse_env_text(text).items():
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path.resolve()


def _state(name: str) -> str:
    return "set" if (os.environ.get(name) or "").strip() else "missing"


def print_status(env_path: Optional[Path]) -> None:
    print(f".env: {env_path if env_path else '(not found; using process environment)'}")
    providers = [
        ("NVIDIA", ["NVIDIA_API_KEY", "NVIDIA_MODEL"]),
        ("OpenCode", ["OPENCODE_API_KEY", "OPENCODE_MODEL", "OPENCODE_BASE_URL"]),
        ("Gemini", ["GEMINI_API_KEY", "GEMINI_MODEL"]),
        ("Groq", ["GROQ_API_KEY", "GROQ_MODEL"]),
        ("Unsplash", ["UNSPLASH_ACCESS_KEY"]),
        ("Pixabay", ["PIXABAY_API_KEY"]),
    ]
    for label, keys in providers:
        print(f"{label}: " + ", ".join(f"{key}={_state(key)}" for key in keys))
    session_file = project_root() / "ig_session.json"
    session_hint = "set" if _state("IG_SESSION_JSON") == "set" else (
        "local file found" if session_file.is_file() else "missing"
    )
    print(f"Instagram session: {session_hint}")
    print(f"CHROME_PATH: {_state('CHROME_PATH')}")
    print(f"Local root override: {_state('NEWSCARD_ROOT')}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Load and inspect local .env settings")
    parser.add_argument("--file", default="", help="Path to an env file")
    args = parser.parse_args(argv)
    path = Path(args.file) if args.file else None
    loaded = load_env(path)
    print_status(loaded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
