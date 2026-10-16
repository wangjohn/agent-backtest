"""Offline checks for explicitly authored M1 packages; never executes package content."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from pathlib import Path
from typing import cast
from uuid import UUID

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
type Object = dict[str, Json]

SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


class Invalid(ValueError):
    """Malformed or inconsistent input, rather than an unmet pilot gate."""


def obj(value: Json, label: str) -> Object:
    if not isinstance(value, dict):
        raise Invalid(f"{label}: expected object")
    return value


def items(value: Json, label: str) -> list[Json]:
    if not isinstance(value, list):
        raise Invalid(f"{label}: expected array")
    return value


def string(value: Json, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f"{label}: expected nonempty string")
    return value


def finite_number(value: Json, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid(f"{label}: expected finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise Invalid(f"{label}: number exceeds finite supported range") from exc
    if not math.isfinite(number):
        raise Invalid(f"{label}: expected finite number")
    return number


def positive(value: Json, label: str) -> float:
    number = finite_number(value, label)
    if number <= 0:
        raise Invalid(f"{label}: expected positive finite number")
    return number


def _pairs(pairs: list[tuple[str, Json]]) -> Object:
    result: Object = {}
    for key, value in pairs:
        if key in result:
            raise Invalid("duplicate JSON key")
        result[key] = value
    return result


def parse_json(text: str) -> Json:
    def reject_constant(_: str) -> None:
        raise Invalid("nonfinite JSON number")

    def parse_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise Invalid("nonfinite JSON number")
        return number

    return cast(
        Json,
        json.loads(
            text, object_pairs_hook=_pairs, parse_constant=reject_constant, parse_float=parse_float
        ),
    )


def read_json(path: Path) -> Object:
    return obj(parse_json(path.read_text()), "JSON document")


def digest(value: Json) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained(root: Path, name: Json, *, allow_empty: bool = False) -> Path:
    text = string(name, "artifact path")
    path = Path(text)
    if path.is_absolute() or any(part in {"..", ".git"} for part in path.parts):
        raise Invalid("artifact paths must stay inside the package, without git metadata")
    target = root / path
    if any(p.is_symlink() for p in [target, *target.parents] if p != root.parent):
        raise Invalid("symlink artifacts are not supported")
    if not target.is_file() or not target.resolve().is_relative_to(root.resolve()):
        raise Invalid("missing artifact or artifact outside package")
    if not allow_empty and target.stat().st_size == 0:
        raise Invalid("empty evidence artifact")
    return target


def frozen_input(root: Path, name: Json) -> Path:
    path = contained(root, name)
    if path.is_relative_to(root / "private/qualification"):
        raise Invalid("frozen input must stay outside private/qualification")
    return path


def export_record(record: Object) -> Object:
    """Validate the v1 fields consumed here, preserving additive upstream fields.

    This is deliberately not a replacement for the complete upstream JSON Schema.
    Unknown error/gap/event codes are opaque data. No native transcript is accepted.
    """
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise Invalid("unsupported export schema_version (supported: 1)")
    if record.get("record") == "error":
        if not isinstance(record.get("input"), str):
            raise Invalid("error input must be a string")
        error = obj(record.get("error"), "export error")
        code = string(error.get("code"), "error code")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", code):
            raise Invalid("invalid export error code")
        if not isinstance(error.get("message"), str):
            raise Invalid("invalid export error message")
        return record
    if record.get("record") != "session":
        raise Invalid("expected an Agent Archive session or error record")
    if record.get("source") not in ("archive", "local"):
        raise Invalid("unsupported export source")
    if record.get("detail") not in ("metadata", "full"):
        raise Invalid("unsupported export detail")
    string(record.get("session_id"), "session_id")
    if "revision_id" in record and not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
        string(record["revision_id"], "revision_id"),
    ):
        raise Invalid("revision_id must be an exact native revision UUID")
    string(obj(record.get("harness"), "harness").get("name"), "harness.name")
    obj(record.get("project"), "project")
    parser = obj(record.get("parser"), "parser")
    for name in ("name", "version", "status"):
        if not isinstance(parser.get(name), str):
            raise Invalid(f"invalid parser.{name}")
    if not isinstance(record.get("filter_version"), str):
        raise Invalid("invalid filter_version")
    counts = obj(record.get("counts"), "counts")
    for key in (
        "turns",
        "messages",
        "tool_calls",
        "tool_results",
        "user_shell_commands",
        "compactions",
        "explicit_feedback",
        "files_touched",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
    ):
        if key not in counts:
            continue
        value = counts[key]
        if type(value) is not int or value < 0:
            raise Invalid("counts must be nonnegative integers")
    if record["source"] == "local" and any(
        key in record for key in ("git_head", "replay", "feedback", "machine_id", "captured_at")
    ):
        raise Invalid("local exports cannot supply archive-only provenance")
    if record["source"] == "archive" and (
        "transcript_path" in record or "root" in obj(record["project"], "project")
    ):
        raise Invalid("archive export contains local-only paths")
    if "git_head" in record:
        head = obj(record["git_head"], "git_head")
        for name in ("start", "last"):
            if name not in head:
                continue
            observation = obj(head[name], "git observation")
            if not SHA.fullmatch(string(observation.get("sha"), "git sha")):
                raise Invalid("git observation requires a full lowercase commit hash")
            string(observation.get("observed_at"), "git observed_at")
            if "dirty" in observation and type(observation["dirty"]) is not bool:
                raise Invalid("git dirty must be boolean")
    if record["detail"] == "full":
        for prompt in items(record.get("prompts"), "prompts"):
            entry = obj(prompt, "prompt")
            if not isinstance(entry.get("text"), str):
                raise Invalid("prompt text must be a string")
            if "truncated" in entry and entry["truncated"] is not True:
                raise Invalid("prompt truncated must be true when present")
        for filename in items(record.get("files_edited", []), "files_edited"):
            string(filename, "edited file")
    elif any(key in record for key in ("prompts", "final_response", "files_edited", "feedback")):
        raise Invalid("metadata exports cannot contain full-detail fields")
    return record


def read_export(path: Path) -> list[Object]:
    records: list[Object] = []
    # JSONL uses LF delimiters. Unicode separators such as NEL are valid inside JSON text.
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines[-1] == "":
        lines.pop()
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            raise Invalid(f"export line {line_no}: blank lines are not JSON records")
        try:
            records.append(export_record(obj(parse_json(line), "export record")))
        except (Invalid, json.JSONDecodeError) as exc:
            raise Invalid(f"export line {line_no}: {exc}") from exc
    if not records:
        raise Invalid("empty export")
    return records


def inspect_export(path: Path) -> Object:
    summaries: list[Json] = []
    for record in read_export(path):
        if record["record"] == "error":
            summaries.append({"record": "error", "code": obj(record["error"], "error")["code"]})
            continue
        head = obj(record.get("git_head", {}), "git_head")
        prompts = items(record.get("prompts", []), "prompts")
        summaries.append(
            {
                "record": "session",
                "session_id": record["session_id"],
                "revision_id": record.get("revision_id"),
                "source": record["source"],
                "detail": record["detail"],
                "recorded_start": head.get("start"),
                "prompt_count": len(prompts),
                "truncated": "trimmed" in record
                or any(obj(p, "prompt").get("truncated") is True for p in prompts),
                "replay": "replay" in record,
            }
        )
    return {"export_sha256": file_hash(path), "records": summaries}


def frozen_files(root: Path, manifest: Object) -> Object:
    files = obj(manifest.get("files"), "files")
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Invalid("symlink artifacts are not supported")
        if path.is_file() and path != root / "pilot.json":
            actual.add(path.relative_to(root).as_posix())
    if actual != set(files):
        raise Invalid("files must cover every package file except root pilot.json")
    for name, expected in files.items():
        if not HASH.fullmatch(string(expected, "file hash")):
            raise Invalid("expected SHA256 artifact hash")
        if file_hash(contained(root, name, allow_empty=True)) != expected:
            raise Invalid(f"frozen artifact changed: {name}")
    return files


def package_digest(manifest: Object, files: Object) -> str:
    """Freeze inputs before qualification; evidence/review cannot hash themselves."""
    return digest(
        {
            "manifest": {k: v for k, v in manifest.items() if k != "files"},
            "files": {k: v for k, v in files.items() if not k.startswith("private/qualification/")},
        }
    )


def _source_gates(root: Path, manifest: Object, blockers: list[Json]) -> None:
    source = obj(manifest.get("source"), "source")
    string(source.get("archive_version"), "source.archive_version")
    source_path = frozen_input(root, source.get("export"))
    records = read_export(source_path)
    matches = [
        r
        for r in records
        if r.get("session_id") == source.get("session_id")
        and r.get("revision_id") == source.get("revision_id")
        and r["record"] == "session"
    ]
    if len(matches) != 1:
        raise Invalid("source must select exactly one exported session and exact optional revision")
    record = matches[0]
    if record["detail"] != "full":
        blockers.append("data: full export required")
        return
    if "replay" in record:
        blockers.append("data: replay sessions are excluded")
    parser = obj(record["parser"], "parser")
    if parser["status"] not in ("complete", "partial"):
        blockers.append("data: unsupported or failed parser status")
    prompts = items(record["prompts"], "prompts")
    if (
        not prompts
        or "trimmed" in record
        or any(obj(p, "prompt").get("truncated") for p in prompts)
    ):
        blockers.append("data: complete untrimmed prompts required")
    boundary = obj(manifest.get("instruction"), "instruction")
    # M1 supports only the first prompt boundary: a later boundary needs an exact new snapshot.
    if boundary.get("prompt_index") != 0 or type(boundary.get("prompt_index")) is not int:
        blockers.append("data: only original first-prompt boundaries are supported")
    mode = boundary.get("mode")
    if mode not in ("literal", "retrospective"):
        raise Invalid("instruction.mode must be literal or retrospective")
    instruction = contained(root, "task/instruction.md").read_bytes().decode("utf-8")
    if mode == "literal" and prompts and instruction != obj(prompts[0], "prompt")["text"]:
        blockers.append("data: literal instruction must exactly match the original prompt")
    later = items(boundary.get("later_messages"), "instruction.later_messages")
    indexes: list[int] = []
    for entry in later:
        message = obj(entry, "later message")
        index = message.get("prompt_index")
        if type(index) is not int:
            raise Invalid("later prompt_index must be an integer")
        indexes.append(index)
        if message.get("classification") not in (
            "clarification",
            "new_requirement",
            "solution_revealing",
        ):
            raise Invalid("later message needs clarification/new_requirement/solution_revealing")
        string(message.get("reason"), "later classification reason")
    if indexes != list(range(1, len(prompts))):
        blockers.append("data: classify every later prompt exactly once in order")
    start = obj(manifest.get("start"), "start")
    commit = string(start.get("commit"), "start.commit")
    if not SHA.fullmatch(commit):
        raise Invalid("start.commit must be an exact full lowercase hash")
    observation = obj(obj(record.get("git_head", {}), "git_head").get("start", {}), "start")
    if observation.get("sha") != commit:
        blockers.append("data: no matching hook-recorded start; never substitute current main")
    if observation.get("dirty") is not False:
        # An exact initial tree cannot be recovered from files_edited (paths only).
        blockers.append(
            "data: clean initial state not recorded; dirty/unknown starts excluded in M1"
        )
    frozen_input(root, start.get("verification"))


def _qualification(root: Path, manifest: Object, package_hash: str, blockers: list[Json]) -> str:
    evidence_path = root / "private/qualification/index.json"
    if not evidence_path.exists():
        blockers.append("qualification: no recorded trials")
        return ""
    evidence = read_json(contained(root, "private/qualification/index.json"))
    if evidence.get("package_digest") != package_hash:
        blockers.append("qualification: evidence belongs to different frozen inputs")
    trials = items(evidence.get("trials"), "qualification.trials")
    roles: list[str] = []
    sandboxes: set[str] = set()
    trial_ids: set[str] = set()
    nop_witnesses: set[tuple[str, str]] = set()
    for raw in trials:
        trial = obj(raw, "qualification trial")
        role = string(trial.get("role"), "qualification role")
        roles.append(role)
        if role not in ("nop", "oracle", "known_bad"):
            raise Invalid("unsupported qualification role")
        if role == "known_bad":
            contained(root, trial.get("solution"))
            string(trial.get("reason"), "known-bad failure rationale")
        # Trial result and reward are actual runner outputs, not a passed=true declaration.
        result = read_json(contained(root, trial.get("result")))
        reward = read_json(contained(root, trial.get("reward")))
        contained(root, trial.get("verifier_log"))
        trial_id = string(result.get("id"), "Harbor trial ID")
        try:
            UUID(trial_id)
        except ValueError as exc:
            raise Invalid("Harbor trial ID must be UUID") from exc
        if trial_id in trial_ids:
            blockers.append("qualification: duplicate Harbor trial IDs")
        trial_ids.add(trial_id)
        string(result.get("finished_at"), "Harbor finished_at")
        verifier = obj(result.get("verifier"), "Harbor verifier timing")
        string(verifier.get("started_at"), "verifier.started_at")
        string(verifier.get("finished_at"), "verifier.finished_at")
        checksum = manifest.get("harbor_task_checksum")
        if role == "known_bad":
            checksum = trial.get("variant_task_checksum")
        if not HASH.fullmatch(string(checksum, "recorded Harbor task checksum")):
            raise Invalid("Harbor task checksum must be SHA256")
        if result.get("task_checksum") != checksum:
            blockers.append("qualification: Harbor task checksum mismatch")
        agent = obj(result.get("agent_info"), "Harbor agent_info")
        if agent.get("name") != ("nop" if role == "nop" else "oracle"):
            blockers.append("qualification: unexpected qualification agent")
        if obj(result.get("verifier_result"), "Harbor verifier_result").get("rewards") != reward:
            blockers.append("qualification: Harbor rewards differ from verifier reward artifact")
        # An independent host inspection and verifier witness are required for freshness.
        inspection = items(
            parse_json(contained(root, trial.get("docker_inspect")).read_text()), "docker inspect"
        )
        if len(inspection) != 1:
            raise Invalid("expected one inspected qualification container")
        container = obj(inspection[0], "inspected container")
        sandbox = string(container.get("Id"), "Docker container ID")
        string(container.get("Created"), "Docker container creation time")
        config = obj(container.get("Config"), "Docker container Config")
        hostname = string(config.get("Hostname"), "Docker container hostname")
        if contained(root, trial.get("hostname")).read_text().strip() != hostname:
            blockers.append("qualification: verifier hostname differs from host witness")
        trial_name = string(result.get("trial_name"), "Harbor trial_name")
        project_name = trial_name.lower() + "__env"
        if not project_name[0].isalnum():
            project_name = "0" + project_name
        project_name = re.sub(r"[^a-z0-9_-]", "-", project_name)
        labels = obj(config.get("Labels"), "Docker labels")
        if (
            labels.get("com.docker.compose.project") != project_name
            or labels.get("com.docker.compose.service") != "main"
        ):
            blockers.append("qualification: inspected container does not bind to Harbor trial")
        if not HASH.fullmatch(sandbox):
            raise Invalid("Docker container ID must be full lowercase hex")
        if not sandbox.startswith(hostname):
            sidecars = items(
                parse_json(contained(root, trial.get("sidecar_inspect")).read_text()),
                "sidecar inspection",
            )
            if len(sidecars) != 1:
                raise Invalid("expected exactly one inspected egress sidecar")
            sidecar = obj(sidecars[0], "egress sidecar")
            sidecar_id = string(sidecar.get("Id"), "egress sidecar ID")
            sidecar_config = obj(sidecar.get("Config"), "sidecar Config")
            sidecar_labels = obj(sidecar_config.get("Labels"), "sidecar Labels")
            host_config = obj(container.get("HostConfig"), "HostConfig")
            if (
                not HASH.fullmatch(sidecar_id)
                or not sidecar_id.startswith(hostname)
                or host_config.get("NetworkMode") != "container:" + sidecar_id
                or sidecar_labels.get("com.docker.compose.project") != project_name
                or sidecar_labels.get("com.docker.compose.service")
                != "harbor-docker-egress-control-sidecar"
            ):
                blockers.append(
                    "qualification: hostname/network namespace sidecar binding mismatch"
                )
        if role != "nop":
            agent_directory = string(trial.get("agent_dir"), "original Harbor agent_dir")
            if not agent_directory.startswith("private/qualification/"):
                raise Invalid("preserve agent outputs under private/qualification")
            oracle_output = contained(root, agent_directory + "/oracle.txt", allow_empty=True)
            exit_code = oracle_output.parent / "exit-code.txt"
            if exit_code.exists() and exit_code.read_text().strip() != "0":
                blockers.append(
                    "qualification: reference/known-bad solver did not exit successfully"
                )
            execution = obj(result.get("agent_execution"), "Harbor agent_execution timing")
            string(execution.get("started_at"), "agent_execution.started_at")
            string(execution.get("finished_at"), "agent_execution.finished_at")
        if sandbox in sandboxes:
            blockers.append("qualification: trials must use distinct fresh sandboxes")
        sandboxes.add(sandbox)
        if role == "nop":
            nop_witnesses.add((trial_id, sandbox))
        if "exception_info" not in result or result["exception_info"] is not None:
            blockers.append(
                "qualification: infrastructure/runner exception is not behavior failure"
            )
        if trial.get("failure_kind") != ("none" if role == "oracle" else "behavior"):
            blockers.append("qualification: expected behavioral failure or clean oracle run")
        expected = 1 if role == "oracle" else 0
        if (
            type(reward.get("requested_behavior")) not in {int, float}
            or reward.get("requested_behavior") != expected
        ):
            blockers.append("qualification: requested-behavior reward does not discriminate")
        if reward.get("regression_suite") != 1 or type(reward.get("regression_suite")) is bool:
            blockers.append("qualification: existing regression suite must pass")
    if roles.count("nop") < 1 or roles.count("oracle") < 3 or roles.count("known_bad") < 1:
        blockers.append("qualification: need nop, three fresh oracle runs, and known-bad evidence")
    isolation_path = root / "private/qualification/isolation.json"
    if not isolation_path.exists():
        blockers.append("qualification: observed isolation audit missing")
    else:
        audit = read_json(contained(root, "private/qualification/isolation.json"))
        if (
            audit.get("package_digest") != package_hash
            or (
                string(audit.get("trial_id"), "isolation trial_id"),
                string(audit.get("container_id"), "isolation container_id"),
            )
            not in nop_witnesses
        ):
            blockers.append("qualification: isolation audit does not bind to frozen nop sandbox")
        if audit.get("stage") != "before_agent_or_verifier_injection":
            blockers.append("qualification: isolation must be observed at contestant boundary")
        frozen_input(root, audit.get("script"))
        probes = items(
            parse_json(contained(root, audit.get("network_probes")).read_text()), "network probes"
        )
        protocols: set[str] = set()
        for raw_probe in probes:
            probe = obj(raw_probe, "network probe")
            string(probe.get("target"), "network probe target")
            protocols.add(string(probe.get("protocol"), "network probe protocol"))
            # A transparent policy proxy can accept TCP before denying the HTTP/TLS request.
            if (
                probe.get("success") is not False
                or probe.get("error_type")
                not in (
                    "URLError",
                    "RemoteDisconnected",
                    "SSLEOFError",
                    "ConnectionResetError",
                    "ConnectionRefusedError",
                    "TimeoutError",
                    "PermissionError",
                )
                or not isinstance(probe.get("error"), str)
                or not probe["error"]
            ):
                blockers.append("qualification: forbidden HTTP/TLS request was not observed denied")
        if not {"http", "https", "direct_ip_tls"}.issubset(protocols):
            blockers.append("qualification: HTTP, HTTPS and direct-IP TLS denial probes required")
        scans = read_json(contained(root, audit.get("filesystem_scan")))
        for key in (
            "later_git_refs",
            "answer_files",
            "transcript_files",
            "private_grader_files",
            "live_host_mounts",
        ):
            if items(scans.get(key), key):
                blockers.append(f"qualification: isolation scan found {key}")
    return digest(
        {
            p.relative_to(root).as_posix(): file_hash(p)
            for p in (root / "private/qualification").rglob("*")
            if p.is_file() and p != root / "private/qualification/review.json"
        }
    )


def validate_package(root: Path) -> Object:
    root = root.resolve()
    manifest = read_json(root / "pilot.json")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise Invalid("unsupported pilot schema_version")
    task_id = string(manifest.get("task_id"), "task_id")
    if not NAME.fullmatch(task_id):
        raise Invalid("task_id must use lowercase letters/digits/underscore/hyphen")
    if manifest.get("kind") not in ("real", "synthetic"):
        raise Invalid("kind must be real or synthetic")
    files = frozen_files(root, manifest)
    for required in (
        "task/task.toml",
        "task/instruction.md",
        "task/solution/solve.sh",
        "task/tests/test.sh",
    ):
        contained(root, required)
    task_config = obj(
        cast(Json, tomllib.loads(contained(root, "task/task.toml").read_text())), "task.toml"
    )
    environment = obj(task_config.get("environment"), "environment")
    if "docker_image" in environment:
        image = string(environment.get("docker_image"), "environment.docker_image")
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
            raise Invalid("prebuilt Docker images require an immutable SHA256 digest")
    elif not (root / "task/environment/Dockerfile").is_file():
        raise Invalid("task requires an environment Dockerfile or pinned docker_image")
    for section, fields in (
        ("agent", ("timeout_sec",)),
        ("verifier", ("timeout_sec",)),
        ("environment", ("cpus", "memory_mb", "storage_mb")),
    ):
        values = obj(task_config.get(section), section)
        for field in fields:
            positive(values.get(field), f"task {section}.{field}")
    for required in ("acceptance", "environment", "isolation"):
        frozen_input(root, manifest.get(required))
    blockers: list[Json] = []
    _source_gates(root, manifest, blockers)
    package_hash = package_digest(manifest, files)
    evidence_hash = _qualification(root, manifest, package_hash, blockers)
    review_path = root / "private/qualification/review.json"
    reviewed = False
    if review_path.exists():
        review = read_json(contained(root, "private/qualification/review.json"))
        reviewed = (
            review.get("decision") == "approved"
            and review.get("package_digest") == package_hash
            and review.get("evidence_digest") == evidence_hash
            and bool(string(review.get("reviewer"), "human reviewer"))
            and bool(string(review.get("reviewed_at"), "human reviewed_at"))
            and review.get("authority") == "direct_user_approval"
        )
    if not reviewed:
        blockers.append("review: direct human task approval pending or stale")
    if manifest["kind"] == "synthetic":
        state = "synthetic"
    elif any(str(b).startswith("data:") for b in blockers):
        state = "data-blocked"
    elif any(str(b).startswith("qualification:") for b in blockers):
        state = "draft"
    elif not reviewed:
        state = "unreviewed"
    else:
        state = "qualified"
    return {
        "task_id": task_id,
        "kind": manifest["kind"],
        "state": state,
        "package_digest": package_hash,
        "blockers": blockers,
        "qualification": "recorded artifact consistency only; human reviews evidence and isolation",
    }


def plan_run(config_path: Path, roots: list[Path]) -> Object:
    """Produce a reviewable matrix and recipes. This never authorizes or starts jobs."""
    roots = [root.resolve() for root in roots]
    config = read_json(config_path)
    if config.get("harbor_version") != "0.24.0":
        raise Invalid("recipes currently target Harbor 0.24.0 only")
    contestants = items(config.get("contestants"), "contestants")
    if len(contestants) != 2:
        raise Invalid("M1 plans require exactly two contestant configurations")
    limits = obj(config.get("limits"), "limits")
    for key in (
        "timeout_sec",
        "verifier_timeout_sec",
        "cpus",
        "memory_mb",
        "storage_mb",
        "concurrency",
    ):
        positive(limits.get(key), f"limits.{key}")
    if type(limits["concurrency"]) is not int:
        raise Invalid("concurrency must be an integer")
    reports = [validate_package(root) for root in roots]
    limit_blockers: list[Json] = []
    for root, report in zip(roots, reports, strict=True):
        task_config = tomllib.loads(contained(root, "task/task.toml").read_text())
        for section, key, expected in (
            ("agent", "timeout_sec", limits["timeout_sec"]),
            ("verifier", "timeout_sec", limits.get("verifier_timeout_sec")),
            ("environment", "cpus", limits["cpus"]),
            ("environment", "memory_mb", limits["memory_mb"]),
            ("environment", "storage_mb", limits["storage_mb"]),
        ):
            if expected is None or task_config.get(section, {}).get(key) != expected:
                limit_blockers.append(
                    f"task {report['task_id']}: frozen {section}.{key} differs from run limits"
                )
    ids = [string(r["task_id"], "task_id") for r in reports]
    if not roots or len(set(ids)) != len(ids):
        raise Invalid("provide at least one package, without duplicate task IDs")
    names: set[str] = set()
    trials: list[Json] = []
    recipes: list[Json] = []
    total_cost = 0.0
    total_input = 0.0
    total_output = 0.0
    for raw in contestants:
        contestant = obj(raw, "contestant")
        for key in ("id", "agent", "agent_version", "model", "effort", "config_sha256"):
            string(contestant.get(key), f"contestant.{key}")
        name = string(contestant["id"], "contestant.id")
        if not NAME.fullmatch(name) or name in names:
            raise Invalid("contestant IDs must be distinct lowercase identifiers")
        names.add(name)
        if contestant["agent"] not in ("codex", "claude-code"):
            raise Invalid("pinned recipes currently support codex and claude-code only")
        config_file = contained(config_path.resolve().parent, contestant.get("config_file"))
        if file_hash(config_file) != contestant["config_sha256"]:
            raise Invalid("contestant configuration differs from its frozen SHA256")
        if not HASH.fullmatch(string(contestant["config_sha256"], "config_sha256")):
            raise Invalid("config_sha256 must freeze the whole contestant configuration")
        job = read_json(config_file)
        agents = items(job.get("agents"), "Harbor job agents")
        if len(agents) != 1:
            raise Invalid("whole Harbor job config must select exactly one agent")
        agent = obj(agents[0], "Harbor job agent")
        kwargs = obj(agent.get("kwargs"), "Harbor job agent kwargs")
        if (
            agent.get("name") != contestant["agent"]
            or agent.get("model_name") != contestant["model"]
            or agent.get("import_path") is not None
            or kwargs.get("version") != contestant["agent_version"]
            or kwargs.get("reasoning_effort") != contestant["effort"]
        ):
            raise Invalid("whole Harbor config agent identity differs from selected contestant")
        if job.get("user_agent") is not None or job.get("source_jobs"):
            raise Invalid("M1 whole configs must describe fresh single-turn contestant attempts")
        usage = obj(contestant.get("estimate"), "contestant.estimate")
        for key in (
            "input_tokens",
            "output_tokens",
            "input_usd_per_million",
            "output_usd_per_million",
        ):
            value = finite_number(usage.get(key), f"estimate.{key}")
            if value < 0:
                raise Invalid(f"estimate.{key}: expected nonnegative finite number")
        input_tokens = float(cast(int | float, usage["input_tokens"]))
        output_tokens = float(cast(int | float, usage["output_tokens"]))
        cost = (
            input_tokens * float(cast(int | float, usage["input_usd_per_million"]))
            + output_tokens * float(cast(int | float, usage["output_usd_per_million"]))
        ) / 1_000_000
        if not math.isfinite(cost):
            raise Invalid("estimated per-trial cost overflowed")
        for root, report in zip(roots, reports, strict=True):
            for attempt in range(1, 4):
                task_name = string(report["task_id"], "task_id")
                # Unambiguous frozen identities; also stay within Archive's replay ID bound.
                trial_id = "m1-" + digest(
                    [
                        name,
                        task_name,
                        report["package_digest"],
                        contestant["config_sha256"],
                        attempt,
                    ]
                )
                trials.append(
                    {
                        "trial_id": trial_id,
                        "task_id": report["task_id"],
                        "package_digest": report["package_digest"],
                        "contestant": contestant,
                        "attempt": attempt,
                        "limits": limits,
                        "estimated_usd": cost,
                        "status": "planned",
                        "unattended_completion": None,
                        "clarification_requests": None,
                    }
                )
                # argv arrays remain data, not shell text. No part of this module executes them.
                recipes.append(
                    {
                        "trial_id": trial_id,
                        "argv": [
                            "harbor",
                            "run",
                            "--config",
                            str(config_file),
                            "--path",
                            str(root.resolve() / "task"),
                            "--n-attempts",
                            "1",
                            "--n-concurrent",
                            "1",
                            "--max-retries",
                            "0",
                            "--env",
                            "docker",
                            "--job-name",
                            trial_id,
                            "--jobs-dir",
                            str(config_path.resolve().parent / "jobs"),
                            "--agent-env",
                            f"AGENT_ARCHIVE_REPLAY={trial_id}",
                        ],
                        "environment": {"AGENT_ARCHIVE_REPLAY": trial_id},
                    }
                )
                total_cost += cost
                total_input += input_tokens
                total_output += output_tokens
    if not all(math.isfinite(v) for v in (total_cost, total_input, total_output)):
        raise Invalid("estimated run totals overflowed")
    blockers: list[Json] = [
        "Recipes require runtime/provider/budget review; this command only plans.",
        "Verify isolated Docker runtime, provider access, and installed pinned versions.",
        "Apply task resource/time limits and contestant config before running recipes.",
        "Inspect network isolation and images for history, answers, transcripts, and graders.",
        "Token usage is an estimate, not an enforced provider spending limit.",
    ]
    blockers.extend(limit_blockers)
    for report in reports:
        if report["state"] != "qualified":
            blockers.append(f"task {report['task_id']}: {report['state']}")
    cap = config.get("incremental_usd_cap")
    if cap is None:
        blockers.append("Incremental provider/cloud spending cap has not been selected.")
    else:
        positive(cap, "incremental_usd_cap")
        if total_cost > cast(int | float, cap):
            blockers.append("Estimated cost exceeds the selected cap.")
    return {
        "schema_version": 1,
        "execution_ready": False,
        "harbor_version": config["harbor_version"],
        "trial_count": len(trials),
        "tasks": cast(list[Json], reports),
        "trials": trials,
        "recipes": recipes,
        "blockers": blockers,
        "estimate": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "incremental_usd": total_cost,
            "incremental_usd_cap": cap,
            "basis": "user-supplied token and price estimates; excludes setup/cloud costs",
        },
        "measurement": "unattended completion; clarification requests recorded separately",
    }
