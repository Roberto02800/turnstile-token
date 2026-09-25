"""turnstile-token: a focused, dependency-free client for Cloudflare Turnstile tokens.

The Clearance API turns a Turnstile sitekey into a ready-to-submit
``cf-turnstile-response`` value in about 450 milliseconds. This package wraps
that flow end to end: it finds the sitekey on a page, asks Clearance to solve
it, verifies the token shape, and bundles the browser identity the token was
earned with so your follow-up request presents the same TLS and HTTP/2
fingerprint and the token is not thrown away.

Everything runs on the standard library. No browser, no SDK, no dependency
resolution.

Typical use::

    from turnstile_token import TurnstileClient

    client = TurnstileClient.from_env()
    bundle = client.solve("https://example.com/login")
    print(bundle.token)
    print(bundle.replay_headers())

Command line::

    turnstile-token solve --url https://example.com/login
    turnstile-token discover --page https://example.com/login
    turnstile-token verify --token 0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5
    turnstile-token balance

Library use without a client object::

    from turnstile_token import solve
    bundle = solve(api_key, "https://example.com/login")
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

__all__ = [
    "API_BASE",
    "ENV_API_KEY",
    "TASK_TYPE",
    "TurnstileError",
    "RETRYABLE_CODES",
    "SitekeyHit",
    "SitekeyScanner",
    "ReplayBundle",
    "TokenReport",
    "TurnstileClient",
    "create_task",
    "get_task_result",
    "get_balance",
    "solve",
    "solve_turnstile",
    "discover_sitekeys",
    "discover_sitekey",
    "verify_token",
    "read_page",
    "main",
    "__version__",
]

__version__ = "1.1.0"

API_BASE = "https://api.clearance.sh"
ENV_API_KEY = "CLEARANCE_API_KEY"
TASK_TYPE = "AntiTurnstileTask"

DEFAULT_TIMEOUT = 30.0
POLL_GRACE = 0.5
POLL_INTERVAL = 0.25
POLL_MAX = 60
DEFAULT_ATTEMPTS = 4

RETRYABLE_CODES = frozenset(
    {
        "ERROR_CAPTCHA_UNSOLVABLE",
        "ERROR_SERVICE_UNAVAILABLE",
        "ERROR_NO_SLOT_AVAILABLE",
    }
)

_USER_AGENT = "turnstile/" + __version__

# Three shapes Turnstile sitekeys actually appear in on real pages.
_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(
        r"""data-sitekey\s*=\s*["'](?P<attr>[^"']+)["']""",
        re.I,
    ),
    re.compile(
        r"""(?:sitekey|render)\s*[:=]\s*["'](?P<js>[^"']+)["']""",
        re.I,
    ),
    re.compile(
        r"""(?:k|sitekey)=(?P<qs>[0-9A-Za-z_-]{16,})""",
        re.I,
    ),
)

_TOKEN_SHAPE = re.compile(r"^[0-9A-Za-z._\-]{20,}$")


class TurnstileError(RuntimeError):
    """A refusal or failure reported by the API, or a bad local input.

    Attributes:
        code: the ``errorCode`` string, e.g. ``ERROR_NO_SLOT_AVAILABLE``.
        description: the human-readable ``errorDescription``.
        http_status: the HTTP status that accompanied the body.
        retry_after: seconds the server asked us to wait, when it said so.
    """

    def __init__(
        self,
        code: str,
        description: str = "",
        http_status: int = 200,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(f"{code}: {description}" if description else code)
        self.code = code
        self.description = description
        self.http_status = http_status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """True when re-sending the same request is worth doing."""
        return self.code in RETRYABLE_CODES


@dataclass
class SitekeyHit:
    """One sitekey found on a page.

    Attributes:
        value: the sitekey string itself.
        source: which pattern matched - ``attr``, ``js`` or ``qs``.
        context: a short snippet of surrounding text for disambiguation.
    """

    value: str
    source: str
    context: str = ""

    @property
    def confidence(self) -> float:
        """Heuristic confidence that this is the live widget key.

        ``data-sitekey`` attributes are the canonical placement and score
        highest. JavaScript assignments are usually the same key rendered by a
        script and score next. Query-string keys are often CDN references and
        score lowest.
        """
        return {"attr": 1.0, "js": 0.85, "qs": 0.6}.get(self.source, 0.5)


@dataclass
class TokenReport:
    """The result of checking a token's shape locally.

    Attributes:
        token: the value that was checked.
        plausible: whether the value looks like a real Turnstile token.
        length: character count.
        segments: how many dot-separated parts the token has.
        reasons: human-readable notes about what was seen.
    """

    token: str
    plausible: bool
    length: int
    segments: int
    reasons: List[str] = field(default_factory=list)


@dataclass
class ReplayBundle:
    """A solved token together with the identity that earned it.

    A Turnstile token is bound to the browser that produced it. Replaying the
    token from a different User-Agent, TLS handshake or HTTP/2 settings order
    makes Cloudflare reject it even though the solve succeeded. This object
    carries every piece needed to reproduce the identity.

    Attributes:
        token: the ``cf-turnstile-response`` value to submit.
        sitekey: the sitekey that was solved.
        url: the page the token was earned for.
        user_agent: the User-Agent the token was earned with.
        profile_id: the browser profile that solved it.
        headers: headers to replay alongside the token.
        cookies: cookies to replay, when the API returned any.
        emulation: the TLS and HTTP/2 fingerprint block.
        elapsed: seconds from ``createTask`` to ``ready``.
        raw: the full decoded ``solution`` object.
    """

    token: str
    sitekey: str = ""
    url: str = ""
    user_agent: str = ""
    profile_id: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    emulation: Dict[str, Any] = field(default_factory=dict)
    elapsed: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> Dict[str, Any]:
        """The identity block to reproduce on the follow-up request."""
        return {
            "userAgent": self.user_agent,
            "profileId": self.profile_id,
            "emulation": self.emulation,
        }

    def replay_headers(self) -> Dict[str, str]:
        """Headers for the follow-up request, with the correct User-Agent."""
        out = dict(self.headers)
        if self.user_agent:
            out["User-Agent"] = self.user_agent
        return out

    def form_fields(self) -> Dict[str, str]:
        """The form fields to POST with the token, under the usual names."""
        return {"cf-turnstile-response": self.token, "g-recaptcha-response": self.token}

    def as_dict(self) -> Dict[str, Any]:
        """A JSON-ready view of the bundle."""
        return {
            "token": self.token,
            "sitekey": self.sitekey,
            "url": self.url,
            "userAgent": self.user_agent,
            "profileId": self.profile_id,
            "headers": self.headers,
            "cookies": self.cookies,
            "emulation": self.emulation,
            "elapsed": round(self.elapsed, 3),
        }


class SitekeyScanner:
    """Finds Turnstile sitekeys in a page and ranks them by confidence.

    The scanner recognises the three shapes a sitekey takes in the wild: a
    ``data-sitekey`` attribute, a JavaScript ``sitekey`` assignment, and a
    ``k=`` query parameter on a CDN URL. Each match keeps a short context
    snippet so a page with several widgets can be told apart by hand.
    """

    def scan(self, html: str) -> List[SitekeyHit]:
        """Return every unique sitekey on the page, best first."""
        found: Dict[str, SitekeyHit] = {}
        for pattern in _PATTERNS:
            for match in pattern.finditer(html or ""):
                groups = match.groupdict()
                value = next((g for g in groups.values() if g), None)
                if not value:
                    continue
                value = value.strip()
                if not value or value in found:
                    continue
                source = next(k for k, v in groups.items() if v == value)
                start = max(0, match.start() - 30)
                end = min(len(html), match.end() + 30)
                found[value] = SitekeyHit(
                    value=value,
                    source=source,
                    context=html[start:end].replace("\n", " "),
                )
        return sorted(found.values(), key=lambda h: -h.confidence)

    def best(self, html: str) -> Optional[SitekeyHit]:
        """Return the highest-confidence sitekey, or ``None``."""
        hits = self.scan(html)
        return hits[0] if hits else None

    def values(self, html: str) -> List[str]:
        """Return just the sitekey strings, best first."""
        return [h.value for h in self.scan(html)]


_scanner = SitekeyScanner()


def discover_sitekeys(html: str) -> List[str]:
    """Return every unique Turnstile sitekey found in a page, best first."""
    return _scanner.values(html)


def discover_sitekey(html: str) -> Optional[str]:
    """Return the most likely Turnstile sitekey on a page, or ``None``."""
    hit = _scanner.best(html)
    return hit.value if hit else None


def verify_token(token: str) -> TokenReport:
    """Check a token's shape locally, without calling the API.

    A real Turnstile token is a long, dot-separated, URL-safe string. This is
    a cheap sanity check for pipeline wiring mistakes - truncated tokens,
    shell-quoting damage, tokens from the wrong field - not a cryptographic
    verification. Only Cloudflare can say whether a token is accepted.

    Args:
        token: the value to inspect.

    Returns:
        A :class:`TokenReport` describing what was seen.
    """
    token = (token or "").strip()
    reasons: List[str] = []
    length = len(token)
    segments = token.count(".") + 1 if token else 0

    if not token:
        return TokenReport(token="", plausible=False, length=0, segments=0, reasons=["empty"])

    if length < 20:
        reasons.append("short - real tokens are usually far longer")
    if not _TOKEN_SHAPE.match(token):
        reasons.append("contains characters outside the URL-safe alphabet")
    if segments < 2:
        reasons.append("no dot separators - Turnstile tokens are dot-delimited")
    if token.count(" ") > 0:
        reasons.append("contains whitespace - likely truncated or pasted wrong")
    if not reasons:
        reasons.append("shape looks correct")

    plausible = length >= 20 and _TOKEN_SHAPE.match(token) is not None and segments >= 2
    return TokenReport(
        token=token,
        plausible=plausible,
        length=length,
        segments=segments,
        reasons=reasons,
    )


def read_page(url: str, timeout: float = DEFAULT_TIMEOUT, proxy: Optional[str] = None) -> str:
    """Fetch a page and return its text body.

    Args:
        url: the page to fetch.
        timeout: request timeout in seconds.
        proxy: optional ``http://user:pass@host:port`` proxy for the fetch.
    """
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    if proxy:
        opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _normalise_proxy(proxy: Optional[str]) -> Optional[str]:
    """Accept ``host:port``, ``host:port:user:pass`` or a full URL."""
    if not proxy:
        return None
    value = proxy.strip()
    if "://" in value:
        return value
    parts = value.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{value}"
    return value


def _build_task(
    url: str,
    sitekey: str,
    proxy: Optional[str] = None,
    action: Optional[str] = None,
) -> Dict[str, Any]:
    if not sitekey:
        raise TurnstileError(
            "ERROR_INVALID_TASK_DATA",
            "AntiTurnstileTask requires task.websiteKey.",
        )
    task: Dict[str, Any] = {"type": TASK_TYPE, "websiteURL": url, "websiteKey": sitekey}
    normalised = _normalise_proxy(proxy)
    if normalised:
        task["proxy"] = normalised
    if action:
        task["metadata"] = {"action": action}
    return task


def _retry_after(exc: HTTPError) -> Optional[float]:
    try:
        value = exc.headers.get("Retry-After") if exc.headers else None
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def _post(
    path: str,
    payload: Dict[str, Any],
    api_key: str,
    timeout: float,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """POST one endpoint and decode the JSON body.

    Protocol errors arrive as HTTP 200 with ``errorId: 1``, so the body decides,
    not the status code. Only two conditions carry a real status: 401 for a bad
    key and 503 with ``Retry-After`` for a full fleet.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Private-Key": api_key,
        "User-Agent": _USER_AGENT,
    }
    req = Request(API_BASE + path, data=body, headers=headers, method="POST")

    opener = None
    if proxy:
        opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))

    try:
        if opener is not None:
            raw = opener.open(req, timeout=timeout).read()
        else:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
    except HTTPError as exc:
        retry_after = _retry_after(exc)
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            data = {}
        raise TurnstileError(
            str(data.get("errorCode") or f"HTTP_{exc.code}"),
            str(data.get("errorDescription") or str(exc.reason)),
            http_status=exc.code,
            retry_after=retry_after,
        ) from exc
    except URLError as exc:
        raise TurnstileError("ERROR_SERVICE_UNAVAILABLE", str(exc.reason)) from exc

    data = json.loads(raw.decode("utf-8"))
    if data.get("errorId"):
        raise TurnstileError(
            str(data.get("errorCode") or "ERROR_UNKNOWN"),
            str(data.get("errorDescription") or ""),
        )
    return data


