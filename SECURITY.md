# Security Policy

## Reporting a vulnerability

If you find a security problem in this package, please report it privately
rather than opening a public issue.

- Open a [private security advisory](https://github.com/<you>/turnstile-token/security/advisories/new)
  on this repository, or
- email the maintainer through the contact link on [clearance.sh](https://clearance.sh).

Please include:

- what the problem is,
- how to reproduce it,
- what you think the impact is,
- any suggested fix.

You will get an acknowledgement within two working days and a fuller response
within seven.

## Rotating a key

Rotation takes effect immediately: the old key stops working the moment the
new one is issued. Deploy the new key to every integration first, then
rotate. A task that was already accepted keeps running, but reading its
result still needs a valid key, so re-poll with the new key before the
five-minute window closes.

## Scope

This package is a thin client over a third-party API. Problems in the API
itself, in Cloudflare, or in a site you are working against are out of scope
here and should be reported to the relevant vendor.

## Supported versions

Only the latest release receives security fixes. Older versions are not
patched.

## Credential handling

- Never commit an API key. Read it from `CLEARANCE_API_KEY` or pass `--api-key`.
- A leaked key cannot read your account, change settings or move funds, but it
  can spend credits. Rotate immediately if it escapes.
- Prefer the `X-Private-Key` header over putting the key in a request body -
  bodies end up in debug logs far more often than headers do.

Corrections are made before public disclosure so that users can upgrade without exposure.
