from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1]
PUBLISHER = WORKFLOW / "publish_qwen_recovered_unfiltered_trace_package.sh"
ARCHIVE_VERIFIER = WORKFLOW / "verify_qwen_recovered_trace_archive.py"
PACKAGE_JOB = "2000002"
SOURCE_JOB = "2000000"
POSTRUN_JOB = "2000001"
ARCHIVE_ROOT = "qwen-2499-recovered-unfiltered-108b713af-v6"
ARCHIVE_NAME = f"{ARCHIVE_ROOT}.tar.zst"
TARGET_RELATIVE = "user/tianhaowu/terminal_bench_vmvm/trace_packages/qwen-2499-recovered-unfiltered-108b713af-v6"
PRIVATE_MARKER = "SYNTHETIC_PRIVATE_ARCHIVE_PAYLOAD_MUST_NOT_BE_LOGGED"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


@dataclass
class PublishFixture:
    environment: dict[str, str]
    repository: Path
    remote: Path
    source: Path
    target: Path
    watcher_state: Path


def _fixture(tmp_path: Path) -> PublishFixture:
    if shutil.which("zstd") is None:
        pytest.skip("zstd is required")

    remote = tmp_path / "remote.git"
    repository = tmp_path / "repository"
    subprocess.run(
        ["git", "init", "--bare", "-q", str(remote)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Publisher Test")
    _git(repository, "config", "user.email", "publisher@example.invalid")
    (repository / "seed.txt").write_text("seed\n")
    target_parent = repository / Path(TARGET_RELATIVE).parent
    target_parent.mkdir(parents=True)
    _git(repository, "add", "seed.txt")
    _git(repository, "commit", "-q", "-m", "seed")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-q", "origin", "HEAD:refs/heads/vmvm-sandbox")
    remote_head = _git(repository, "rev-parse", "HEAD")

    source = tmp_path / ARCHIVE_ROOT
    chunks = source / "chunks"
    chunks.mkdir(parents=True, mode=0o700)
    source.chmod(0o700)
    chunks.chmod(0o700)

    member_payloads = {
        "merge_manifest.json": b'{"fixture":"merge"}\n',
        "postrun_receipt-src108b713af-v6.json": b'{"fixture":"postrun"}\n',
        "postrun_worker.sbatch": b"#!/bin/bash\nprintf 'fixture worker\\n'\n",
        "qwen_2499_error_retry_run_certificate.json": b'{"fixture":"retry"}\n',
        "qwen_2499_error_retry_superseding_certificate.json": b'{"fixture":"superseding"}\n',
        "qwen_2499_recovered_results_certificate.json": b'{"fixture":"recovered"}\n',
        "results.jsonl": f'{{"fixture":"{PRIVATE_MARKER}"}}\n'.encode(),
    }
    member_names = [f"{ARCHIVE_ROOT}/{name}" for name in member_payloads]
    archive_tar = tmp_path / "fixture.tar"
    with tarfile.open(archive_tar, "w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload in member_payloads.items():
            info = tarfile.TarInfo(f"{ARCHIVE_ROOT}/{name}")
            info.size = len(payload)
            info.mode = 0o600
            archive.addfile(info, fileobj=io.BytesIO(payload))
    archive_zst = tmp_path / ARCHIVE_NAME
    subprocess.run(
        ["zstd", "-q", "-19", "--long=31", str(archive_tar), "-o", str(archive_zst)],
        check=True,
    )
    chunk_name = f"{ARCHIVE_NAME}.000.part"
    chunk = chunks / chunk_name
    shutil.copyfile(archive_zst, chunk)
    chunk.chmod(0o600)

    digests = {name: _sha256_bytes(payload) for name, payload in member_payloads.items()}
    project_revision = "1" * 40
    packager_sha256 = "2" * 64
    package_worker_payload = b"#!/bin/bash\nprintf 'fixture package worker\\n'\n"
    worker_sha256 = _sha256_bytes(package_worker_payload)
    postrun_worker_sha256 = digests["postrun_worker.sbatch"]
    selection_sha256 = "3" * 64
    previous_sha256 = "4" * 64
    canonical_sha256 = "5" * 64
    postprocessor_revision = "6" * 40
    predecessor_revision = "7" * 40
    archive_members = [
        {
            "name": member_name,
            "bytes": len(member_payloads[member_name.removeprefix(f"{ARCHIVE_ROOT}/")]),
            "sha256": digests[member_name.removeprefix(f"{ARCHIVE_ROOT}/")],
        }
        for member_name in member_names
    ]
    manifest = {
        "schema_version": 1,
        "kind": "qwen-2499-recovered-unfiltered-trajectory-package",
        "state": "ready",
        "package_version": "v6",
        "project_revision": project_revision,
        "packager": {"bytes": 1, "sha256": packager_sha256},
        "package_worker": {"bytes": len(package_worker_payload), "sha256": worker_sha256},
        "coverage": {"canonical_tasks": 2499, "outcomes": {"positive": 1, "zero": 2498, "error": 0}},
        "lineage": {
            "selection_contract_sha256": selection_sha256,
            "previous_package_manifest_sha256": previous_sha256,
            "retry_certificate_sha256": digests["qwen_2499_error_retry_run_certificate.json"],
            "superseding_certificate_sha256": digests["qwen_2499_error_retry_superseding_certificate.json"],
            "recovered_certificate_sha256": digests["qwen_2499_recovered_results_certificate.json"],
            "recovered_merge_manifest_sha256": digests["merge_manifest.json"],
            "postrun_receipt_sha256": digests["postrun_receipt-src108b713af-v6.json"],
            "postrun_worker_sha256": postrun_worker_sha256,
            "postprocessor_revision": postprocessor_revision,
            "predecessor_revision": predecessor_revision,
            "source_job": int(SOURCE_JOB),
            "postrun_job_id": int(POSTRUN_JOB),
            "canonical_task_file_sha256": canonical_sha256,
        },
        "inputs": {
            "results": {
                "bytes": len(member_payloads["results.jsonl"]),
                "sha256": digests["results.jsonl"],
                "rows": 2499,
            },
            "recovered_certificate": {
                "bytes": len(member_payloads["qwen_2499_recovered_results_certificate.json"]),
                "sha256": digests["qwen_2499_recovered_results_certificate.json"],
            },
            "recovered_merge_manifest": {
                "bytes": len(member_payloads["merge_manifest.json"]),
                "sha256": digests["merge_manifest.json"],
            },
            "retry_certificate": {
                "bytes": len(member_payloads["qwen_2499_error_retry_run_certificate.json"]),
                "sha256": digests["qwen_2499_error_retry_run_certificate.json"],
            },
            "superseding_certificate": {
                "bytes": len(member_payloads["qwen_2499_error_retry_superseding_certificate.json"]),
                "sha256": digests["qwen_2499_error_retry_superseding_certificate.json"],
            },
            "postrun_receipt": {
                "bytes": len(member_payloads["postrun_receipt-src108b713af-v6.json"]),
                "sha256": digests["postrun_receipt-src108b713af-v6.json"],
            },
            "postrun_worker": {
                "bytes": len(member_payloads["postrun_worker.sbatch"]),
                "sha256": postrun_worker_sha256,
            },
            "previous_package_manifest": {"bytes": 1, "sha256": previous_sha256},
        },
        "archive": {
            "name": ARCHIVE_NAME,
            "bytes": archive_zst.stat().st_size,
            "sha256": _sha256(archive_zst),
            "compression": "zstd-19-long31",
            "member_count": 7,
            "members": archive_members,
        },
        "chunk_bytes": 95_000_000,
        "chunks": [{"name": chunk_name, "bytes": chunk.stat().st_size, "sha256": _sha256(chunk)}],
    }
    _write_private(source / "manifest.json", json.dumps(manifest, sort_keys=True).encode() + b"\n")
    _write_private(source / "README.md", b"Synthetic package fixture.\n")
    _write_private(source / "SHA256SUMS", f"{_sha256(chunk)}  {chunk_name}\n".encode())

    watcher_state = tmp_path / "watcher.json"
    _write_private(
        watcher_state,
        json.dumps(
            {
                "schema_version": 1,
                "kind": "qwen-recovery-chain-watch",
                "stage": "chain",
                "state": "completed",
                "job_id": int(PACKAGE_JOB),
                "timestamp_utc": "2026-09-25T00:00:00Z",
            },
            separators=(",", ":"),
        ).encode()
        + b"\n",
    )
    jobid_file = tmp_path / "package.jobid"
    _write_private(jobid_file, f"{PACKAGE_JOB}\n".encode())

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sacct = fake_bin / "sacct"
    sacct.write_text("#!/bin/sh\nprintf '%s|COMPLETED|0:0\\n' \"$TEST_PACKAGE_JOB\"\n")
    sacct.chmod(0o755)
    scontrol = fake_bin / "scontrol"
    scontrol.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = show ] && [ "$2" = job ]; then\n'
        "  printf 'JobId=%s JobName=qwen-recovered-package WorkDir=/fixture\\n' \"$4\"\n"
        'elif [ "$1" = write ] && [ "$2" = batch_script ]; then\n'
        '  /bin/cat "$TEST_PACKAGE_WORKER"\n'
        "else\n"
        "  exit 2\n"
        "fi\n"
    )
    scontrol.chmod(0o755)
    package_worker = tmp_path / "package_worker.sbatch"
    package_worker.write_bytes(package_worker_payload)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TEST_PACKAGE_JOB": PACKAGE_JOB,
            "TEST_PACKAGE_WORKER": str(package_worker),
            "QWEN_PUBLISH_REPOSITORY": str(repository),
            "QWEN_PUBLISH_SOURCE": str(source),
            "QWEN_PUBLISH_TARGET_RELATIVE": TARGET_RELATIVE,
            "QWEN_PUBLISH_WATCHER_STATE": str(watcher_state),
            "QWEN_PUBLISH_PACKAGE_JOBID_FILE": str(jobid_file),
            "QWEN_PUBLISH_TRANSACTION_DIR": str(tmp_path / "publication-transaction"),
            "QWEN_PUBLISH_EXPECTED_REMOTE_HEAD": remote_head,
            "QWEN_PUBLISH_EXPECTED_REMOTE_URL": str(remote),
            "QWEN_PUBLISH_EXPECTED_PROJECT_REVISION": project_revision,
            "QWEN_PUBLISH_EXPECTED_PACKAGER_SHA256": packager_sha256,
            "QWEN_PUBLISH_EXPECTED_WORKER_SHA256": worker_sha256,
            "QWEN_PUBLISH_EXPECTED_ARCHIVE_VERIFIER_SHA256": _sha256(ARCHIVE_VERIFIER),
            "QWEN_PUBLISH_EXPECTED_SOURCE_JOB": SOURCE_JOB,
            "QWEN_PUBLISH_EXPECTED_POSTRUN_JOB": POSTRUN_JOB,
            "QWEN_PUBLISH_EXPECTED_POSTRUN_WORKER_SHA256": postrun_worker_sha256,
            "QWEN_PUBLISH_EXPECTED_POSTPROCESSOR_REVISION": postprocessor_revision,
            "QWEN_PUBLISH_EXPECTED_PREDECESSOR_REVISION": predecessor_revision,
            "QWEN_PUBLISH_EXPECTED_SELECTION_CONTRACT_SHA256": selection_sha256,
            "QWEN_PUBLISH_EXPECTED_PREVIOUS_MANIFEST_SHA256": previous_sha256,
            "QWEN_PUBLISH_EXPECTED_CANONICAL_TASK_FILE_SHA256": canonical_sha256,
            "QWEN_PUBLISH_EXPECTED_RESULTS_SHA256": digests["results.jsonl"],
            "QWEN_PUBLISH_EXPECTED_RETRY_CERTIFICATE_SHA256": digests["qwen_2499_error_retry_run_certificate.json"],
            "QWEN_PUBLISH_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256": digests[
                "qwen_2499_error_retry_superseding_certificate.json"
            ],
            "QWEN_PUBLISH_EXPECTED_RECOVERED_CERTIFICATE_SHA256": digests[
                "qwen_2499_recovered_results_certificate.json"
            ],
            "QWEN_PUBLISH_EXPECTED_MERGE_MANIFEST_SHA256": digests["merge_manifest.json"],
            "QWEN_PUBLISH_EXPECTED_POSTRUN_RECEIPT_SHA256": digests["postrun_receipt-src108b713af-v6.json"],
            "QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256": _sha256(source / "manifest.json"),
            "QWEN_PUBLISH_EXPECTED_README_SHA256": _sha256(source / "README.md"),
            "QWEN_PUBLISH_COMMIT_MESSAGE": "Publish recovered Qwen trajectory package",
        }
    )
    return PublishFixture(
        environment=environment,
        repository=repository,
        remote=remote,
        source=source,
        target=repository / TARGET_RELATIVE,
        watcher_state=watcher_state,
    )


