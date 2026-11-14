"""Create an Instagram session JSON locally, one time.

    python tools/get_session.py

Then store the file as the IG_SESSION_JSON GitHub secret. Never commit it.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ask(prompt: str, secret: bool = False) -> str:
    if secret:
        return getpass.getpass(prompt)
    return input(prompt)


def _challenge_help() -> str:
    return (
        "Instagram asked for a security check instead of logging in.\n"
        "1. Open Instagram on your phone and approve the login request or complete the check.\n"
        "2. Wait a few minutes, then run this script again.\n"
        "3. If it still fails, switch networks (mobile hotspot works) and try once more.\n"
        "Do not retry in a loop; Instagram will lock the account temporarily."
    )


def _login(client, username: str, password: str) -> None:
    from instagrapi.exceptions import (
        BadPassword,
        ChallengeRequired,
        TwoFactorRequired,
    )

    try:
        client.login(username, password)
        return
    except TwoFactorRequired:
        code = _ask("Two-factor code: ").strip()
        client.login(username, password, verification_code=code)
        return
    except ChallengeRequired as exc:
        raise SystemExit(_challenge_help()) from exc
    except BadPassword as exc:
        raise SystemExit("Instagram rejected the username or password.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an Instagram session for NewsCard Studio")
    parser.add_argument("--username", default="")
    parser.add_argument("--output", default=str(ROOT / "ig_session.json"))
    parser.add_argument("--sessionid", action="store_true", help="Import a browser sessionid instead of logging in")
    parser.add_argument("--no-verify", action="store_true", help="Skip the account check")
    args = parser.parse_args()
    try:
        from instagrapi import Client
        from instagrapi.exceptions import ChallengeRequired
    except ImportError:
        print("instagrapi is not installed. Run: pip install -r requirements.txt")
        return 2
    client = Client()
    client.delay_range = [1, 3]
    try:
        if args.sessionid:
            sessionid = _ask("Instagram sessionid cookie: ", secret=True).strip()
            if not sessionid:
                print("No sessionid provided.")
                return 2
            client.login_by_sessionid(sessionid)
        else:
            username = args.username.strip() or _ask("Instagram username: ").strip()
            password = _ask("Instagram password (not stored, not echoed): ", secret=True)
            if not username or not password:
                print("Username and password are required.")
                return 2
            _login(client, username, password)
        if not args.no_verify:
            try:
                account = client.account_info()
                print(f"Logged in as @{getattr(account, 'username', 'unknown')}.")
            except ChallengeRequired as exc:
                raise SystemExit(_challenge_help()) from exc
        settings = client.get_settings()
        if client.sessionid:
            settings["sessionid"] = client.sessionid
        output = Path(args.output).expanduser().resolve()
        output.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(output, 0o600)
        except OSError:
            pass
    except ChallengeRequired as exc:
        print(_challenge_help())
        return 1
    except Exception as exc:
        name = type(exc).__name__
        text = str(exc)
        if "challenge" in f"{name} {text}".lower():
            print(_challenge_help())
        else:
            print(f"Login failed: {name}. {text[:300]}")
        return 1
    print("")
    print(f"Session written to {output}")
    print("This file is a credential. Keep it private and never commit it.")
    print("Add it to GitHub Secrets (replace owner/repo):")
    print(f"  gh secret set IG_SESSION_JSON --repo owner/repo < \"{output}\"")
    print("Or paste the file contents into the IG_SESSION_JSON secret in the GitHub UI.")
    print("")
    print("If a run fails with an Instagram challenge, repeat this script later and update the secret.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
