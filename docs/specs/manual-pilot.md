# Manual M1 pilot

Status: offline support, scoped to the hand-built M1 in [v0-plan.md](v0-plan.md).
Prepare three complete tasks first; expand toward approximately ten only after qualification
holds. Fewer reconstructable tasks are preferable to weaker gates. Comparison is exactly two
whole contestant configurations, three attempts per task. This addendum does not implement M2
selection/inference, an automatic builder, judging, or a runner.

`backtest pilot` reads local, explicitly selected files and prints JSON. It never starts a
subprocess, accesses credentials, opens Docker, invokes an agent, or sends data anywhere.
Harbor/provider execution remains a separate action. Keep exports, source histories, packages,
results, and run configuration **outside this public repository**. Its tests use invented exports
and fake runner artifacts in temporary directories; they are not qualification results.

## Commands and exit status

```sh
backtest pilot inspect-export /private-workspace/exports.jsonl
backtest pilot validate /private-workspace/packages/task-one
backtest pilot plan /private-workspace/run.json /private-workspace/packages/task-one
```

`inspect-export` prints a file SHA256 and per-record identity, source/detail, recorded start,
prompt count, truncation and replay flags. It omits prompts, final responses, error messages,
and local source paths. It accepts Agent Archive eval-export schema version 1 only, including
per-record errors, unknown error codes, and additive fields. It checks the field subset consumed
here, **not the complete upstream JSON Schema**. Full records may omit `files_edited` when edit
evidence is unavailable. Native transcript formats are never parsed.
Malformed consumed fields or unsupported schema versions fail closed. An error record remains
an error, not a candidate. A valid inspection does not select or qualify a task.

`validate` returns 0 for a real, qualified package, 1 for a structurally consistent but blocked,
unreviewed, or synthetic package, and 2 for malformed input, missing files, or changed hashes.
`plan` returns 0 for a produced planning artifact even when blockers remain; `execution_ready`
is always false. Input errors return 2. All commands print errors on stderr.

