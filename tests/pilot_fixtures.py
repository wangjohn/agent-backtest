"""Wholly invented package/runner artifacts for offline tests; no trial is executed."""

import json
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

from agent_backtest.pilot import Json, Object, digest, file_hash, obj, package_digest


def write_json(path: Path, value: Json) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def freeze(root: Path, manifest: Object) -> None:
    manifest["files"] = {
        p.relative_to(root).as_posix(): file_hash(p)
        for p in root.rglob("*")
        if p.is_file() and p != root / "pilot.json"
    }
    write_json(root / "pilot.json", manifest)


def make_package(root: Path, task_id: str = "counter", kind: str = "synthetic") -> Object:
    """Create a tiny fake package. Changing kind only exercises state logic in tests."""
    files = {
        "task/task.toml": """version = "1.0"
[agent]
timeout_sec = 300
[verifier]
timeout_sec = 60
[environment]
cpus = 1
memory_mb = 512
storage_mb = 1024
""",
        "task/instruction.md": "Fix count_items so an empty list returns zero.",
        "task/environment/Dockerfile": "FROM python:3.12-slim@sha256:" + "a" * 64 + "\n",
        "task/solution/solve.sh": (
            "#!/bin/sh\nprintf 'def count_items(items): return len(items)\\n' > /app/counter.py\n"
        ),
        "task/tests/test.sh": "#!/bin/sh\npython /tests/check_counter.py\n",
        "task/tests/check_counter.py": (
            "from counter import count_items\nassert count_items([]) == 0\n"
        ),
        "private/acceptance.md": "Check empty and nonempty input through count_items.",
        "private/environment.md": "Invented image digest; no actual Docker build was run.",
        "private/isolation.md": "Invented isolation review; fixture only, never qualified.",
        "private/audit.py": "# Invented unit fixture; no probe was executed.\n",
        "private/start.md": "Invented hook start SHA, clean tree, and exact first prompt boundary.",
    }
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    export: Object = {
        "schema_version": 1,
        "record": "session",
        "source": "archive",
        "detail": "full",
        "session_id": "invented-session",
        "harness": {"name": "codex", "version": "invented"},
        "project": {"name": "invented-counter"},
        "parser": {"name": "codex", "version": "invented", "status": "complete"},
        "filter_version": "invented",
        "counts": {"turns": 2, "files_touched": 1},
        "git_head": {
            "start": {"sha": "a" * 40, "dirty": False, "observed_at": "2026-01-01T00:00:00Z"}
        },
        "prompts": [
            {"text": files["task/instruction.md"]},
            {"text": "Keep nonempty behavior unchanged."},
        ],
        "final_response": {"text": "Done (not proof of success).", "source": "transcript"},
        "files_edited": ["counter.py"],
    }
    (root / "private/export.jsonl").write_text(json.dumps(export) + "\n")
    manifest: Object = {
        "schema_version": 1,
        "task_id": task_id,
        "kind": kind,
        "source": {
            "export": "private/export.jsonl",
            "session_id": "invented-session",
            "archive_version": "invented",
        },
        "start": {"commit": "a" * 40, "verification": "private/start.md"},
        "instruction": {
            "prompt_index": 0,
            "mode": "literal",
            "later_messages": [
                {
                    "prompt_index": 1,
                    "classification": "clarification",
                    "reason": "Existing behavior constraint",
                }
            ],
        },
        "acceptance": "private/acceptance.md",
        "environment": "private/environment.md",
        "isolation": "private/isolation.md",
        "harbor_task_checksum": "b" * 64,
    }
    freeze(root, manifest)
    return manifest


