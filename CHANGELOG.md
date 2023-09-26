# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-09-25

### Added
- `SitekeyScanner` with confidence ranking across `data-sitekey`, JavaScript
  and query-string placements, plus context snippets for pages with several
  widgets.
- `verify_token` and the `turnstile verify` command for cheap local checks of
  token shape before wiring it into a pipeline.
- `ReplayBundle.replay_headers()` and `ReplayBundle.form_fields()` so the
  follow-up request carries the right identity and the right field names.
- `turnstile batch` for processing one URL per line from a file.
- `turnstile discover` prints every sitekey on a page, best first.

### Changed
- The client is now `TurnstileClient`, focused on the Turnstile solve flow.
  `solve()` discovers the sitekey automatically when one is not supplied.

## [1.0.0] - 2026-09-25

### Added
- Initial release.
- `TurnstileClient` with retries, `Retry-After` honouring and typed errors for
  every API error code.
- Sitekey discovery from `data-sitekey` attributes, JavaScript assignments and
  query-string keys.
- Identity replay block: User-Agent, profile id and the TLS/HTTP2 fingerprint
  the token was earned with.
- CLI: `solve`, `discover`, `verify`, `balance`, `batch`.
- Offline test suite, no network or API key required.

[1.1.0]: https://github.com/<you>/turnstile-token/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/<you>/turnstile-token/releases/tag/v1.0.0