def _publish(fixture: PublishFixture) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PUBLISHER), PACKAGE_JOB],
        env=fixture.environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )


def _install_rewritten_tar(fixture: PublishFixture, archive_tar: Path) -> None:
    chunk = next((fixture.source / "chunks").iterdir())
    subprocess.run(
        ["zstd", "-q", "-f", "-19", "--long=31", str(archive_tar), "-o", str(chunk)],
        check=True,
    )
    chunk.chmod(0o600)
    manifest_path = fixture.source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["archive"]["bytes"] = chunk.stat().st_size
    manifest["archive"]["sha256"] = _sha256(chunk)
    manifest["chunks"] = [{"name": chunk.name, "bytes": chunk.stat().st_size, "sha256": _sha256(chunk)}]
    _write_private(manifest_path, json.dumps(manifest, sort_keys=True).encode() + b"\n")
    _write_private(fixture.source / "SHA256SUMS", f"{_sha256(chunk)}  {chunk.name}\n".encode())
    fixture.environment["QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256"] = _sha256(manifest_path)


def _decompress_archive(fixture: PublishFixture, name: str) -> Path:
    chunk = next((fixture.source / "chunks").iterdir())
    archive_tar = fixture.source.parent / name
    subprocess.run(
        ["zstd", "-q", "--long=31", "-dc", str(chunk)],
        check=True,
        stdout=archive_tar.open("wb"),
    )
    return archive_tar


