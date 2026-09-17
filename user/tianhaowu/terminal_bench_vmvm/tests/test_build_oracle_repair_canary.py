import fcntl
import hashlib
import json
import stat
from collections import Counter
from pathlib import Path

import pytest
from build_oracle_repair_canary import CanaryManifestError, build_canary_manifest, main


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ordered_sha256(slugs: list[str]) -> str:
    return hashlib.sha256("".join(f"{slug}\n" for slug in slugs).encode()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, list[str], list[dict]]:
    oracle = tmp_path / "oracle"
    statuses = oracle / "tasks"
    statuses.mkdir(parents=True)
    (oracle / ".writer.lock").touch()
    slugs = [f"private-task-{index}" for index in range(6)]
    network_semantics = {
        "schema_version": 1,
        "trusted_reference_solution": "public",
        "verifier": "declared",
    }
    identity = {
        "acceptance": {"minimum_pass_rate": 0.9, "minimum_valid": 5},
        "dataset": {},
        "execution": {},
        "images": {},
        "network_semantics": network_semantics,
        "schema_version": 1,
        "selection": {
            "count": len(slugs),
            "limit": None,
            "offset": 0,
            "ordered_task_slugs_sha256": _ordered_sha256(slugs),
            "task_file": {"path": None, "sha256": None},
        },
        "source": {},
    }
    identity_sha256 = _canonical_sha256(identity)
    (oracle / "run_identity.json").write_text(
        json.dumps(
            {
                "identity": identity,
                "run_identity_sha256": identity_sha256,
                "schema_version": 1,
            },
            sort_keys=True,
        )
        + "\n"
    )
    rows = []
    for index, slug in enumerate(slugs):
        valid = index not in {1, 4}
        reason = "valid" if valid else ("invalid" if index == 1 else "error")
        row = {
            "attempts": 1,
            "elapsed_sec": float(index + 1),
            "error": None if valid else f"private-error-{index}",
            "error_type": None if valid else "PrivateFailure",
            "image": f"registry.invalid/private-image-{index}@sha256:" + str(index) * 64,
            "index": index,
            "infrastructure_failures": [],
            "name": f"private-name-{index}",
            "oracle_network_semantics": network_semantics,
            "reason": reason,
            "run_identity_sha256": identity_sha256,
            "slug": slug,
            "valid": valid,
        }
        rows.append(row)
        (statuses / f"{slug}.json").write_text(json.dumps(row, sort_keys=True) + "\n")
    (oracle / "results.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    reasons = Counter(row["reason"] for row in rows)
    passed = sum(row["valid"] for row in rows)
    (oracle / "summary.json").write_text(
        json.dumps(
            {
                "completed": len(rows),
                "finished_at": 1234.5,
                "oracle_network_semantics": network_semantics,
                "pass_rate": passed / len(rows),
                "passed": passed,
                "reasons": dict(reasons),
                "run_identity_sha256": identity_sha256,
                "selected": len(rows),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return oracle, slugs, rows


def test_builds_deterministic_confidential_manifest_and_self_hashed_receipt(tmp_path: Path) -> None:
    oracle, slugs, rows = _fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    task_file = output / "canary.tasks.txt"
    receipt_path = output / "canary.receipt.json"

    summary = build_canary_manifest(
        oracle,
        task_file,
        receipt_path,
        expected_total=6,
        control_count=2,
        seed="fixed-seed",
    )

    selected = task_file.read_text().splitlines()
    assert len(selected) == 4
    assert slugs[1] in selected
    assert slugs[4] in selected
    assert selected == [slug for slug in slugs if slug in set(selected)]
    assert stat.S_IMODE(task_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    receipt = json.loads(receipt_path.read_text())
    assert receipt["receipt_sha256"] == _canonical_sha256(receipt["receipt"])
    assert receipt["receipt"]["counts"] == {
        "controls": 2,
        "nonvalid": 2,
        "oracle_reasons": {"error": 1, "invalid": 1, "valid": 4},
        "selected": 4,
        "source_statuses": 6,
        "source_total": 6,
        "source_valid": 4,
    }
    assert receipt["receipt"]["selection"]["task_file"]["sha256"] == hashlib.sha256(task_file.read_bytes()).hexdigest()
    aggregate_text = receipt_path.read_text() + json.dumps(summary, sort_keys=True)
    private_values = [*slugs]
    private_values.extend(row["name"] for row in rows)
    private_values.extend(row["error"] for row in rows if row["error"] is not None)
    assert not any(value in aggregate_text for value in private_values)

    second_task_file = output / "second.tasks.txt"
    second_receipt = output / "second.receipt.json"
    build_canary_manifest(
        oracle,
        second_task_file,
        second_receipt,
        expected_total=6,
        control_count=2,
        seed="fixed-seed",
    )
    assert second_task_file.read_bytes() == task_file.read_bytes()
    assert second_receipt.read_bytes() == receipt_path.read_bytes()
    assert (
        build_canary_manifest(
            oracle,
            task_file,
            receipt_path,
            expected_total=6,
            control_count=2,
            seed="fixed-seed",
        )["published"]
        is False
    )


def test_cli_stdout_is_aggregate_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    oracle, slugs, rows = _fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()

    assert (
        main(
            [
                str(oracle),
                str(output / "canary.tasks.txt"),
                str(output / "canary.receipt.json"),
                "--expected-total",
                "6",
                "--controls",
                "2",
                "--seed",
                "fixed-seed",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    output_text = captured.out + captured.err
    private_values = [*slugs]
    private_values.extend(row["name"] for row in rows)
    private_values.extend(row["error"] for row in rows if row["error"] is not None)
    assert not any(value in output_text for value in private_values)
    assert set(json.loads(captured.out)) == {
        "control_count",
        "nonvalid_count",
        "published",
        "receipt_sha256",
        "selected_count",
        "source_total",
        "source_valid",
        "task_file_sha256",
    }


def test_cli_failure_is_stable_and_confidential(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    oracle, slugs, rows = _fixture(tmp_path)
    lines = (oracle / "results.jsonl").read_text().splitlines()
    lines[0] = lines[0][:-1] + ', "index": 0}'
    (oracle / "results.jsonl").write_text("\n".join(lines) + "\n")
    output = tmp_path / "output"
    output.mkdir()

    assert (
        main(
            [
                str(oracle),
                str(output / "canary.tasks.txt"),
                str(output / "canary.receipt.json"),
                "--expected-total",
                "6",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "oracle_repair_canary_error:oracle_result_schema_invalid\n"
    private_values = [*slugs]
    private_values.extend(row["name"] for row in rows)
    private_values.extend(row["error"] for row in rows if row["error"] is not None)
    assert not any(value in captured.err for value in private_values)


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("duplicate", "oracle_result_duplicates"),
        ("malformed", "oracle_result_schema_invalid"),
        ("incomplete", "oracle_universe_incomplete"),
    ],
)
def test_rejects_duplicate_malformed_and_incomplete_sources(tmp_path: Path, case: str, error: str) -> None:
    oracle, _, _ = _fixture(tmp_path)
    if case == "duplicate":
        lines = (oracle / "results.jsonl").read_text().splitlines()
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        second["slug"] = first["slug"]
        lines[1] = json.dumps(second, sort_keys=True)
        (oracle / "results.jsonl").write_text("\n".join(lines) + "\n")
    elif case == "malformed":
        lines = (oracle / "results.jsonl").read_text().splitlines()
        lines[0] = lines[0][:-1] + ', "index": 0}'
        (oracle / "results.jsonl").write_text("\n".join(lines) + "\n")

    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(CanaryManifestError, match=f"^{error}$"):
        build_canary_manifest(
            oracle,
            output / "canary.tasks.txt",
            output / "canary.receipt.json",
            expected_total=7 if case == "incomplete" else 6,
            control_count=2,
        )
    assert list(output.iterdir()) == []


def test_rejects_active_oracle_writer_without_publishing(tmp_path: Path) -> None:
    oracle, _, _ = _fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()

    with (oracle / ".writer.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(CanaryManifestError, match="^oracle_writer_active$"):
            build_canary_manifest(
                oracle,
                output / "canary.tasks.txt",
                output / "canary.receipt.json",
                expected_total=6,
                control_count=2,
            )
    assert list(output.iterdir()) == []


def test_rejects_partial_or_changed_output_pair(tmp_path: Path) -> None:
    oracle, _, _ = _fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    task_file = output / "canary.tasks.txt"
    receipt = output / "canary.receipt.json"
    task_file.write_text("unrelated\n")
    task_file.chmod(0o600)

    with pytest.raises(CanaryManifestError, match="^output_pair_incomplete$"):
        build_canary_manifest(
            oracle,
            task_file,
            receipt,
            expected_total=6,
            control_count=2,
        )
    assert task_file.read_text() == "unrelated\n"
    assert not receipt.exists()
