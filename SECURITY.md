# Security policy

agent-backtest reads coding-agent transcripts, which can contain source code, credentials, and
personal data; it builds containers from private repositories, runs coding agents autonomously
inside them, and passes model-provider credentials to those agents. Security reports are welcome
and taken seriously.

## Reporting a vulnerability

Report privately through GitHub:
**[Security → Report a vulnerability](https://github.com/wangjohn/agent-backtest/security/advisories/new)**
(a private security advisory). Please don't open a public issue, discussion, or pull request for a
vulnerability.

Include what you found, the version (`backtest --version`), how to reproduce it (a synthetic
transcript or repository is ideal; never send real session content, private code, or credentials),
and what an attacker gains.

## What to expect

agent-backtest is maintained by one person, in spare time. Expect an acknowledgement within a week
and an assessment within two weeks. A confirmed vulnerability is fixed in `main` first, then
released, and credited in the advisory and the [changelog](CHANGELOG.md) unless you prefer
otherwise.

## Supported versions

The latest release is supported.