def _rewrite_archive_member(fixture: PublishFixture, member_name: str) -> None:
    archive_tar = _decompress_archive(fixture, "tampered.tar")
    members: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(archive_tar, "r:") as archive:
        for member in archive:
            stream = archive.extractfile(member)
            assert stream is not None
            payload = stream.read()
            if member.name == member_name:
                payload = bytes([payload[0] ^ 1]) + payload[1:]
            members.append((member, payload))
    with tarfile.open(archive_tar, "w", format=tarfile.PAX_FORMAT) as archive:
        for member, payload in members:
            replacement = tarfile.TarInfo(member.name)
            replacement.size = len(payload)
            replacement.mode = member.mode
            replacement.uid = member.uid
            replacement.gid = member.gid
            replacement.mtime = member.mtime
            archive.addfile(replacement, io.BytesIO(payload))
    _install_rewritten_tar(fixture, archive_tar)


def _append_unmanifested_tar_bytes(fixture: PublishFixture, fill: bytes) -> None:
    archive_tar = _decompress_archive(fixture, "trailing.tar")
    with archive_tar.open("ab") as stream:
        stream.write(fill * 10240)
    _install_rewritten_tar(fixture, archive_tar)


def _corrupt_member_padding(fixture: PublishFixture, member_name: str) -> None:
    archive_tar = _decompress_archive(fixture, "member-padding.tar")
    with tarfile.open(archive_tar, "r:") as archive:
        member = archive.getmember(member_name)
        assert member.size % 512
        padding_offset = member.offset_data + member.size
    with archive_tar.open("r+b") as stream:
        stream.seek(padding_offset)
        assert stream.read(1) == b"\0"
        stream.seek(padding_offset)
        stream.write(b"X")
    _install_rewritten_tar(fixture, archive_tar)


