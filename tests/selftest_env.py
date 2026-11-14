"""Offline self-test for the local .env loader.

Run from the repo root:

    python -m tests.selftest_env
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import env  # noqa: E402

KEEP = "NEWSCARD_ENV_TEST_KEEP"
NEW = "NEWSCARD_ENV_TEST_NEW"


def test_parser() -> None:
    text = """\ufeff# full-line comment
PLAIN=value
SPACES=value with spaces
EQUALS=left=right
SINGLE='a # literal value'
DOUBLE="line\\nnext"
EMPTY=
export EXPORTED=yes
INVALID LINE
1INVALID=no
"""
    values = env.parse_env_text(text)
    assert values["PLAIN"] == "value", values
    assert values["SPACES"] == "value with spaces", values
    assert values["EQUALS"] == "left=right", values
    assert values["SINGLE"] == "a # literal value", values
    assert values["DOUBLE"] == "line\nnext", values
    assert values["EMPTY"] == "", values
    assert values["EXPORTED"] == "yes", values
    assert "INVALID LINE" not in values
    assert "1INVALID" not in values
    print("PASS .env parser handles comments, quotes and spaced paths")


def test_load_precedence() -> None:
    old_keep = os.environ.get(KEEP)
    old_new = os.environ.get(NEW)
    try:
        os.environ[KEEP] = "from-process"
        os.environ.pop(NEW, None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                f"{KEEP}=from-file\n{NEW}=from-file\n",
                encoding="utf-8",
            )
            loaded = env.load_env(path)
            assert loaded == path.resolve(), loaded
            assert os.environ[KEEP] == "from-process"
            assert os.environ[NEW] == "from-file"
            env.load_env(path, override=True)
            assert os.environ[KEEP] == "from-file"
        missing = env.load_env(Path(tempfile.gettempdir()) / "newscard-no-such.env")
        assert missing is None
    finally:
        if old_keep is None:
            os.environ.pop(KEEP, None)
        else:
            os.environ[KEEP] = old_keep
        if old_new is None:
            os.environ.pop(NEW, None)
        else:
            os.environ[NEW] = old_new
    print("PASS process values win unless override is explicit")


def test_example_is_ignored_by_git() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignore
    assert ".env.*" in ignore
    assert "!.env.example" in ignore
    assert (ROOT / ".env.example").is_file()
    print("PASS .env is ignored while .env.example is kept")


def test_run_loads_env() -> None:
    from core import run

    called = []
    original = run.load_env
    run.load_env = lambda: called.append(True)
    try:
        code = run.main(["--action", "tick", "--style", "99"])
    finally:
        run.load_env = original
    assert code == 2, code
    assert called, "core.run did not call the .env loader"
    print("PASS core.run loads .env before validating a run")


def main() -> None:
    tests = [
        test_parser,
        test_load_precedence,
        test_example_is_ignored_by_git,
        test_run_loads_env,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} env self-tests passed.")


if __name__ == "__main__":
    main()