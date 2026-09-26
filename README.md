<a href="https://clearance.sh/register?ref=UQ428VM">
  <img src="./assets/clearance-banner.png" alt="Clearance - Cloudflare Turnstile tokens in 451ms, $0.40 per 1,000" width="100%">
</a>

# turnstile-token

A small, dependency-free Python client and CLI for Cloudflare Turnstile tokens, backed by the [Clearance](https://clearance.sh/register?ref=UQ428VM) API.

It finds the sitekey on a page, gets you a ready-to-submit `cf-turnstile-response` value in about 451 milliseconds, and hands back the browser identity the token was earned with - so your follow-up request presents the same TLS and HTTP/2 fingerprint and the token is not thrown away.

<a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-credits.png" alt="Get free credits" height="46"></a>
&nbsp;
<a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-pricing.png" alt="Pricing" height="46"></a>
&nbsp;
<a href="https://clearance.sh/docs/quickstart"><img src="./assets/btn-docs.png" alt="Read the docs" height="46"></a>

- **Free credits on sign-up.** No card, no trial countdown - create an account and get started.
- **$0.40 per 1,000.** $0.00040 a solve. Failed solves are refunded in full.
- **451ms** average Turnstile solve, with a live figure on the [status page](https://clearance.sh/status).
- **No runtime dependencies.** Standard library only, Python 3.8+.
- **Sitekey discovery built in.** Point it at a page; it finds the key.

---

## Contents

- [Pricing](#pricing)
- [Why tokens fail and how this fixes it](#why-tokens-fail-and-how-this-fixes-it)
- [Install](#install)
- [Quickstart](#quickstart)
- [Sitekey discovery](#sitekey-discovery)
- [Token verification](#token-verification)
- [The replay bundle](#the-replay-bundle)
- [Task parameters](#task-parameters)
- [The polling rhythm](#the-polling-rhythm)
- [Error handling](#error-handling)
- [CLI reference](#cli-reference)
- [Batch runs](#batch-runs)
- [FAQ](#faq)

---

## Pricing

One service, one price. Billed per solve, with no subscription and no minimum spend.

| Service | `task.type` | Price / 1,000 | Per solve | Avg solve |
| --- | --- | --- | --- | --- |
| **Cloudflare Turnstile** | `AntiTurnstileTask` | **$0.40** | $0.00040 | **451ms** |

**Free credits on sign-up** - enough to run your first integration before you spend anything.

**Unlimited plans** are available for sustained volume - ask for pricing.

### How that compares

Published per-1,000 rates for Cloudflare Turnstile, gathered from each provider's own pricing page:

| Provider | Turnstile / 1,000 |
| --- | --- |
| **Clearance** | **$0.40** |
| CapMonster Cloud | $0.80 |
| CapSolver | $0.80 - $1.00 |
| Anti-Captcha | $1.50 |
| CaptchaSonic | $1.45 |
| 2Captcha | $1.45 - $1.99 |

At $0.40 that is roughly a third of what the field charges, without giving up solve time - Turnstile averages **451ms** here against a published field average of about 8 seconds.

<a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-credits.png" alt="Get free credits" height="46"></a>

---

## Why tokens fail and how this fixes it

The most common Turnstile integration bug is not the solve. The solve works, the token comes back, the request goes out - and Cloudflare rejects it.

The reason: **a Turnstile token is bound to the browser that earned it.** The User-Agent, the TLS handshake and the HTTP/2 settings present when the widget was solved are baked into the token. Replay it from a different client and the edge treats it as if you had never solved anything.

Most clients return a bare token string and leave you to guess the rest. This package returns the token **together with** the identity that earned it:

```python
bundle = client.solve("https://example.com/login")

bundle.token        # the cf-turnstile-response value
bundle.user_agent   # the exact User-Agent
bundle.profile_id   # e.g. "brave151-windows-b0ddf2db"
bundle.emulation    # TLS + HTTP/2 fingerprint block
bundle.replay_headers()   # headers ready to send
bundle.form_fields()      # form fields ready to POST
```

Send all of it and the token clears. Send the token alone and you are guessing.

---

## Install

```bash
pip install turnstile-token
```

Or straight from source:

```bash
git clone https://github.com/<you>/turnstile-token.git
cd turnstile-token
pip install .
```

No dependency resolution is needed - the package installs nothing else.

---

## Quickstart

Create an account to get your key - it takes about a minute and comes with **free credits**:

<a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-credits.png" alt="Get free credits" height="46"></a>

Then export the key from **Dashboard > Settings**:

```bash
export CLEARANCE_API_KEY="your_key_here"
```

### From the command line

```bash
turnstile-token solve --url https://example.com/login
turnstile-token solve --url https://example.com/login --sitekey 0x4AAAAAAAxxxx --action login
turnstile-token discover --page https://example.com/login
turnstile-token verify --token 0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5
turnstile-token balance
```

The token is printed to stdout; progress goes to stderr, so the output is safe to pipe.

### As a library

```python
from turnstile_token import TurnstileClient

client = TurnstileClient.from_env()
bundle = client.solve("https://example.com/login")

print(bundle.token)          # submit as cf-turnstile-response
print(bundle.profile_id)     # the browser that solved it

# replay with the identity that earned it
headers = bundle.replay_headers()
fields = bundle.form_fields()
```

Pass a sitekey explicitly when you already have one:

```python
bundle = client.solve("https://example.com/login", sitekey="0x4AAAAAAAxxxx", action="login")
```

### With curl

Two calls, no SDK, no browser:

```bash
# 1. create the task
curl -s https://api.clearance.sh/createTask \
  -H 'content-type: application/json' \
  -d '{
    "clientKey": "YOUR_API_KEY",
    "task": {
      "type": "AntiTurnstileTask",
      "websiteURL": "https://example.com/login",
      "websiteKey": "0x4AAAAAAAxxxx"
    }
  }'
```

```json
{ "errorId": 0, "status": "idle", "taskId": "0f5a5b6c-9a5a-4a1e-9d3f-2b8c5a9e4d71" }
```

```bash
# 2. read the result (sleep ~500ms first, then poll every 200-300ms)
curl -s https://api.clearance.sh/getTaskResult \
  -H 'content-type: application/json' \
  -d '{"clientKey": "YOUR_API_KEY", "taskId": "0f5a5b6c-9a5a-4a1e-9d3f-2b8c5a9e4d71"}'
```

```json
{
  "errorId": 0,
  "taskId": "0f5a5b6c-9a5a-4a1e-9d3f-2b8c5a9e4d71",
  "status": "ready",
  "solution": {
    "token": "0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5",
    "type": "turnstile",
    "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "profileId": "brave151-windows-b0ddf2db",
    "emulation": { "alpn": ["h2", "http/1.1"], "key_shares": ["X25519MLKEM768", "X25519"] }
  }
}
```

---

## Sitekey discovery

You do not always have the sitekey to hand. If it is not already in your config, pull it off the page:

```python
from turnstile_token import SitekeyScanner, discover_sitekey, discover_sitekeys, read_page

html = read_page("https://example.com/login")
sitekey = discover_sitekey(html)     # most likely match, or None
every = discover_sitekeys(html)      # all unique matches, best first
```

The scanner recognises the three shapes Turnstile keys actually appear in:

```html
<div class="cf-turnstile" data-sitekey="0x4AAAAAAAabc123"></div>
```
```js
turnstile.render(el, { sitekey: "0x4AAAAAAAabc123" });
```
```
/cdn-cgi/challenge-platform/...?k=0x4AAAAAAAabc123
```

Each match carries a confidence score and a context snippet, so a page with several widgets can be told apart:

```python
scanner = SitekeyScanner()
for hit in scanner.scan(html):
    print(hit.value, hit.source, hit.confidence, hit.context)
```

| Source | Placement | Confidence |
| --- | --- | --- |
| `attr` | `data-sitekey="..."` | 1.00 |
| `js` | `sitekey: "..."` in a script | 0.85 |
| `qs` | `?k=...` on a CDN URL | 0.60 |

From the shell:

```bash
turnstile-token discover --page https://example.com/login
```

---

## Token verification

A cheap local check for pipeline wiring mistakes - truncated tokens, shell-quoting damage, tokens from the wrong field:

```python
from turnstile_token import verify_token

report = verify_token("0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5")
print(report.plausible)   # True
print(report.length)      # 37
print(report.segments)    # 2
print(report.reasons)     # ["shape looks correct"]
```

From the shell:

```bash
turnstile-token verify --token 0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5
```

```json
{
  "token": "0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5",
  "plausible": true,
  "length": 37,
  "segments": 2,
  "reasons": ["shape looks correct"]
}
```

Exit code `0` when the shape is plausible, `1` when it is not. This checks the shape only - only Cloudflare can say whether a token is accepted.

---

## The replay bundle

A `ready` result is turned into a `ReplayBundle`:

| Field | Meaning |
| --- | --- |
| `token` | The `cf-turnstile-response` value to submit. |
| `sitekey` | The sitekey that was solved. |
| `url` | The page the token was earned for. |
| `user_agent` | The User-Agent the token was earned with. |
| `profile_id` | The browser profile that solved it, e.g. `brave151-windows-b0ddf2db`. |
| `headers` | Headers to replay alongside the token. |
| `cookies` | Cookies to replay, when the API returned any. |
| `emulation` | The TLS and HTTP/2 fingerprint block. |
| `elapsed` | Seconds from `createTask` to `ready`. |

The emulation block is what makes the replay work:

```json
"emulation": {
  "alpn": ["h2", "http/1.1"],
  "curves_list": "X25519MLKEM768:X25519:P-256:P-384",
  "key_shares": ["X25519MLKEM768", "X25519"],
  "min_tls_version": "1.2",
  "max_tls_version": "1.3",
  "permute_extensions": true,
  "http2": {
    "settings_order": [1, 2, 4, 6],
    "headers_pseudo_order": ["m", "a", "s", "p"]
  }
}
```

Three helpers package it for you:

```python
bundle.identity          # {"userAgent", "profileId", "emulation"}
bundle.replay_headers()  # headers with the correct User-Agent
bundle.form_fields()     # {"cf-turnstile-response", "g-recaptcha-response"}
```

Send the follow-up request with **all** of it:

```python
bundle = client.solve(url)

final = post(
    url,
    headers=bundle.replay_headers(),
    data=bundle.form_fields(),
    # ... and a TLS/HTTP2 stack configured from bundle.emulation
)
```

A client that checks only `response.ok` and replays the token with a default HTTP library will present a different handshake, and the token is thrown away. That is the failure people blame on the service.

---

## Task parameters

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `task.websiteURL` | url | yes | absolute http/https, max 2048 characters |
| `task.websiteKey` | string | yes | the sitekey, max 128 characters |
| `task.proxy` | string | optional | `scheme://[user:pass@]host:port`, max 512 |
| `task.metadata.action` | string | optional | the widget's `data-action`, max 64 characters |
| `task.metadata.cdata` | string | **rejected** | sending it is an error, not a no-op |

```python
bundle = client.solve(
    "https://example.com/login",
    sitekey="0x4AAAAAAAAjq6WYeRDKmebM",
    action="login",
    proxy="http://user:pass@host:port",
)
```

### Proxies

Every task accepts an optional proxy so the solve happens from your own exit IP, which matters when the target is IP-sensitive:

```python
client = TurnstileClient(key, proxy="http://user:pass@host:port")
```

This package also accepts the shorter `host:port:user:pass` form and normalises it. Leave the proxy off and the solve uses Clearance's egress instead.

---

## The polling rhythm

Everything is asynchronous. `/createTask` returns an id immediately; `/getTaskResult` returns the solution once a node has produced it.

- Sleep about **500ms** after creating the task.
- Then poll every **200-300ms**. Sooner mostly buys you `processing` responses; slower adds latency that has nothing to do with the service.
- A result lives for **five minutes**, and **reading it does not consume it**. The same solution comes back until it expires, so a retry after a dropped connection is free and you never lose a solve you already paid for.
- After five minutes the id is gone and returns `ERROR_TASKID_INVALID`.

The `TurnstileClient` does all of this for you:

```python
bundle = client.poll(task_id)          # 500ms grace, then 250ms polls
```

Or drive it yourself:

```python
task_id = client.create({"type": "AntiTurnstileTask", "websiteURL": url, "websiteKey": sitekey})
time.sleep(0.5)
while True:
    data = client.result(task_id)
    if data["status"] == "ready":
        break
    if data["status"] == "failed":
        raise RuntimeError(data["errorCode"])
    time.sleep(0.25)
```

---

## Error handling

Seven codes cover everything the API can refuse or fail to do. Three are worth retrying, four are not.

Protocol errors arrive as **HTTP 200 with `errorId: 1`** - that is deliberate, so a client that only checks the status code will happily read a failed solve as a success. Branch on the body, check `errorId`, then switch on `errorCode`.

| `errorCode` | HTTP | Retry? | Meaning |
| --- | --- | --- | --- |
| `ERROR_KEY_DOES_NOT_EXIST` | 401 | no | The key is wrong or missing. Fix the credential. |
| `ERROR_INVALID_TASK_DATA` | 200 | no | A required field is missing, malformed, or rejected. |
| `ERROR_TASK_NOT_SUPPORTED` | 200 | no | Unknown `task.type`, or the service is disabled. |
| `ERROR_TASKID_INVALID` | 200 | no | No such id, or it is older than five minutes. |
| `ERROR_CAPTCHA_UNSOLVABLE` | 200 | **yes** | Attempted and failed. Often transient; refunded. |
| `ERROR_SERVICE_UNAVAILABLE` | 200 | **yes** | Service did not answer in time, or maintenance. |
| `ERROR_NO_SLOT_AVAILABLE` | 503 | **yes** | No capacity. Nothing attempted, nothing charged. Honour `Retry-After`. |

This package models all of that:

```python
from turnstile_token import TurnstileError, RETRYABLE_CODES

try:
    bundle = client.solve(url)
except TurnstileError as exc:
    if exc.code == "ERROR_KEY_DOES_NOT_EXIST":
        ...                       # fix the key, do not retry
    elif exc.retryable:
        ...                       # back off and try again
    else:
        raise                     # a bug in the request
```

`TurnstileClient` already applies exponential backoff to retryable codes and prefers `Retry-After` over its own guess whenever the server sends one. The retry budget is capped so an incident cannot turn into a silent hang.

---

## Billing

- **$0.40 per 1,000 solves** - $0.00040 each.
- **A failed solve is refunded in full and is not billed.**
- **Capacity is checked before any money moves.** `ERROR_NO_SLOT_AVAILABLE` never charges you at all.
- **No subscription, no minimum spend.** Pay for what clears.

Check your balance without touching anything else:

```bash
turnstile-token balance
# 303.43519
```

<a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-credits.png" alt="Get free credits" height="46"></a>

---

## CLI reference

```
turnstile-token solve    --url URL [--sitekey KEY] [--action NAME]
turnstile-token discover --page URL
turnstile-token verify   --token TOKEN
turnstile-token balance
turnstile-token batch    FILE [--sitekey KEY]
```

Global flags: `--api-key`, `--proxy`, `--timeout`, `--retries`, `--quiet`, `--verbose`, `--version`.

| Flag | Default | Notes |
| --- | --- | --- |
| `--api-key` | `$CLEARANCE_API_KEY` | Falls back to the environment variable. |
| `--proxy` | - | `http://user:pass@host:port`, `host:port:user:pass` or `host:port`. |
| `--timeout` | `30` | Per-request timeout in seconds. |
| `--retries` | `4` | Budget for retryable codes only. |
| `--verbose` | off | Prints the full bundle JSON, including the identity block. |
| `--quiet` | off | Suppresses progress output on stderr. |

Exit codes: `0` success, `1` solve failed, `2` usage or credential problem.

---

## Batch runs

```bash
python examples/batch_urls.py targets.txt > results.json
```

One URL per line; blank lines and `#` comments are skipped. A failure on one URL never aborts the batch - the error is recorded next to its URL:

```json
[
  { "url": "https://a.example/", "ok": true,  "token": "0." },
  { "url": "https://b.example/", "ok": false, "error": "ERROR_CAPTCHA_UNSOLVABLE: no token produced" }
]
```

The CLI has the same thing built in:

```bash
turnstile-token batch targets.txt
```

---

## FAQ

**How much does a solve cost?**
**$0.40 per 1,000** - $0.00040 each. Failed solves are refunded. New accounts start with free credits.

**How fast is a solve?**
Turnstile averages **451ms**. The live figure is published on the [status page](https://clearance.sh/status) without needing an account.

**Do I need a browser?**
No. Two REST calls, no SDK, nothing to install on your side.

**Can I use my own proxy?**
Yes - every task accepts an optional `proxy`. Leave it off and the solve uses Clearance's egress instead.

**Why did my token fail even though the solve succeeded?**
Almost always the identity. The token is bound to the User-Agent and TLS handshake that earned it. Replay `bundle.replay_headers()` and a stack configured from `bundle.emulation`, not your default HTTP client.

**How long does a Turnstile token last?**
Treat it as a single-use value. It is valid for the submission it was earned for and is not meant to be stored or replayed across sessions.

**What happens if a solve fails?**
You are refunded in full and not billed. The code is `ERROR_CAPTCHA_UNSOLVABLE` and it is retryable.

**Is there a public status page?**
Yes - [clearance.sh/status](https://clearance.sh/status) publishes solve activity, queue depth and node capacity, refreshing every 30 seconds, and the same figures are available as JSON with no API key.

**How do I get volume pricing?**
Unlimited plans are arranged directly on request.

---

## get started

Free credits on sign-up, no card required.

<a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-credits.png" alt="Get free credits" height="46"></a>
&nbsp;
<a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-pricing.png" alt="Pricing" height="46"></a>
&nbsp;
<a href="https://clearance.sh/docs/quickstart"><img src="./assets/btn-docs.png" alt="Read the docs" height="46"></a>
&nbsp;
<a href="https://clearance.sh/status"><img src="./assets/btn-status.png" alt="Live status" height="46"></a>

---

<p align="center">
  <b>Turnstile tokens in 451ms.</b><br>
  <i>Sitekey discovery, one command, identity replay - at $0.40 per 1,000, fully automated, failed solves refunded.</i>
</p>

<p align="center">
  <b>451ms avg</b> &nbsp;&middot;&nbsp; <b>$0.40 / 1K</b> &nbsp;&middot;&nbsp; <b>Free credits</b> &nbsp;&middot;&nbsp; <b>Failures refunded</b>
</p>

<p align="center">
  <a href="https://clearance.sh/register?ref=UQ428VM"><img src="./assets/btn-credits.png" alt="Get free credits" height="46"></a>
</p>

## License

MIT - see [LICENSE](LICENSE).

See [CHANGELOG.md](CHANGELOG.md) for release history, [CONTRIBUTING.md](CONTRIBUTING.md) for the ground rules, and [SECURITY.md](SECURITY.md) for private vulnerability reporting.

This is an unofficial client. Clearance is a separate service; see [clearance.sh](https://clearance.sh/register?ref=UQ428VM) for terms.