def _set_chunk_layout(
    fixture: PublishFixture,
    parts: list[bytes],
    declared_chunk_bytes: int,
    *,
    first_index: int = 0,
) -> None:
    chunks = fixture.source / "chunks"
    for chunk in chunks.iterdir():
        chunk.unlink()
    manifest_path = fixture.source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest_chunks = []
    for offset, payload in enumerate(parts):
        name = f"{ARCHIVE_NAME}.{first_index + offset:03d}.part"
        chunk = chunks / name
        _write_private(chunk, payload)
        manifest_chunks.append({"name": name, "bytes": len(payload), "sha256": _sha256(chunk)})
    manifest["chunk_bytes"] = declared_chunk_bytes
    manifest["chunks"] = manifest_chunks
    _write_private(manifest_path, json.dumps(manifest, sort_keys=True).encode() + b"\n")
    sums = "".join(f"{entry['sha256']}  {entry['name']}\n" for entry in manifest_chunks)
    _write_private(fixture.source / "SHA256SUMS", sums.encode())
    fixture.environment["QWEN_PUBLISH_EXPECTED_CHUNK_BYTES"] = str(declared_chunk_bytes)
    fixture.environment["QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256"] = _sha256(manifest_path)


def _install_blocking_post_receive(remote: Path, root: Path) -> tuple[Path, Path, Path]:
    started = root / "post-receive.started"
    release = root / "post-receive.release"
    calls = root / "post-receive.calls"
    hook = remote / "hooks/post-receive"
    hook.write_text(
        "#!/bin/sh\n"
        f"printf 'call\\n' >>{shlex.quote(str(calls))}\n"
        f": >{shlex.quote(str(started))}\n"
        f"while [ ! -e {shlex.quote(str(release))} ]; do sleep 0.05; done\n"
    )
    hook.chmod(0o755)
    return started, release, calls


