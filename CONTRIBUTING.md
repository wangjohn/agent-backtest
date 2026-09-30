# Contributing

Thanks for helping. agent-backtest is early and maintained by one person, so the process is light.

## Before you start

- For anything bigger than a small fix, open an issue first so we can agree on the approach. The
  current design is [docs/specs/v0-plan.md](docs/specs/v0-plan.md).
- Vulnerabilities go through [SECURITY.md](SECURITY.md), never a public issue.
- By contributing you agree to license your work under the [MIT License](LICENSE).

## Set up

- Python 3.12 or newer (the repo's `.python-version` says 3.12; CI also runs 3.13).
- [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## What CI checks

```sh
uv lock --check
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
uv build
```

Run them before opening a pull request.

## Safety rules

- Never run contestant or builder agents outside a sandbox, and never against your real checkout
  or home directory. Tests use temporary directories and fakes; they never start Docker, use the
  network, or need real credentials.
- Never commit a real transcript, private code, or credentials, even in a fixture. Use synthetic
  content.
- A change to what leaves the user's machine (to model providers or anywhere else) is a privacy
  change. Say so in the pull request and update the docs.

## Releases

Releases are cut by pushing a `vX.Y.Z` tag that matches `version` in `pyproject.toml`. The release
workflow tests, builds, and publishes to PyPI through trusted publishing.