def add_evidence(root: Path, manifest: Object, *, approve: bool = False) -> None:
    """Fake outputs model Harbor 0.24's consumed fields. They are NOT execution evidence."""
    core = package_digest(manifest, obj(manifest["files"], "files"))
    trials: list[Json] = []
    for index, role in enumerate(("nop", "oracle", "oracle", "oracle", "known_bad"), 1):
        base = f"private/qualification/{index}"
        trial_name = f"invented-{index}"
        container = f"{index:064x}"
        rewards: Object = {
            "requested_behavior": 1 if role == "oracle" else 0,
            "regression_suite": 1,
        }
        result: Object = {
            "id": str(uuid5(NAMESPACE_DNS, trial_name)),
            "trial_name": trial_name,
            "task_checksum": "c" * 64 if role == "known_bad" else "b" * 64,
            "agent_info": {"name": "nop" if role == "nop" else "oracle", "version": "1.0.0"},
            "verifier_result": {"rewards": rewards},
            "exception_info": None,
            "finished_at": "2026-01-01T00:02:00Z",
            "agent_execution": {
                "started_at": "2026-01-01T00:00:30Z",
                "finished_at": "2026-01-01T00:00:31Z",
            },
            "verifier": {
                "started_at": "2026-01-01T00:01:00Z",
                "finished_at": "2026-01-01T00:02:00Z",
            },
        }
        write_json(root / base / "result.json", result)
        write_json(root / base / "reward.json", rewards)
        write_json(
            root / base / "inspect.json",
            [
                {
                    "Id": container,
                    "Created": "2026-01-01T00:00:00Z",
                    "Config": {
                        "Hostname": container[:12],
                        "Labels": {
                            "com.docker.compose.project": trial_name + "__env",
                            "com.docker.compose.service": "main",
                        },
                    },
                }
            ],
        )
        (root / base / "hostname.txt").write_text(container[:12] + "\n")
        (root / base / "verifier.txt").write_text(
            "Invented checker: empty input and regressions checked.\n"
        )
        (root / base / "agent").mkdir(exist_ok=True)
        (root / base / "agent/oracle.txt").write_text("")
        trial: Object = {
            "role": role,
            "result": base + "/result.json",
            "reward": base + "/reward.json",
            "verifier_log": base + "/verifier.txt",
            "docker_inspect": base + "/inspect.json",
            "hostname": base + "/hostname.txt",
            "failure_kind": "none" if role == "oracle" else "behavior",
            "agent_dir": base + "/agent",
        }
        if role == "known_bad":
            (root / base / "wrong.py").write_text("def count_items(items): return 1\n")
            trial.update(
                {
                    "solution": base + "/wrong.py",
                    "reason": "Always-one fails empty input",
                    "variant_task_checksum": "c" * 64,
                }
            )
        trials.append(trial)
    write_json(
        root / "private/qualification/index.json", {"package_digest": core, "trials": trials}
    )
    write_json(
        root / "private/qualification/network.json",
        [
            {
                "target": "invented.invalid:443",
                "protocol": protocol,
                "success": False,
                "error_type": "SSLEOFError",
                "error": "Invented denied request",
            }
            for protocol in ("http", "https", "direct_ip_tls")
        ],
    )
    write_json(
        root / "private/qualification/scan.json",
        {
            "later_git_refs": [],
            "answer_files": [],
            "transcript_files": [],
            "private_grader_files": [],
            "live_host_mounts": [],
        },
    )
    write_json(
        root / "private/qualification/isolation.json",
        {
            "package_digest": core,
            "trial_id": str(uuid5(NAMESPACE_DNS, "invented-1")),
            "container_id": f"{1:064x}",
            "stage": "before_agent_or_verifier_injection",
            "script": "private/audit.py",
            "network_probes": "private/qualification/network.json",
            "filesystem_scan": "private/qualification/scan.json",
        },
    )
    if approve:
        evidence = digest(
            {
                p.relative_to(root).as_posix(): file_hash(p)
                for p in (root / "private/qualification").rglob("*")
                if p.is_file()
            }
        )
        write_json(
            root / "private/qualification/review.json",
            {
                "decision": "approved",
                "authority": "direct_user_approval",
                "reviewer": "invented-human",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "package_digest": core,
                "evidence_digest": evidence,
            },
        )
    freeze(root, manifest)


def run_config(path: Path) -> None:
    for name, agent in (("candidate-a", "codex"), ("candidate-b", "claude-code")):
        write_json(
            path.parent / (name + ".json"),
            {
                "agents": [
                    {
                        "name": agent,
                        "model_name": "invented/model",
                        "kwargs": {
                            "version": "invented-exact-version",
                            "reasoning_effort": "high",
                            "config": "invented-native-settings",
                        },
                        "skills": ["invented-skill"],
                        "env": {"INVENTED_SETTING": "preserve-me"},
                        "mcp_servers": [],
                    }
                ]
            },
        )
    write_json(
        path,
        {
            "harbor_version": "0.24.0",
            "incremental_usd_cap": None,
            "limits": {
                "timeout_sec": 300,
                "verifier_timeout_sec": 60,
                "cpus": 1,
                "memory_mb": 512,
                "storage_mb": 1024,
                "concurrency": 1,
            },
            "contestants": [
                {
                    "id": name,
                    "agent": agent,
                    "agent_version": "invented-exact-version",
                    "model": "invented/model",
                    "effort": "high",
                    "config_file": name + ".json",
                    "config_sha256": file_hash(path.parent / (name + ".json")),
                    "estimate": {
                        "input_tokens": 1000,
                        "output_tokens": 500,
                        "input_usd_per_million": 2,
                        "output_usd_per_million": 6,
                    },
                }
                for name, agent in (("candidate-a", "codex"), ("candidate-b", "claude-code"))
            ],
        },
    )
