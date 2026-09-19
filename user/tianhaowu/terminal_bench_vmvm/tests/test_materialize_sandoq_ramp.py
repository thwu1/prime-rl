import hashlib

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
    assert receipt["selected_sha256"] == hashlib.sha256(payload).hexdigest()


def test_materialize_sandoq_ramp_rejects_bad_source(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("opaque-a\nopaque-b\n")
    with pytest.raises(ValueError, match="SHA-256"):
        materialize(source, "0" * 64, 2)


def test_materializer_rejects_noncanonical_matching_source(tmp_path, monkeypatch) -> None:
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
    with pytest.raises(ValueError, match="canonical"):
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


def test_materialize_production_keeps_bounded_rollout_and_http_concurrency(tmp_path) -> None:
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
        count=2500,
        task_file=tmp_path / "selected.txt",
        task_file_sha256="a" * 64,
    )
    assert b"num_tasks = 2500\n" in payload
    assert b"max_concurrent = 64\n" in payload
    assert b"multiplex = 64\n" in payload
    assert b"max_connections = 32\n" in payload
    assert b"max_concurrent = 2500" not in payload
