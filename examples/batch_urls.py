#!/usr/bin/env python3
"""Batch: solve Turnstile on every URL in a file.

One URL per line; blank lines and # comments are skipped. Results go to
stdout as JSON; progress goes to stderr.

    export CLEARANCE_API_KEY="your_key_here"
    python examples/batch_urls.py targets.txt > results.json

A failure on one URL never aborts the batch - the error is recorded next to
its URL and the run continues.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from turnstile_token import TurnstileClient, TurnstileError


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} FILE [--sitekey KEY]", file=sys.stderr)
        return 2

    path = sys.argv[1]
    sitekey = None
    if "--sitekey" in sys.argv:
        idx = sys.argv.index("--sitekey")
        if idx + 1 < len(sys.argv):
            sitekey = sys.argv[idx + 1]

    try:
        client = TurnstileClient.from_env()
    except TurnstileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    with open(path, encoding="utf-8") as fh:
        lines = [
            line.strip()
            for line in fh
            if line.strip() and not line.startswith("#")
        ]

    if not lines:
        print("no URLs found", file=sys.stderr)
        return 2

    results = []
    for i, target in enumerate(lines, 1):
        print(f"[{i}/{len(lines)}] {target}", file=sys.stderr)
        try:
            bundle = client.solve(target, sitekey=sitekey)
            results.append(
                {
                    "url": target,
                    "ok": True,
                    "token": bundle.token,
                    "sitekey": bundle.sitekey,
                    "elapsed": round(bundle.elapsed, 3),
                }
            )
        except TurnstileError as exc:
            results.append({"url": target, "ok": False, "error": str(exc)})

    print(json.dumps(results, indent=2))
    ok = sum(1 for r in results if r["ok"])
    print(f"{ok}/{len(results)} solved", file=sys.stderr)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
