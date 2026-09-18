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


def _fixture(tmp_path: Path, *, source_wheel: bool = False) -> tuple[Path, list[str], list[dict]]:
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
    source_wheel_attestation_sha256 = None
    if source_wheel:
        policy = tmp_path / "source-wheel-policy.json"
        policy.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "allowed_hosts": ["files.example.invalid"],
                    "entries": [
                        {
                            "requirements": ["verifier-helper==1.0"],
                            "image": "registry.invalid/task@sha256:" + "1" * 64,
                            "build_tools": {"pip": "24.3.1", "setuptools": "75.6.0", "wheel": "0.45.1"},
                            "sources": [
                                {
                                    "distribution": "verifier-helper",
                                    "version": "1.0",
                                    "filename": "verifier-helper-1.0.tar.gz",
                                    "url": "https://files.example.invalid/verifier-helper-1.0.tar.gz",
                                    "size": 1,
                                    "sha256": "2" * 64,
                                    "wheel_filename": "verifier_helper-1.0-py3-none-any.whl",
                                    "wheel_size": 1,
                                    "wheel_sha256": "3" * 64,
                                }
                            ],
                            "binary_wheels": [],
                        }
                    ],
                },
                sort_keys=True,
            )
            + "\n"
        )
        policy_sha256 = hashlib.sha256(policy.read_bytes()).hexdigest()
        attestation = {
            "schema_version": 1,
            "policy_sha256": policy_sha256,
            "entries_sha256": _canonical_sha256([]),
            "entries": [],
        }
        attestation_path = oracle / "source_wheel_attestations.json"
        attestation_path.write_text(json.dumps(attestation, sort_keys=True) + "\n")
        attestation_path.chmod(0o400)
        source_wheel_attestation_sha256 = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
        identity["source_wheel_recovery"] = {
            "schema_version": 1,
            "policy": {"path": str(policy.resolve()), "sha256": policy_sha256},
            "attestation": "source_wheel_attestations.json",
            "artifact_download_network": "public-hash-pinned-https",
            "builder_lease_limit": 1,
            "build_network": "no-network",
            "build_isolation": False,
            "target_install": "offline-no-index-no-deps",
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
        if source_wheel:
            row["source_wheel_attestation_sha256s"] = []
        rows.append(row)
        (statuses / f"{slug}.json").write_text(json.dumps(row, sort_keys=True) + "\n")
    (oracle / "results.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    reasons = Counter(row["reason"] for row in rows)
    passed = sum(row["valid"] for row in rows)
    summary = {
        "completed": len(rows),
        "finished_at": 1234.5,
        "oracle_network_semantics": network_semantics,
        "pass_rate": passed / len(rows),
        "passed": passed,
        "reasons": dict(reasons),
        "run_identity_sha256": identity_sha256,
        "selected": len(rows),
    }
    if source_wheel_attestation_sha256 is not None:
        summary["source_wheel_attestation_sha256"] = source_wheel_attestation_sha256
    (oracle / "summary.json").write_text(json.dumps(summary, sort_keys=True) + "\n")
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


def test_builds_canary_manifest_from_source_wheel_enabled_oracle(tmp_path: Path) -> None:
    oracle, _, _ = _fixture(tmp_path, source_wheel=True)
    output = tmp_path / "output"
    output.mkdir()
    receipt_path = output / "canary.receipt.json"

    build_canary_manifest(
        oracle,
        output / "canary.tasks.txt",
        receipt_path,
        expected_total=6,
        control_count=2,
        seed="fixed-seed",
    )

    recovery = json.loads(receipt_path.read_text())["receipt"]["source_oracle"]["source_wheel_recovery"]
    assert (
        recovery["attestation"]["sha256"]
        == hashlib.sha256((oracle / "source_wheel_attestations.json").read_bytes()).hexdigest()
    )


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
