#!/usr/bin/env python3
"""Quickstart: solve a Turnstile widget and replay the token.

Set CLEARANCE_API_KEY in your environment before running:

    export CLEARANCE_API_KEY="your_key_here"
    python examples/quickstart.py https://example.com/login

Pass a URL as the first argument, or edit the default below.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from turnstile_token import TurnstileClient, TurnstileError


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com/login"

    try:
        client = TurnstileClient.from_env()
    except TurnstileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"processing Turnstile on {url} ...", file=sys.stderr)

    try:
        bundle = client.solve(url)
    except TurnstileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"solved in {bundle.elapsed * 1000:.0f}ms")
    print(f"sitekey:    {bundle.sitekey}")
    print(f"token:      {bundle.token}")
    print(f"profile:    {bundle.profile_id}")
    print(f"user-agent: {bundle.user_agent}")
    print()
    print("replay headers:")
    for key, value in bundle.replay_headers().items():
        print(f"  {key}: {value}")
    print()
    print("form fields:")
    for key, value in bundle.form_fields().items():
        print(f"  {key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