def create_task(
    api_key: str,
    task: Mapping[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
    proxy: Optional[str] = None,
) -> str:
    """Submit a task and return its id. Capacity is checked before any charge."""
    if not api_key:
        raise TurnstileError(
            "ERROR_KEY_DOES_NOT_EXIST",
            "No API key. Set CLEARANCE_API_KEY or pass --api-key "
            "(free credits on sign-up at https://clearance.sh).",
            http_status=401,
        )
    payload = {"clientKey": api_key, "task": dict(task)}
    data = _post("/createTask", payload, api_key, timeout, proxy=proxy)
    task_id = str(data.get("taskId") or "")
    if not task_id:
        raise TurnstileError("ERROR_TASKID_INVALID", "Response carried no taskId.")
    return task_id


def get_task_result(
    api_key: str,
    task_id: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Fetch the current state of a task without consuming it."""
    payload = {"clientKey": api_key, "taskId": task_id}
    return _post("/getTaskResult", payload, api_key, timeout)


def get_balance(api_key: str, timeout: float = DEFAULT_TIMEOUT) -> float:
    """Return the account balance. The cheapest way to confirm a key works."""
    payload = {"clientKey": api_key}
    data = _post("/getBalance", payload, api_key, timeout)
    return float(data.get("balance") or 0.0)


class TurnstileClient:
    """A Clearance client bound to one API key, tuned for Turnstile solves.

    Args:
        api_key: the key from Dashboard -> Settings.
        timeout: per-request timeout in seconds.
        proxy: proxy applied to every task, ``http://user:pass@host:port``.
        attempts: retry budget for retryable errors.
        poll_grace: seconds to wait after createTask before polling.
        poll_interval: seconds between polls.
    """

    def __init__(
        self,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT,
        proxy: Optional[str] = None,
        attempts: int = DEFAULT_ATTEMPTS,
        poll_grace: float = POLL_GRACE,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.proxy = proxy
        self.attempts = max(1, attempts)
        self.poll_grace = poll_grace
        self.poll_interval = poll_interval

    @classmethod
    def from_env(cls, **kwargs: Any) -> "TurnstileClient":
        """Build a client from ``CLEARANCE_API_KEY``."""
        key = os.environ.get(ENV_API_KEY, "")
        if not key:
            raise TurnstileError(
                "ERROR_KEY_DOES_NOT_EXIST",
                f"Set {ENV_API_KEY} to your Clearance API key.",
                http_status=401,
            )
        return cls(key, **kwargs)

    def _with_retry(self, fn, *args: Any, **kwargs: Any) -> Any:
        backoff = 0.5
        for attempt in range(1, self.attempts + 1):
            try:
                return fn(*args, **kwargs)
            except TurnstileError as exc:
                if not exc.retryable or attempt == self.attempts:
                    raise
                if exc.retry_after is not None:
                    time.sleep(exc.retry_after)
                else:
                    time.sleep(backoff)
                    backoff *= 2
        raise AssertionError("unreachable")

    def create(self, task: Mapping[str, Any]) -> str:
        """Submit a task and return its id."""
        return self._with_retry(create_task, self.api_key, task, self.timeout, proxy=self.proxy)

    def result(self, task_id: str) -> Dict[str, Any]:
        """Read the current state of a task."""
        return self._with_retry(get_task_result, self.api_key, task_id, self.timeout)

    def balance(self) -> float:
        """Return the account balance."""
        return self._with_retry(get_balance, self.api_key, self.timeout)

    def poll(self, task_id: str, deadline: Optional[int] = None) -> ReplayBundle:
        """Wait for a task to finish and return the bundle.

        Raises :class:`TurnstileError` when the service reports failure. A task
        id expires five minutes after it was created.
        """
        started = time.time()
        time.sleep(self.poll_grace)
        for _ in range(POLL_MAX):
            data = self.result(task_id)
            status = data.get("status")
            if status == "ready":
                return _bundle(data, task_id=task_id, elapsed=time.time() - started)
            if status == "failed":
                raise TurnstileError(
                    str(data.get("errorCode") or "ERROR_CAPTCHA_UNSOLVABLE"),
                    str(data.get("errorDescription") or "The solve failed."),
                )
            if deadline is not None and time.time() - started > deadline:
                break
            time.sleep(self.poll_interval)
        raise TurnstileError(
            "ERROR_TASKID_INVALID",
            "Task did not become ready within the polling window.",
        )

    def solve(
        self,
        url: str,
        sitekey: Optional[str] = None,
        proxy: Optional[str] = None,
        action: Optional[str] = None,
    ) -> ReplayBundle:
        """Solve a Turnstile widget on ``url`` and return a replay bundle.

        When ``sitekey`` is omitted the page is fetched and the sitekey is
        discovered automatically.
        """
        resolved = sitekey
        if not resolved:
            html = read_page(url, timeout=self.timeout, proxy=proxy)
            resolved = discover_sitekey(html)
            if not resolved:
                raise TurnstileError(
                    "ERROR_INVALID_TASK_DATA",
                    f"No Turnstile sitekey found on {url}.",
                )
        task = _build_task(url, resolved, proxy=proxy, action=action)
        task_id = self.create(task)
        bundle = self.poll(task_id)
        bundle.sitekey = resolved
        bundle.url = url
        return bundle


def _bundle(data: Mapping[str, Any], task_id: str, elapsed: float) -> ReplayBundle:
    sol = dict(data.get("solution") or {})
    return ReplayBundle(
        token=str(sol.get("token") or ""),
        user_agent=str(sol.get("userAgent") or ""),
        profile_id=str(sol.get("profileId") or ""),
        headers={str(k): str(v) for k, v in dict(sol.get("headers") or {}).items()},
        cookies={str(k): str(v) for k, v in dict(sol.get("cookies") or {}).items()},
        emulation=dict(sol.get("emulation") or {}),
        elapsed=elapsed,
        raw=sol,
    )


def solve(
    api_key: str,
    url: str,
    sitekey: Optional[str] = None,
    proxy: Optional[str] = None,
    action: Optional[str] = None,
    attempts: int = DEFAULT_ATTEMPTS,
) -> ReplayBundle:
    """One-shot solve without managing a :class:`TurnstileClient`."""
    client = TurnstileClient(api_key, attempts=attempts, proxy=proxy)
    return client.solve(url, sitekey=sitekey, action=action)


def solve_turnstile(
    api_key: str,
    sitekey: str,
    url: str,
    proxy: Optional[str] = None,
    action: Optional[str] = None,
) -> ReplayBundle:
    """One-shot Turnstile solve with an explicit sitekey."""
    return solve(api_key, url, sitekey=sitekey, proxy=proxy, action=action)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="turnstile-token",
        description="Obtain a Cloudflare Turnstile token from Clearance.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get(ENV_API_KEY, ""),
        help=f"Clearance API key (default: {ENV_API_KEY})",
    )
    parser.add_argument("--proxy", help="Proxy as http://user:pass@host:port")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-request timeout")
    parser.add_argument("--retries", type=int, default=DEFAULT_ATTEMPTS, help="Retry budget")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    parser.add_argument("--verbose", action="store_true", help="Print the full bundle JSON")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command")

    solve_p = sub.add_parser("solve", help="Solve a Turnstile widget and print the token")
    solve_p.add_argument("--url", required=True, help="Target page URL")
    solve_p.add_argument("--sitekey", help="Turnstile sitekey (0x...)")
    solve_p.add_argument("--action", help="Optional widget data-action")

    disc = sub.add_parser("discover", help="Print sitekeys found on a page")
    disc.add_argument("--page", required=True, help="Page to scan")

    ver = sub.add_parser("verify", help="Check a token's shape locally")
    ver.add_argument("--token", required=True, help="Token value to inspect")

    sub.add_parser("balance", help="Print the account balance")

    batch = sub.add_parser("batch", help="Solve one URL per line from a file")
    batch.add_argument("file", help="File with one URL per line")
    batch.add_argument("--sitekey", help="Sitekey to use for every URL")

    return parser


def _say(args: argparse.Namespace, msg: str) -> None:
    if not args.quiet:
        print(msg, file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "discover":
        html = read_page(args.page, timeout=args.timeout)
        keys = discover_sitekeys(html)
        if not keys:
            print("no sitekey found", file=sys.stderr)
            return 2
        for key in keys:
            print(key)
        return 0

    if args.command == "verify":
        report = verify_token(args.token)
        print(json.dumps(report.__dict__, indent=2))
        return 0 if report.plausible else 1

    if not args.api_key:
        print(
            f"error: no API key. Set {ENV_API_KEY} or pass --api-key "
            "(free credits at https://clearance.sh)",
            file=sys.stderr,
        )
        return 2

    if args.command == "balance":
        try:
            print(f"{get_balance(args.api_key, args.timeout):.5f}")
        except TurnstileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    client = TurnstileClient(
        args.api_key,
        timeout=args.timeout,
        proxy=args.proxy,
        attempts=args.retries,
    )

    try:
        if args.command == "batch":
            lines = [
                line.strip()
                for line in open(args.file, encoding="utf-8")
                if line.strip() and not line.startswith("#")
            ]
            out: List[Dict[str, Any]] = []
            for target in lines:
                try:
                    bundle = client.solve(target, sitekey=args.sitekey)
                    out.append({"url": target, "token": bundle.token, "ok": True})
                except TurnstileError as exc:
                    out.append({"url": target, "ok": False, "error": str(exc)})
            print(json.dumps(out, indent=2))
            return 0 if all(item["ok"] for item in out) else 1

        if args.command == "solve":
            bundle = client.solve(args.url, sitekey=args.sitekey, action=args.action)

        else:  # pragma: no cover - argparse guards this
            parser.error(f"unknown command {args.command}")
            return 2

    except TurnstileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.retryable:
            print("this code is retryable -- the failure was refunded", file=sys.stderr)
        return 1

    _say(args, f"solved in {bundle.elapsed * 1000:.0f}ms")
    if args.verbose:
        print(json.dumps(bundle.as_dict(), indent=2))
    else:
        print(bundle.token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