def _wait_for(path: Path, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path.name}")


def test_publisher_commits_and_pushes_exact_verified_package(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    completed = _publish(fixture)
    assert completed.returncode == 0, completed.stderr
    assert PRIVATE_MARKER not in completed.stdout
    assert PRIVATE_MARKER not in completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["state"] == "published"
    assert receipt["tasks"] == 2499
    local_head = _git(fixture.repository, "rev-parse", "HEAD")
    remote_head = _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0]
    assert receipt["commit"] == remote_head
    assert local_head == fixture.environment["QWEN_PUBLISH_EXPECTED_REMOTE_HEAD"]
    assert _git(fixture.repository, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert not fixture.target.exists()
    transaction_repository = Path(fixture.environment["QWEN_PUBLISH_TRANSACTION_DIR"]) / "repository.git"
    changed = _git(
        transaction_repository,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        receipt["commit"],
    )
    assert all(path.startswith(f"{TARGET_RELATIVE}/") for path in changed.splitlines())
    resumed = _publish(fixture)
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["commit"] == receipt["commit"]


def test_publisher_uses_pinned_manifest_snapshot_after_staging_starts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    original_manifest = (fixture.source / "manifest.json").read_bytes()
    marker = tmp_path / "manifest-race-triggered"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = Path(fixture.environment["PATH"].split(":", 1)[0])
    git_wrapper = fake_bin / "git"
    git_wrapper.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        '  *" hash-object "*manifest.json*|*" hash-object "*manifest.snapshot.json*)\n'
        '    output=$("$REAL_GIT" "$@")\n'
        "    status=$?\n"
        '    [ "$status" -eq 0 ] || exit "$status"\n'
        '    if [ ! -e "$TEST_RACE_MARKER" ]; then\n'
        "      printf '%s\\n' '{\"race\":\"mutated\"}' >\"$TEST_MUTABLE_MANIFEST\"\n"
        '      chmod 0600 "$TEST_MUTABLE_MANIFEST"\n'
        '      : >"$TEST_RACE_MARKER"\n'
        "    fi\n"
        "    printf '%s\\n' \"$output\"\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        'exec "$REAL_GIT" "$@"\n'
    )
    git_wrapper.chmod(0o755)
    fixture.environment.update(
        {
            "REAL_GIT": real_git,
            "TEST_MUTABLE_MANIFEST": str(fixture.source / "manifest.json"),
            "TEST_RACE_MARKER": str(marker),
        }
    )

    completed = _publish(fixture)
    assert completed.returncode == 0, completed.stderr
    assert marker.exists()
    assert (fixture.source / "manifest.json").read_bytes() != original_manifest
    published_commit = json.loads(completed.stdout)["commit"]
    published_manifest = subprocess.run(
        [
            "git",
            "--git-dir",
            str(fixture.remote),
            "show",
            f"{published_commit}:{TARGET_RELATIVE}/manifest.json",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    assert published_manifest == original_manifest
    snapshot = Path(fixture.environment["QWEN_PUBLISH_TRANSACTION_DIR"]) / "manifest.snapshot.json"
    assert snapshot.read_bytes() == original_manifest
    assert snapshot.stat().st_mode & 0o777 == 0o400


def test_publisher_resume_rejects_main_head_advanced_to_transaction_commit(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    completed = _publish(fixture)
    assert completed.returncode == 0, completed.stderr
    published_commit = json.loads(completed.stdout)["commit"]
    _git(fixture.repository, "fetch", "-q", "origin", "refs/heads/vmvm-sandbox")
    _git(fixture.repository, "checkout", "-q", "--detach", published_commit)
    assert _git(fixture.repository, "status", "--porcelain=v1", "--untracked-files=all") == ""
    resumed = _publish(fixture)
    assert resumed.returncode == 2
    assert "repository_not_at_expected_remote_head" in resumed.stderr


def test_publisher_rejects_incomplete_watcher_without_git_mutation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    watcher = json.loads(fixture.watcher_state.read_text())
    watcher["state"] = "running"
    _write_private(fixture.watcher_state, json.dumps(watcher).encode() + b"\n")
    original_head = _git(fixture.repository, "rev-parse", "HEAD")
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "watcher_chain_not_complete" in completed.stderr
    assert PRIVATE_MARKER not in completed.stdout
    assert PRIVATE_MARKER not in completed.stderr
    assert _git(fixture.repository, "rev-parse", "HEAD") == original_head
    assert not fixture.target.exists()


def test_publisher_rejects_manifest_revision_before_staging(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.environment["QWEN_PUBLISH_EXPECTED_PROJECT_REVISION"] = "8" * 40
    original_head = _git(fixture.repository, "rev-parse", "HEAD")
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr
    assert PRIVATE_MARKER not in completed.stdout
    assert PRIVATE_MARKER not in completed.stderr
    assert _git(fixture.repository, "rev-parse", "HEAD") == original_head
    assert not fixture.target.exists()


def test_publisher_rejects_wrong_slurm_worker_provenance(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    Path(fixture.environment["TEST_PACKAGE_WORKER"]).write_text("different worker\n")
    original_head = _git(fixture.repository, "rev-parse", "HEAD")
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_job_provenance_invalid" in completed.stderr
    assert PRIVATE_MARKER not in completed.stdout
    assert PRIVATE_MARKER not in completed.stderr
    assert _git(fixture.repository, "rev-parse", "HEAD") == original_head
    assert not fixture.target.exists()


def test_publisher_rejects_successful_looking_sacct_output_with_failure(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    sacct = Path(fixture.environment["PATH"].split(":", 1)[0]) / "sacct"
    sacct.write_text("#!/bin/sh\nprintf '%s|COMPLETED|0:0\\n' \"$TEST_PACKAGE_JOB\"\nexit 17\n")
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_job_accounting_invalid" in completed.stderr


@pytest.mark.parametrize(
    ("operation", "expected_error"),
    [
        ("ls-remote", "repository_not_at_expected_remote_head"),
        ("remote get-url", "repository_remote_invalid"),
        ("config --show-origin", "repository_remote_invalid"),
        ("status", "repository_not_clean"),
        ("ls-tree", "transaction_base_invalid"),
    ],
)
def test_publisher_rejects_successful_looking_git_output_with_failure(
    tmp_path: Path, operation: str, expected_error: str
) -> None:
    fixture = _fixture(tmp_path)
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = Path(fixture.environment["PATH"].split(":", 1)[0])
    git_wrapper = fake_bin / "git"
    git_wrapper.write_text(
        f'#!/bin/sh\ncase " $* " in *" {operation} "*)\n  "$REAL_GIT" "$@"\n  exit 17\nesac\nexec "$REAL_GIT" "$@"\n'
    )
    git_wrapper.chmod(0o755)
    fixture.environment["REAL_GIT"] = real_git
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert expected_error in completed.stderr


def test_publisher_rejects_successful_looking_find_output_with_failure(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    real_find = shutil.which("find")
    assert real_find is not None
    fake_bin = Path(fixture.environment["PATH"].split(":", 1)[0])
    find_wrapper = fake_bin / "find"
    find_wrapper.write_text('#!/bin/sh\n"$REAL_FIND" "$@"\nexit 17\n')
    find_wrapper.chmod(0o755)
    fixture.environment["REAL_FIND"] = real_find
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr


def test_publisher_fails_closed_when_push_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = fixture.remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    original_remote = _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0]
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "push_outcome_ambiguous" in completed.stderr
    assert PRIVATE_MARKER not in completed.stdout
    assert PRIVATE_MARKER not in completed.stderr
    current_remote = _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0]
    assert current_remote == original_remote
    assert _git(fixture.repository, "rev-parse", "HEAD") == original_remote


def test_publisher_rejects_self_consistent_archive_payload_tamper(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _rewrite_archive_member(fixture, f"{ARCHIVE_ROOT}/results.jsonl")
    original_remote = _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0]
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr
    assert PRIVATE_MARKER not in completed.stdout
    assert PRIVATE_MARKER not in completed.stderr
    assert _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0] == original_remote


@pytest.mark.parametrize("fill", [b"X", b"\0"], ids=["nonzero", "zero-padding"])
def test_publisher_rejects_unmanifested_bytes_after_canonical_tar_end(tmp_path: Path, fill: bytes) -> None:
    fixture = _fixture(tmp_path)
    _append_unmanifested_tar_bytes(fixture, fill)
    original_remote = _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0]
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr
    assert _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0] == original_remote


def test_publisher_rejects_nonzero_member_padding(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _corrupt_member_padding(fixture, f"{ARCHIVE_ROOT}/results.jsonl")
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr


def test_publisher_rejects_final_chunk_larger_than_declared_size(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    archive = next((fixture.source / "chunks").iterdir()).read_bytes()
    _set_chunk_layout(fixture, [archive], 1)
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr


def test_publisher_rejects_oversized_nonfinal_chunk(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    archive = next((fixture.source / "chunks").iterdir()).read_bytes()
    declared = len(archive) // 2
    assert declared > 0 and len(archive) - declared - 1 > 0
    _set_chunk_layout(
        fixture,
        [archive[: declared + 1], archive[declared + 1 :]],
        declared,
    )
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr


def test_publisher_rejects_noncontiguous_chunk_sequence(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    archive = next((fixture.source / "chunks").iterdir()).read_bytes()
    _set_chunk_layout(fixture, [archive], 95_000_000, first_index=1)
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "package_validation_failed" in completed.stderr


def test_publisher_rejects_pushurl_redirect_before_publication(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    unintended = tmp_path / "unintended.git"
    subprocess.run(["git", "init", "--bare", "-q", str(unintended)], check=True)
    _git(fixture.repository, "remote", "set-url", "--push", "origin", str(unintended))
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "repository_remote_invalid" in completed.stderr
    refs = subprocess.run(
        ["git", "--git-dir", str(unintended), "show-ref"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert refs.stdout == ""


def test_publisher_rejects_cwd_dependent_relative_remote_url(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    relative_remote = tmp_path / "relative.git"
    subprocess.run(["git", "init", "--bare", "-q", str(relative_remote)], check=True)
    _git(
        fixture.repository,
        "push",
        "-q",
        str(relative_remote),
        "HEAD:refs/heads/vmvm-sandbox",
    )
    original_head = _git(
        fixture.repository,
        "ls-remote",
        str(relative_remote),
        "refs/heads/vmvm-sandbox",
    ).split()[0]
    relative_url = "../relative.git"
    _git(fixture.repository, "remote", "set-url", "origin", relative_url)
    fixture.environment["QWEN_PUBLISH_EXPECTED_REMOTE_URL"] = relative_url
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "publication_identity_invalid" in completed.stderr
    assert (
        _git(
            fixture.repository,
            "ls-remote",
            str(relative_remote),
            "refs/heads/vmvm-sandbox",
        ).split()[0]
        == original_head
    )
    assert not Path(fixture.environment["QWEN_PUBLISH_TRANSACTION_DIR"]).exists()


def test_publisher_rejects_custom_filter_without_invoking_it(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    marker = tmp_path / "filter-invoked"
    filter_script = tmp_path / "filter.sh"
    filter_script.write_text(f"#!/bin/sh\n: >{shlex.quote(str(marker))}\n/bin/cat\n")
    filter_script.chmod(0o755)
    attributes = fixture.repository / ".gitattributes"
    attributes.write_text(f"{TARGET_RELATIVE}/** filter=private-filter\n")
    _git(fixture.repository, "config", "filter.private-filter.clean", str(filter_script))
    _git(fixture.repository, "add", ".gitattributes")
    _git(fixture.repository, "commit", "-q", "-m", "fixture attributes")
    _git(fixture.repository, "push", "-q", "origin", "HEAD:refs/heads/vmvm-sandbox")
    fixture.environment["QWEN_PUBLISH_EXPECTED_REMOTE_HEAD"] = _git(fixture.repository, "rev-parse", "HEAD")
    completed = _publish(fixture)
    assert completed.returncode == 2
    assert "git_attribute_forbidden" in completed.stderr
    assert not marker.exists()


def test_publisher_disables_client_hooks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    marker = tmp_path / "pre-push-invoked"
    hooks = tmp_path / "client-hooks"
    hooks.mkdir()
    hook = hooks / "pre-push"
    hook.write_text(f"#!/bin/sh\n: >{shlex.quote(str(marker))}\nexit 1\n")
    hook.chmod(0o755)
    _git(fixture.repository, "config", "core.hooksPath", str(hooks))
    completed = _publish(fixture)
    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()


def test_repository_wide_lock_rejects_concurrent_publisher(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    started, release, _calls = _install_blocking_post_receive(fixture.remote, tmp_path)
    first = subprocess.Popen(
        ["bash", str(PUBLISHER), PACKAGE_JOB],
        env=fixture.environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for(started)
        second = _publish(fixture)
        assert second.returncode == 2
        assert "publication_locked" in second.stderr
    finally:
        release.touch()
    first_stdout, first_stderr = first.communicate(timeout=30)
    assert first.returncode == 0, first_stderr
    assert json.loads(first_stdout)["state"] == "published"
    assert _git(fixture.repository, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_publisher_pushes_receipt_commit_when_transaction_head_changes_during_push(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    marker = tmp_path / "transaction-head-race"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_bin = Path(fixture.environment["PATH"].split(":", 1)[0])
    git_wrapper = fake_bin / "git"
    transaction_repo = Path(fixture.environment["QWEN_PUBLISH_TRANSACTION_DIR"]) / "repository.git"
    git_wrapper.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        '  *" --git-dir=$TEST_TRANSACTION_REPO push "*)\n'
        '    original=$("$REAL_GIT" --git-dir="$TEST_TRANSACTION_REPO" rev-parse HEAD) || exit $?\n'
        '    "$REAL_GIT" --git-dir="$TEST_TRANSACTION_REPO" update-ref --no-deref HEAD '
        '"$TEST_EXPECTED_BASE" || exit $?\n'
        '    : >"$TEST_RACE_MARKER"\n'
        '    "$REAL_GIT" "$@"\n'
        "    status=$?\n"
        '    "$REAL_GIT" --git-dir="$TEST_TRANSACTION_REPO" update-ref --no-deref HEAD '
        '"$original" || exit $?\n'
        '    exit "$status"\n'
        "    ;;\n"
        "esac\n"
        'exec "$REAL_GIT" "$@"\n'
    )
    git_wrapper.chmod(0o755)
    fixture.environment.update(
        {
            "REAL_GIT": real_git,
            "TEST_EXPECTED_BASE": fixture.environment["QWEN_PUBLISH_EXPECTED_REMOTE_HEAD"],
            "TEST_RACE_MARKER": str(marker),
            "TEST_TRANSACTION_REPO": str(transaction_repo),
        }
    )

    completed = _publish(fixture)
    assert completed.returncode == 0, completed.stderr
    assert marker.exists()
    receipt = json.loads(completed.stdout)
    assert receipt["commit"] != fixture.environment["QWEN_PUBLISH_EXPECTED_REMOTE_HEAD"]
    assert (
        _git(fixture.repository, "ls-remote", "origin", "refs/heads/vmvm-sandbox").split()[0]
        == receipt["commit"]
    )


def test_term_after_remote_acceptance_is_reconciled_on_resume(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    started, release, calls = _install_blocking_post_receive(fixture.remote, tmp_path)
    process = subprocess.Popen(
        ["bash", str(PUBLISHER), PACKAGE_JOB],
        env=fixture.environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for(started)
    process.terminate()
    release.touch()
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 143, (stdout, stderr)
    receipt_path = Path(fixture.environment["QWEN_PUBLISH_TRANSACTION_DIR"]) / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["state"] == "published"
    resumed = _publish(fixture)
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["commit"] == receipt["commit"]
    assert calls.read_text().splitlines() == ["call"]


def test_publisher_has_terminating_signal_and_explicit_push_contract() -> None:
    body = PUBLISHER.read_text()
    assert "trap cleanup EXIT INT TERM" not in body
    assert "trap cleanup EXIT\n" in body
    assert "trap 'on_signal 130' INT\n" in body
    assert "trap 'on_signal 143' TERM\n" in body
    assert '"$current_commit:refs/heads/$branch"' in body
    assert '"HEAD:refs/heads/$branch"' not in body
    assert "-c push.followTags=false" in body
    assert (
        'validate_transaction_commit "$current_commit" \\\n'
        "    || fail transaction_changed_before_push\n"
        "write_receipt pushing push"
    ) in body
    assert "--force" not in body
    assert "git_attribute_forbidden" in body
    assert "push_outcome_ambiguous" in body
