import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import materialize_sandoq_ramp as ramp
import pytest
from materialize_sandoq_ramp import main, materialize, materialize_config


def test_materialize_sandoq_ramp_binds_opaque_ordered_prefix(tmp_path) -> None:
    source = b"opaque-a\nopaque-b\nopaque-c\n"
    source_path = tmp_path / "source.txt"
    source_path.write_bytes(source)
    payload, receipt = materialize(
        source=source_path,
        source_sha256=hashlib.sha256(source).hexdigest(),
        count=2,
    )
    assert payload == b"opaque-a\nopaque-b\n"
    assert receipt["selected_count"] == 2
    assert receipt["selection"] == "ordered-provider-prefix"
    assert receipt["selected_sha256"] == hashlib.sha256(payload).hexdigest()


def test_materialize_sandoq_ramp_rejects_bad_source(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("opaque-a\nopaque-b\n")
    with pytest.raises(ValueError, match="SHA-256"):
        materialize(source, "0" * 64, 2)


def test_materializer_requires_canonical_partition_inputs(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.txt"
    source.write_text("opaque-a\nopaque-b\n")
    monkeypatch.setattr(
        "sys.argv",
        [
            "materialize_sandoq_ramp.py",
            "--source",
            str(source),
            "--source-sha256",
            hashlib.sha256(source.read_bytes()).hexdigest(),
            "--count",
            "2",
            "--output",
            str(tmp_path / "tasks.txt"),
            "--receipt",
            str(tmp_path / "receipt.json"),
        ],
    )
    with pytest.raises(SystemExit):
        main()


def test_materialize_config_binds_capacity_and_selected_allowlist(tmp_path) -> None:
    template = tmp_path / "template.toml"
    template.write_text(
        "num_tasks = 2500\nmax_concurrent = 64\nmultiplex = 64\n"
        "max_connections = 32\nmax_keepalive_connections = 32\n"
        'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"\n'
        'task_file_sha256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"\n'
    )
    payload = materialize_config(
        template,
        hashlib.sha256(template.read_bytes()).hexdigest(),
        count=2,
        task_file=tmp_path / "selected.txt",
        task_file_sha256="a" * 64,
    )
    assert b"num_tasks = 2\n" in payload
    assert b"max_connections = 2\n" in payload
    assert str(tmp_path / "selected.txt").encode() in payload
    assert ("a" * 64).encode() in payload


def test_materialize_64_stage_keeps_bounded_rollout_and_http_concurrency(tmp_path) -> None:
    template = tmp_path / "template.toml"
    template.write_text(
        "num_tasks = 2500\nmax_concurrent = 64\nmultiplex = 64\n"
        "max_connections = 32\nmax_keepalive_connections = 32\n"
        'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"\n'
        'task_file_sha256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"\n'
    )
    payload = materialize_config(
        template,
        hashlib.sha256(template.read_bytes()).hexdigest(),
        count=64,
        task_file=tmp_path / "selected.txt",
        task_file_sha256="a" * 64,
    )
    assert b"num_tasks = 64\n" in payload
    assert b"max_concurrent = 64\n" in payload
    assert b"multiplex = 64\n" in payload
    assert b"max_connections = 32\n" in payload
    assert b"max_concurrent = 2500" not in payload


def test_main_accepts_existing_private_source_and_atomically_publishes_fresh_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canonical_members = ("opaque-a", "opaque-b", "opaque-c", "opaque-compose")
    canonical_source = tmp_path / "canonical.txt"
    canonical_source.write_text("".join(f"{member}\n" for member in canonical_members))
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    private_root = tmp_path / "shared_qwen38_2p4t"
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    provider_source = private_root / "full-sandoq.tasks.txt"
    provider_source.write_text("opaque-a\nopaque-b\nopaque-c\n")
    provider_source.chmod(0o600)
    output = private_root / "ramp2.tasks.txt"
    receipt = private_root / "ramp2.receipt.json"
    config_output = private_root / "ramp2.toml"
    canonical_template = (
        Path(ramp.__file__).resolve().parent
        / "configs/eval/shared_qwen38_2p4t/mobius_qwen_a95b_2500_sandoq.toml"
    )
    monkeypatch.setattr(ramp, "CANONICAL_SOURCE_SHA256", hashlib.sha256(canonical_source.read_bytes()).hexdigest())
    monkeypatch.setattr(ramp, "SANDOQ_COUNT", 3)
    monkeypatch.setattr(ramp, "verify_canonical_dataset", lambda path: path.resolve(strict=True))
    monkeypatch.setattr(
        ramp,
        "derive_partition",
        lambda _raw, _dataset: SimpleNamespace(sandoq=canonical_members[:3]),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "materialize_sandoq_ramp.py",
            "--source",
            str(provider_source),
            "--source-sha256",
            hashlib.sha256(provider_source.read_bytes()).hexdigest(),
            "--count",
            "2",
            "--canonical-source",
            str(canonical_source),
            "--canonical-dataset",
            str(dataset),
            "--private-output-root",
            str(private_root),
            "--output",
            str(output),
            "--receipt",
            str(receipt),
            "--template",
            str(canonical_template),
            "--template-sha256",
            ramp.CANONICAL_TEMPLATE_SHA256,
            "--config-output",
            str(config_output),
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out) == {"count": 2, "state": "materialized"}
    assert output.read_text() == "opaque-a\nopaque-b\n"
    assert json.loads(receipt.read_text())["selected_count"] == 2
    assert f'num_tasks = 2' in config_output.read_text()
    for path in (provider_source, output, receipt, config_output):
        metadata = path.stat()
        assert metadata.st_uid == os.getuid()
        assert metadata.st_nlink == 1
        assert metadata.st_mode & 0o777 == 0o600
