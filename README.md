# agent-backtest

[![Test](https://github.com/wangjohn/agent-backtest/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/wangjohn/agent-backtest/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Backtest coding agents (Claude Code, Codex, Cursor) on benchmarks built from your own past sessions.

> **Status: planning.** Nothing works yet beyond `backtest --version`. The design is in
> [docs/specs/v0-plan.md](docs/specs/v0-plan.md).

Public leaderboards compare models on someone else's tasks. agent-backtest answers a narrower,
more useful question: **on the work you actually do, which agent product and model should you
use, and what does it cost?** For example: does Codex with GPT beat Claude Code with Opus on your
refactors, and is a cheaper model good enough for your bug fixes?

It works from the sessions [agent-archive](https://github.com/wangjohn/agent-archive) already
keeps for you:

1. **Pick** past sessions that make good benchmark tasks.
2. **Build** each one into a replayable task: the repo as it was when the session started, an
   instruction, hidden tests, and a rubric drawn from the corrections you made along the way.
3. **Check** every task automatically (the real fix must pass, doing nothing must fail) and let
   you approve it.
4. **Run** each contestant (a whole setup: harness, version, model, effort, config) in a sandbox,
   several times, using [Harbor](https://docs.harborframework.com/).
5. **Grade** in layers: tests first, then a rubric, then blind pairwise comparison.
6. **Report** quality against cost for each kind of task, with honest uncertainty.

Everything runs locally. Your code and transcripts go only to the model providers you choose to
benchmark, never to this project.

## Development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run backtest --help
uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the checks CI runs.

## Related

- [agent-archive](https://github.com/wangjohn/agent-archive): captures and stores the sessions
  this tool reads.
- [Harbor](https://github.com/harbor-framework/harbor): runs the agents in sandboxes.

Maintained by [@wangjohn](https://github.com/wangjohn). Released under the [MIT License](LICENSE).
