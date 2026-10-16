"""Offline contract tests. All exports, reviews, and runner artifacts are fabricated."""

import json
from pathlib import Path
from typing import cast

import pytest

from agent_backtest.cli import main
from agent_backtest.pilot import (
    Invalid,
    Object,
    file_hash,
    inspect_export,
    obj,
    plan_run,
    read_json,
    validate_package,
)
from tests.pilot_fixtures import add_evidence, freeze, make_package, run_config, write_json


def test_synthetic_never_counts_as_qualified(tmp_path: Path) -> None:
    manifest = make_package(tmp_path)
    add_evidence(tmp_path, manifest, approve=True)
    assert validate_package(tmp_path)["state"] == "synthetic"


def test_recorded_evidence_requires_human_review_and_binds_all_inputs(tmp_path: Path) -> None:
    manifest = make_package(tmp_path, kind="real")
    assert validate_package(tmp_path)["state"] == "draft"
    add_evidence(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "unreviewed"
    add_evidence(tmp_path, manifest, approve=True)
    assert validate_package(tmp_path)["state"] == "qualified"
    # Editing any grader invalidates the freeze first and old evidence after re-freezing.
    (tmp_path / "task/tests/test.sh").write_text("#!/bin/sh\nexit 0\n")
    with pytest.raises(Invalid, match="frozen artifact changed"):
        validate_package(tmp_path)
    freeze(tmp_path, manifest)
    result = validate_package(tmp_path)
    assert result["state"] == "draft"
    assert any("different frozen inputs" in str(b) for b in cast(list[object], result["blockers"]))


@pytest.mark.parametrize(
    "change", ["local", "missing", "wrong", "dirty", "unknown", "truncated", "replay"]
)
def test_insufficient_source_cannot_qualify(tmp_path: Path, change: str) -> None:
    manifest = make_package(tmp_path, kind="real")
    export_path = tmp_path / "private/export.jsonl"
    record = read_json(export_path)
    if change == "local":
        record["source"] = "local"
        del record["git_head"]
    elif change == "missing":
        del record["git_head"]
    elif change == "wrong":
        obj(obj(record["git_head"], "head")["start"], "start")["sha"] = "c" * 40
    elif change == "dirty":
        obj(obj(record["git_head"], "head")["start"], "start")["dirty"] = True
    elif change == "unknown":
        del obj(obj(record["git_head"], "head")["start"], "start")["dirty"]
    elif change == "truncated":
        cast(list[Object], record["prompts"])[0]["truncated"] = True
    else:
        record["replay"] = {"run_id": "invented-replay"}
    write_json(export_path, record)
    # The source is JSONL: restore its single line after pretty-printing above.
    export_path.write_text(json.dumps(record) + "\n")
    freeze(tmp_path, manifest)
    add_evidence(tmp_path, manifest, approve=True)
    assert validate_package(tmp_path)["state"] == "data-blocked"


@pytest.mark.parametrize(
    "change",
    ["infrastructure", "nop_pass", "regression", "freshness", "join", "reward", "checksum"],
)
def test_rejects_misleading_qualification(tmp_path: Path, change: str) -> None:
    manifest = make_package(tmp_path, kind="real")
    add_evidence(tmp_path, manifest, approve=True)
    result_path = tmp_path / "private/qualification/1/result.json"
    result = read_json(result_path)
    if change == "infrastructure":
        result["exception_info"] = {"exception_type": "EnvironmentStartTimeout"}
    elif change in {"nop_pass", "regression", "reward"}:
        reward_path = tmp_path / "private/qualification/1/reward.json"
        rewards = read_json(reward_path)
        rewards["requested_behavior" if change != "regression" else "regression_suite"] = (
            1 if change != "regression" else 0
        )
        write_json(reward_path, rewards)
        if change != "reward":
            obj(result["verifier_result"], "verifier")["rewards"] = rewards
    elif change == "freshness":
        inspection = (tmp_path / "private/qualification/1/inspect.json").read_text()
        (tmp_path / "private/qualification/2/inspect.json").write_text(inspection)
    elif change == "join":
        result["trial_name"] = "some-other-trial"
    else:
        result["task_checksum"] = "f" * 64
    write_json(result_path, result)
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "draft"


def test_missing_trials_and_self_attested_pass_do_not_qualify(tmp_path: Path) -> None:
    manifest = make_package(tmp_path, kind="real")
    write_json(tmp_path / "private/qualification/index.json", {"passed": True, "trials": []})
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "draft"


def test_later_messages_cannot_silently_enter_literal_prompt(tmp_path: Path) -> None:
    manifest = make_package(tmp_path, kind="real")
    (tmp_path / "task/instruction.md").write_text(
        "Fix empty input. Keep nonempty behavior unchanged."
    )
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "data-blocked"
    obj(manifest["instruction"], "instruction")["mode"] = "retrospective"
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "draft"
    obj(manifest["instruction"], "instruction")["later_messages"] = []
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "data-blocked"


def test_additive_export_fields_and_unknown_error_codes_are_accepted(tmp_path: Path) -> None:
    make_package(tmp_path)
    path = tmp_path / "private/export.jsonl"
    record = read_json(path)
    record.update({"future_field": {"opaque": True}, "git_activity": [{"kind": "future_kind"}]})
    obj(record["counts"], "counts")["future_count_metadata"] = {"opaque": True}
    path.write_text(
        json.dumps(record)
        + "\n"
        + json.dumps(
            {
                "schema_version": 1,
                "record": "error",
                "input": "invented",
                "error": {"code": "future_code", "message": "private-text"},
            }
        )
        + "\n"
    )
    report = inspect_export(path)
    serialized = json.dumps(report)
    assert "future_code" in serialized
    assert "private-text" not in serialized
    assert "Fix count_items" not in serialized
    assert len(cast(list[object], report["records"])) == 2


@pytest.mark.parametrize(
    "text",
    [
        '{"schema_version":2,"record":"session"}',
        '{"schema_version":1,"schema_version":1}',
        "NaN",
        "\n",
        "{}",
    ],
)
def test_invalid_export_fails_cleanly(tmp_path: Path, text: str) -> None:
    path = tmp_path / "export.jsonl"
    path.write_text(text)
    with pytest.raises(Invalid):
        inspect_export(path)


def test_untracked_file_symlink_and_escape_are_rejected(tmp_path: Path) -> None:
    manifest = make_package(tmp_path)
    (tmp_path / "unexpected").write_text("answer-bearing file")
    with pytest.raises(Invalid, match="cover every"):
        validate_package(tmp_path)
    (tmp_path / "unexpected").unlink()
    (tmp_path / "link").symlink_to(tmp_path / "task/instruction.md")
    with pytest.raises(Invalid, match="symlink"):
        validate_package(tmp_path)
    (tmp_path / "link").unlink()
    obj(manifest["files"], "files")["../elsewhere"] = "a" * 64
    freeze(tmp_path, manifest)
    obj(manifest["source"], "source")["export"] = "../elsewhere"
    freeze(tmp_path, manifest)
    with pytest.raises(Invalid, match="stay inside"):
        validate_package(tmp_path)


def test_matrix_is_two_by_three_by_three_and_never_runs(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("counter", "range", "slug")]
    for root in roots:
        make_package(root, root.name)
    config = tmp_path / "run.json"
    run_config(config)
    plan = plan_run(config, roots)
    assert plan["trial_count"] == 18
    assert plan["execution_ready"] is False
    assert obj(plan["estimate"], "estimate")["incremental_usd"] == pytest.approx(0.09)
    trials = cast(list[Object], plan["trials"])
    assert len({t["trial_id"] for t in trials}) == 18
    assert all(
        t["unattended_completion"] is None and t["clarification_requests"] is None for t in trials
    )
    assert any("cap" in str(b) for b in cast(list[object], plan["blockers"]))


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_package(tmp_path)
    assert main(["pilot", "inspect-export", str(tmp_path / "private/export.jsonl")]) == 0
    assert "prompt_count" in capsys.readouterr().out
    assert main(["pilot", "validate", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["state"] == "synthetic"
    assert main(["pilot", "inspect-export", str(tmp_path / "missing")]) == 2
    assert "backtest:" in capsys.readouterr().err


def test_nonzero_oracle_exit_is_not_behavioral_success(tmp_path: Path) -> None:
    manifest = make_package(tmp_path, kind="real")
    add_evidence(tmp_path, manifest, approve=True)
    (tmp_path / "private/qualification/2/agent/exit-code.txt").write_text("17")
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "draft"


def test_pinned_prebuilt_image_can_replace_dockerfile(tmp_path: Path) -> None:
    manifest = make_package(tmp_path)
    (tmp_path / "task/environment/Dockerfile").unlink()
    config_path = tmp_path / "task/task.toml"
    config_path.write_text(
        config_path.read_text() + 'docker_image = "python@sha256:' + "e" * 64 + '"\n'
    )
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "synthetic"
    config_path.write_text(config_path.read_text().replace("@sha256:" + "e" * 64, ":latest"))
    freeze(tmp_path, manifest)
    with pytest.raises(Invalid, match="immutable"):
        validate_package(tmp_path)


def test_sidecar_hostname_namespace_is_joined_to_main(tmp_path: Path) -> None:
    manifest = make_package(tmp_path, kind="real")
    add_evidence(tmp_path, manifest)
    base = tmp_path / "private/qualification/1"
    original = obj(
        cast(list[Object], json.loads((base / "inspect.json").read_text()))[0], "inspect"
    )
    main_config = obj(original["Config"], "Config")
    sidecar_id = "d" * 64
    main_config["Hostname"] = sidecar_id[:12]
    original["HostConfig"] = {"NetworkMode": "container:" + sidecar_id}
    write_json(base / "inspect.json", [original])
    (base / "hostname.txt").write_text(sidecar_id[:12] + "\n")
    write_json(
        base / "sidecar.json",
        [
            {
                "Id": sidecar_id,
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "invented-1__env",
                        "com.docker.compose.service": "harbor-docker-egress-control-sidecar",
                    }
                },
            }
        ],
    )
    index = read_json(tmp_path / "private/qualification/index.json")
    cast(list[Object], index["trials"])[0]["sidecar_inspect"] = (
        "private/qualification/1/sidecar.json"
    )
    write_json(tmp_path / "private/qualification/index.json", index)
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "unreviewed"
    original["HostConfig"] = {"NetworkMode": "container:" + "e" * 64}
    write_json(base / "inspect.json", [original])
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "draft"


def test_plan_rejects_changed_contestant_config_and_flags_resource_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "task"
    manifest = make_package(root)
    config_path = tmp_path / "run.json"
    run_config(config_path)
    (tmp_path / "candidate-a.json").write_text('{"changed":true}')
    with pytest.raises(Invalid, match="configuration differs"):
        plan_run(config_path, [root])
    run_config(config_path)
    task_config = root / "task/task.toml"
    task_config.write_text(
        task_config.read_text().replace("timeout_sec = 300", "timeout_sec = 900")
    )
    freeze(root, manifest)
    result = plan_run(config_path, [root])
    assert any("agent.timeout_sec" in str(b) for b in cast(list[object], result["blockers"]))


@pytest.mark.parametrize("failure", ["missing", "connection", "leak", "binding", "stage"])
def test_human_review_cannot_override_failed_isolation(tmp_path: Path, failure: str) -> None:
    manifest = make_package(tmp_path, kind="real")
    add_evidence(tmp_path, manifest, approve=True)
    audit_path = tmp_path / "private/qualification/isolation.json"
    if failure == "missing":
        audit_path.unlink()
    elif failure == "connection":
        write_json(
            tmp_path / "private/qualification/network.json",
            [
                {
                    "target": "invented.invalid:443",
                    "protocol": "https",
                    "success": True,
                    "status": 200,
                }
            ],
        )
    elif failure == "leak":
        path = tmp_path / "private/qualification/scan.json"
        scan = read_json(path)
        scan["later_git_refs"] = ["refs/heads/answer"]
        write_json(path, scan)
    else:
        audit = read_json(audit_path)
        audit["container_id" if failure == "binding" else "stage"] = "wrong"
        write_json(audit_path, audit)
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "draft"


@pytest.mark.parametrize("field", ["acceptance", "environment", "isolation", "start"])
def test_inputs_cannot_hide_from_freeze_in_qualification(tmp_path: Path, field: str) -> None:
    manifest = make_package(tmp_path, kind="real")
    destination = "private/qualification/changed-input.md"
    write_json(tmp_path / destination, {"invented_input": "before qualification"})
    if field == "start":
        obj(manifest["start"], "start")["verification"] = destination
    else:
        manifest[field] = destination
    freeze(tmp_path, manifest)
    add_evidence(tmp_path, manifest)
    write_json(tmp_path / destination, {"invented_input": "changed after qualification"})
    freeze(tmp_path, manifest)
    # Re-freezing an edited semantic input must never leave old qualification usable.
    with pytest.raises(Invalid, match="frozen input"):
        validate_package(tmp_path)


def test_present_dockerfile_does_not_make_mutable_prebuilt_image_safe(tmp_path: Path) -> None:
    manifest = make_package(tmp_path)
    task_config = tmp_path / "task/task.toml"
    task_config.write_text(task_config.read_text() + 'docker_image = "python:latest"\n')
    freeze(tmp_path, manifest)
    with pytest.raises(Invalid, match="immutable"):
        validate_package(tmp_path)


def test_overflowing_json_number_is_rejected_even_in_additive_field(tmp_path: Path) -> None:
    make_package(tmp_path)
    path = tmp_path / "private/export.jsonl"
    record = read_json(path)
    text = json.dumps(record).removesuffix("}") + ', "future_number": 1e999}'
    path.write_text(text + "\n")
    with pytest.raises(Invalid, match="nonfinite"):
        inspect_export(path)


def test_huge_integer_limit_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = tmp_path / "package"
    make_package(package)
    config_path = tmp_path / "run.json"
    run_config(config_path)
    config = read_json(config_path)
    obj(config["limits"], "limits")["memory_mb"] = 10**500
    write_json(config_path, config)
    assert main(["pilot", "plan", str(config_path), str(package)]) == 2
    assert "finite" in capsys.readouterr().err


def test_literal_instruction_preserves_exact_line_endings(tmp_path: Path) -> None:
    manifest = make_package(tmp_path, kind="real")
    export_path = tmp_path / "private/export.jsonl"
    record = read_json(export_path)
    prompts = cast(list[Object], record["prompts"])
    prompts[0]["text"] = "Fix empty input.\nKeep nonempty input."
    export_path.write_text(json.dumps(record) + "\n")
    instruction = tmp_path / "task/instruction.md"
    instruction.write_bytes(b"Fix empty input.\r\nKeep nonempty input.")
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "data-blocked"
    prompts[0]["text"] = "Fix empty input.\r\nKeep nonempty input."
    export_path.write_text(json.dumps(record) + "\n")
    freeze(tmp_path, manifest)
    assert validate_package(tmp_path)["state"] == "draft"


def test_recipes_preserve_whole_config_and_require_matching_agent_identity(tmp_path: Path) -> None:
    package = tmp_path / "package"
    make_package(package)
    config_path = tmp_path / "run.json"
    run_config(config_path)
    plan = plan_run(config_path, [package])
    for recipe in cast(list[Object], plan["recipes"]):
        argv = cast(list[str], recipe["argv"])
        assert "--agent" not in argv
        assert "--model" not in argv
        assert "--agent-kwarg" not in argv
        assert "--effort" not in argv
        assert "--agent-env" in argv
        assert argv[argv.index("--max-retries") + 1] == "0"
        assert argv[argv.index("--env") + 1] == "docker"
    job_path = tmp_path / "candidate-a.json"
    job = read_json(job_path)
    cast(list[Object], job["agents"])[0]["model_name"] = "invented/other-model"
    write_json(job_path, job)
    config = read_json(config_path)
    cast(list[Object], config["contestants"])[0]["config_sha256"] = file_hash(job_path)
    write_json(config_path, config)
    with pytest.raises(Invalid, match="identity"):
        plan_run(config_path, [package])


@pytest.mark.parametrize("long_names", [False, True])
def test_contestant_and_task_pairs_have_distinct_bounded_trial_ids(
    tmp_path: Path, long_names: bool
) -> None:
    roots = [tmp_path / name for name in ("counter", "b-counter")]
    for root in roots:
        make_package(root, root.name)
    config_path = tmp_path / "run.json"
    run_config(config_path)
    config = read_json(config_path)
    contestants = cast(list[Object], config["contestants"])
    contestants[0]["id"] = "a" * 200 if long_names else "candidate"
    contestants[1]["id"] = "b" * 200 if long_names else "candidate-b"
    write_json(config_path, config)
    plan = plan_run(config_path, roots)
    trials = cast(list[Object], plan["trials"])
    assert len({trial["trial_id"] for trial in trials}) == 12
    assert all(len(cast(str, trial["trial_id"])) <= 128 for trial in trials)


def test_export_revision_uses_documented_uuid_spelling_and_empty_error_input(
    tmp_path: Path,
) -> None:
    make_package(tmp_path)
    path = tmp_path / "private/export.jsonl"
    record = read_json(path)
    record["revision_id"] = "0123456789abcdef0123456789abcdef"
    path.write_text(json.dumps(record) + "\n")
    with pytest.raises(Invalid, match="revision UUID"):
        inspect_export(path)
    record["revision_id"] = "01234567-89ab-cdef-0123-456789abcdef"
    path.write_text(
        json.dumps(record)
        + "\n"
        + json.dumps(
            {
                "schema_version": 1,
                "record": "error",
                "input": "",
                "error": {"code": "not_found", "message": "Invented missing empty input"},
            }
        )
        + "\n"
    )
    assert len(cast(list[Object], inspect_export(path)["records"])) == 2


def test_jsonl_unicode_separator_inside_prompt_is_not_a_record_boundary(tmp_path: Path) -> None:
    make_package(tmp_path)
    path = tmp_path / "private/export.jsonl"
    record = read_json(path)
    cast(list[Object], record["prompts"])[0]["text"] = "Invented first line\u0085same prompt"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    summaries = cast(list[Object], inspect_export(path)["records"])
    assert len(summaries) == 1
    assert summaries[0]["prompt_count"] == 2


def test_same_harness_contestants_keep_distinct_whole_configs(tmp_path: Path) -> None:
    package = tmp_path / "package"
    make_package(package)
    config_path = tmp_path / "run.json"
    run_config(config_path)
    job_path = tmp_path / "candidate-b.json"
    job = read_json(job_path)
    cast(list[Object], job["agents"])[0]["name"] = "codex"
    write_json(job_path, job)
    config = read_json(config_path)
    contestant = cast(list[Object], config["contestants"])[1]
    contestant["agent"] = "codex"
    contestant["config_sha256"] = file_hash(job_path)
    write_json(config_path, config)
    assert plan_run(config_path, [package])["trial_count"] == 6


@pytest.mark.parametrize("path", ["../outside.json", "/invented/outside.json"])
def test_contestant_config_must_stay_inside_run_directory(tmp_path: Path, path: str) -> None:
    package = tmp_path / "package"
    make_package(package)
    config_path = tmp_path / "run.json"
    run_config(config_path)
    config = read_json(config_path)
    cast(list[Object], config["contestants"])[0]["config_file"] = path
    write_json(config_path, config)
    with pytest.raises(Invalid, match="stay inside"):
        plan_run(config_path, [package])


def test_plan_resolves_package_root_like_validate(tmp_path: Path) -> None:
    package = tmp_path / "package"
    make_package(package)
    alias = tmp_path / "alias"
    alias.symlink_to(package, target_is_directory=True)
    config_path = tmp_path / "run.json"
    run_config(config_path)
    assert validate_package(alias)["state"] == "synthetic"
    assert plan_run(config_path, [alias])["trial_count"] == 6