The authoritative Archive references are
[eval-export.md](https://github.com/wangjohn/agent-archive/blob/main/dev/specs/eval-export.md),
[export schema](https://github.com/wangjohn/agent-archive/blob/main/schemas/eval-export.schema.json),
and [replay-sessions.md](https://github.com/wangjohn/agent-archive/blob/main/dev/specs/replay-sessions.md).
Export and replay marking are implemented upstream; the older plan's “being added” language is
historical. Export records may finish out of order. Match exact session identity and optional
`revision_id`, preserve the exact export bytes and producing Archive version, and use supported
`agent-archive eval export` commands. For a revision, use the explicit
`SESSION_ID --revision REVISION_ID --detail full --max-bytes 0` form supported by that build.
A normal export has no `revision_id`; preserve its immutable exported bytes instead of assuming
that re-exporting a mutable session yields identical data. An authentication/Keychain failure
requires supported access diagnosis, never reading raw session files around that failure.

## Package contract (pilot.json schema version 1)

A package is an explicit user-authored directory:

```text
package/
  pilot.json
  task/                       # the only directory passed to Harbor
    task.toml
    instruction.md
    environment/              # Dockerfile or pinned docker_image and safe input files
    solution/solve.sh          # oracle only, never installed for a contestant
    tests/test.sh             # verifier only, never installed for a contestant
  private/                    # never passed to the contestant or its image build
    export.jsonl
    start.md
    acceptance.md
    environment.md
    isolation.md
    qualification/
      index.json
      review.json             # absent until direct human approval
      ...actual result/reward/log/inspection/witness/known-bad artifacts...
```

The task directory follows Harbor's layout. A prebuilt `environment.docker_image` pinned as
`IMAGE@sha256:DIGEST` may replace `environment/Dockerfile`. Harbor owns task execution and verifier isolation.
Every declared `docker_image` must be pinned, including when a Dockerfile is also present:
Harbor can prefer the prebuilt image over that Dockerfile.
The manifest must contain the following fields (names and paths below are examples):

```json
{
  "schema_version": 1,
  "task_id": "task-one",
  "kind": "real",
  "source": {
    "export": "private/export.jsonl",
    "session_id": "exact-session-id",
    "archive_version": "exact-producing-version"
  },
  "start": {
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "verification": "private/start.md"
  },
  "instruction": {
    "prompt_index": 0,
    "mode": "literal",
    "later_messages": [
      {"prompt_index": 1, "classification": "clarification", "reason": "why it is a clarification"}
    ]
  },
  "acceptance": "private/acceptance.md",
  "environment": "private/environment.md",
  "isolation": "private/isolation.md",
  "harbor_task_checksum": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "files": {"every/relative-file-except-root-pilot.json": "its-lowercase-sha256"}
}
```

Use `kind: synthetic` for every invented task. IDs use lowercase letters/digits/underscore/hyphen.
Add `source.revision_id` only when that exact native revision UUID is present in the export.
`files` must cover **every** package file except root `pilot.json`, including evidence/review;
any extra file, changed byte, artifact symlink, missing file, traversal, or git metadata path fails
validation. Package roots are resolved first; links within the package are rejected. File hashes
are lowercase SHA256. Manifests, evidence, and review are ordinary local
JSON; duplicate keys and nonfinite numbers are rejected. Do not store secrets in any of them.

For this narrow pilot, qualification requires a full untrimmed export, a supported nonfailed
parser, no replay marker, and a clean hook-recorded `git_head.start` equal to the exact starting
commit. The chosen boundary is the first original prompt (`prompt_index: 0`). The recorded start
verification must document independently checking that the commit exists, obtaining its exact
source, and reproducing the clean initial tree. Local exports do not contain `git_head` and must
never be assigned one. Missing/dirty/unknown starts and later boundaries are **data-blocked**;
this release intentionally does not infer commits or reconstruct initial edits. `files_edited`
is only a list of paths, not edit contents or a working-tree snapshot. A timestamp, branch tip,
current main, historical “done”, or a patch applying cleanly is insufficient evidence.

`literal` requires instruction bytes to equal the original first prompt text. `retrospective`
explicitly labels a newly compiled instruction; human review must distinguish it from literal
replay and verify it reveals no answer. Classify every later prompt once, in order, as
`clarification`, `new_requirement`, or `solution_revealing`, with a reason. Later requirements must
not silently enter literal replay. Keep only context available at the boundary in the contestant
instruction. Final assistant text is never used as evidence that a solution worked.

`acceptance.md` records independently specified observable behavior, relevant requested checks,
and the existing regression suite. `environment.md` records pinned image/dependency versions,
lockfiles and the independent reference solution provenance. `isolation.md` records inspection
of the built environment: no answer-bearing later history/refs, transcripts, oracle solutions,
private graders, live home/checkouts, or host credentials. These documents are required frozen
artifacts, **not mechanically verified proofs**. Human review must inspect them and the real
runtime artifacts. Acceptance tests should permit behaviorally correct alternative patches.

`task.toml` must explicitly set positive `agent.timeout_sec`, `verifier.timeout_sec`,
`environment.cpus`, `memory_mb`, and `storage_mb`; a missing agent timeout must never silently
become unlimited. The offline tool validates these consumed fields, not the whole Harbor schema.
Dependencies should already be baked into the pinned image. Configure model-only network access
for the attempt and no network for the verifier using the installed Harbor contract.

## Freeze and qualification evidence

Compute `package_digest` as SHA256 of canonical JSON (`sort_keys=True`, separators `(',', ':')`)
containing `{"manifest": manifest_without_files, "files": frozen_input_files}`. Frozen input files
are every `files` entry **except** paths beginning `private/qualification/`. This freezes source,
starting state, instruction, environment, solution, acceptance checks and private graders before
any qualification or contestant attempt. Editing any input requires requalification and review.
Source export, start verification, acceptance, environment, isolation, and audit-script input
references must stay outside the excluded qualification directory; the validator rejects them
there. `validate` prints the digest; it is an identity, not a proof of correctness.

After running deterministic qualification in isolated fresh environments, manually assemble
`private/qualification/index.json`. Its `package_digest` must match, and `trials` must contain at
least one `nop`, three `oracle` runs, and one plausible `known_bad`. Every trial has:

```json
{
  "role": "nop",
  "result": "private/qualification/nop/result.json",
  "reward": "private/qualification/nop/reward.json",
  "verifier_log": "private/qualification/nop/verifier.log",
  "docker_inspect": "private/qualification/nop/inspect.json",
  "hostname": "private/qualification/nop/hostname.txt",
  "failure_kind": "behavior"
}
```

Consume actual Harbor 0.24.0 `result.json`, not its process exit status (a job can exit zero with
failed trials). Require trial UUID/name, finished timestamp, completed verifier timing,
`agent_info.name` (`nop` or `oracle`), exact frozen task checksum, `exception_info: null`, and
`verifier_result.rewards` equal to the saved verifier reward artifact. The verifier emits two
metrics: `requested_behavior` is 0 for nop/known-bad and 1 for each oracle;
`regression_suite` is 1 for all, checking existing behavior even in negative controls. For
oracle and known-bad runs, `agent_dir` points to an exact preserved copy of Harbor's agent output
directory, including `oracle.txt` (which can be empty), and agent execution timing must complete.
Harbor 0.24 writes `agent/exit-code.txt` only on a nonzero solver exit. If present it must contain
zero; absence follows the installed successful-exit convention and must not be replaced with a
fabricated zero file. A nonzero solver exit can lack a result exception and mimic behavior failure. Preserve
logs showing which requested behavior failed. Infra/runner exceptions, missing verifier output,
and a failure in setup are never behavior failures. Oracle `failure_kind` is `none`.

A known-bad trial uses Harbor's oracle with an independently prepared incomplete/incorrect
solution. Also include `solution` (path to its exact frozen patch/script), `reason` (why this
plausible mistake should fail), and `variant_task_checksum` (its actual task directory checksum).
Do not derive this solution from file-path lists. Grade the same acceptance checks/regressions;
keep all variant inputs/artifacts for human inspection.

Retain an independent `docker inspect` JSON array containing exactly the trial's main container.
Join `Config.Labels["com.docker.compose.project"]` to the installed Harbor 0.24 name transform of
`trial_name + "__env"` (lowercase, prepend `0` if first character is not alphanumeric, replace
characters outside `[a-z0-9_-]` with `-`); compose service must be `main`. Require a distinct full
container `Id` and `Created`, plus a verifier-recorded hostname matching `Config.Hostname` and
its ID prefix. When Harbor shares an egress sidecar network namespace, Docker inherits the
sidecar hostname instead. In that case include `sidecar_inspect`: exactly one raw sidecar
inspection, with the same compose project and service `harbor-docker-egress-control-sidecar`.
Require main `HostConfig.NetworkMode` equal to `container:` plus the sidecar ID, and the
hostname prefix to match that ID. A result UUID alone does not prove a fresh sandbox. Capture this evidence while
the container exists; `--environment-kwarg keep_containers=true` preserves stopped containers in
0.24.0. The older `--no-delete` flag alone does not retain containers. Stop/delete only run-owned
resources after collecting evidence. This command never invokes Docker or cleans anything up.

`harbor_task_checksum` is Harbor 0.24's actual legacy 64-hex task directory checksum, preserved
from the exact qualified task. Its algorithm is distinct from this package's input digest and
newer Harbor task-lock digests; never substitute one for another. The validator cross-checks
recorded checksums and frozen files but does not recompute Harbor's legacy checksum or attest
that a runner executed them. Preserve trial locks and source snapshots alongside raw results;
human review must reconcile those identities before approval. Empty/self-attested `passed: true`
gate records cannot qualify. Artifact consistency checks cannot establish authenticity of
fabricated logs or approve task intent/isolation on a human's behalf.

An isolation document or a configured network mode alone cannot pass the hard leak/network
gate. Require `private/qualification/isolation.json`, bound to the same input `package_digest`
and one recorded nop `trial_id`/`container_id`, with `stage: before_agent_or_verifier_injection`.
Its `script` references the exact audit script frozen among package inputs (outside the
qualification directory). `network_probes` references raw JSON probe output: a nonempty array
of `{target, protocol, success, error_type, error}` objects. Observe HTTP, HTTPS, and direct-IP
TLS requests (`protocol` values `http`, `https`, `direct_ip_tls`). Every forbidden request must
fail with an actual recorded network error and `success: false`; successful/invalid output
blocks qualification. A TCP `connect_ex` result alone is inconclusive because Harbor can
transparently redirect a successful TCP connection to a local policy proxy that then denies
the application request. Preserve raw audit output and policy observations to interpret errors;
a boolean declaration alone is insufficient. `filesystem_scan`
references raw JSON with array fields `later_git_refs`, `answer_files`, `transcript_files`,
`private_grader_files`, and `live_host_mounts`; every finding blocks qualification. Preserve
actual observed scans at the contestant boundary before oracle/verifier injection, not after
hidden material has intentionally been mounted for grading. The audit script and human review
must establish complete target/path coverage; these checks cannot authenticate fake results or
prove that an inadequately scoped scan was exhaustive. Missing or failed audit is a hard
qualification blocker even if a review file says approved.

States are `synthetic` (always, for invented data), `data-blocked`, `draft` (qualification
incomplete/inconsistent), `unreviewed` (recorded evidence consistent; human gate pending), and
`qualified` (real package with consistent evidence and bound recorded human approval).

Only after **actual direct user approval**, record `review.json` with `decision: approved`,
`authority: direct_user_approval`, `reviewer`, `reviewed_at`, `package_digest`, and `evidence_digest`.
Never create approval on the user's behalf without that approval. `evidence_digest` is canonical
JSON SHA256 of a relative-path-to-file-SHA256 map of every file below `private/qualification/`
except its root `review.json`; it binds all raw outputs and logs, not just the index. Recompute
the outer `files` map after adding evidence/review. Neither validation nor a plan writes files
or invents approval. Synthetic unit tests that simulate approval remain synthetic fixtures.

## Explicit comparison plan

`run.json` selects exactly two contestants, pinned Harbor `0.24.0`, and explicit run limits:

```json
{
  "harbor_version": "0.24.0",
  "incremental_usd_cap": null,
  "limits": {
    "timeout_sec": 600, "verifier_timeout_sec": 120,
    "cpus": 2, "memory_mb": 2048, "storage_mb": 10240, "concurrency": 1
  },
  "contestants": [
    {
      "id": "candidate-a", "agent": "codex", "agent_version": "EXACT_VERSION",
      "model": "PROVIDER/MODEL", "effort": "high", "config_file": "candidate-a.json",
      "config_sha256": "SHA256_OF_HARBOR_CONFIG",
      "estimate": {
        "input_tokens": 20000, "output_tokens": 5000,
        "input_usd_per_million": 0, "output_usd_per_million": 0
      }
    },
    {
      "id": "candidate-b", "agent": "claude-code", "agent_version": "EXACT_VERSION",
      "model": "PROVIDER/MODEL", "effort": "high", "config_file": "candidate-b.json",
      "config_sha256": "SHA256_OF_HARBOR_CONFIG",
      "estimate": {
        "input_tokens": 20000, "output_tokens": 5000,
        "input_usd_per_million": 0, "output_usd_per_million": 0
      }
    }
  ]
}
```

The example is deliberately incomplete: choose real installed versions, models, whole Harbor
job config files (JSON only, relative to run.json), their actual SHA256, current token price
estimates, and an explicitly approved incremental provider/cloud spending cap before execution.
Zero prices are appropriate only when an already authorized plan truly has no incremental
provider charge; they do not imply authorization or unlimited subscription capacity. The
planner verifies actual config file bytes and flags task time/resource limits that disagree
with the selected limits. Preserve instruction files/skills/settings/MCP configuration and
version information with that whole configuration; verify no mutable dependency is hidden
behind the job config hash. Plan rows include that hash and configuration identity.

Each whole job config must contain exactly one `agents` entry. Its `name` and `model_name`, and
its `kwargs.version` and `kwargs.reasoning_effort`, must exactly match the contestant declaration.
Custom `import_path` agents, simulated users, and `source_jobs` are outside this pilot. Both
contestants may use the same harness with different configurations. The planner reads JSON
using the standard library; it does not support YAML or resolve/hash external config assets.
For example, a selected Codex config contains:

```json
{
  "agents": [{
    "name": "codex", "model_name": "PROVIDER/MODEL",
    "kwargs": {"version": "EXACT_VERSION", "reasoning_effort": "high"},
    "skills": [], "mcp_servers": [], "env": {}
  }]
}
```

The output contains `2 * tasks * 3` rows (18 for three tasks, 60 for ten), versions, limits,
concurrency, token/cost estimates, and per-trial Harbor argv recipes. Each recipe requests one
attempt, no retries, and concurrency one; a human scheduler must respect the selected global concurrency.
Trial/job names derive from the contestant/task identities, frozen package/config hashes, and
attempt, avoiding ambiguous hyphen joins and staying within Archive's replay marker bound.
Results go under run.json's private sibling `jobs/`. Inspect recipes before using them. Job
configuration can override task defaults, so check the final Harbor config/lock and container
limits before execution. The planner records limits; it does not enforce provider token/spend
caps. Estimates exclude setup/cloud costs and are not bills. A selected cap is not itself
spending approval. Plans always retain explicit execution/runtime/budget blockers.
Declared storage is not evidence of an enforced disk quota. Verify each limit in the actual
runtime; the pilot's observed Docker CPU/RAM limits do not establish per-trial storage enforcement.

Recipes retain the single frozen agent stanza through `--config`, adding only the replay
environment marker to that stanza with `--agent-env AGENT_ARCHIVE_REPLAY=...`. They deliberately
omit `--agent`, which in Harbor 0.24 replaces the loaded agent stanza and discards its settings.
They use `--env docker`, `--n-attempts 1`, `--n-concurrent 1`, and `--max-retries 0`.
Pinned recipes support installed `codex` and
`claude-code` only. Harbor 0.24's Cursor installer ignores the version kwarg; it cannot be
claimed pinned through that flag. Prebuilt CLI images and post-install version checks need
separate runtime qualification. Verify credentials using the chosen supported provider flow
without putting credentials in manifests/recipes. No contestant trials are launched by this PR.

The official Harbor [task format](https://harborframework.com/docs/task-format) and
[CLI reference](https://harborframework.com/docs/cli) must be checked against the actual pinned
installation. In 0.24.0 the installed task schema default is 1.4 while hosted task docs have shown
1.3; Docker resource fields use `memory_mb`/`storage_mb`; no built-in arbitrary agent network
allowlist from the old v0 example should be assumed. Preserve offline verifier evidence and
model-only egress separately. A Docker context is not isolation if it points at somebody else's
runtime; use run-owned resources and never mount live source/home directories.

Measure **unattended requested-task completion** first. Trial rows initialize
`unattended_completion` and `clarification_requests` to unknown (`null`), not false/zero.
Capture whether/how often an agent asks for clarification independently of pass/fail. This
single-turn benchmark does not measure human time saved. Report unit/synthetic checks, actual
real-session qualification, and real contestant attempts as different evidence categories.
