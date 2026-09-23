# Contributing

Thanks for your interest in improving `turnstile-token`.

## Ground rules

- **Standard library only.** The package installs nothing else and that is
  deliberate. A dependency has to earn its place by doing something the
  standard library cannot.
- **Python 3.8+.** No syntax newer than 3.8 in shipped code.
- **Tests are not optional.** Every change ships with tests that pass offline,
  with no API key and no network access.

## Setting up

```bash
git clone https://github.com/<you>/turnstile-token.git
cd turnstile-token
python -m unittest discover -s tests -v
```

## Before you open a pull request

1. `python -m unittest discover -s tests` is green.
2. `python turnstile_token.py --version` and `python turnstile_token.py --help` work.
3. `git status` is clean.
4. New behaviour has new tests.
5. Docstrings match the code.

## Style

- `dataclasses` over hand-written `__init__`.
- Typed signatures with `from __future__ import annotations`.
- Short module docstrings that show a working example.
- Comments explain *why*, not *what*.

## Reporting bugs

Open an issue with the smallest reproduction you can manage. Include the
`errorCode` when there is one, and the output of `turnstile-token --version`.

## Security

Do not open a public issue for a security problem. See [SECURITY.md](SECURITY.md).
