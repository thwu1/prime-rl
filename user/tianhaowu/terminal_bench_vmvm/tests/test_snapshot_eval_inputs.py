from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from snapshot_eval_inputs import snapshot


def test_snapshot_copies_config_and_mutable_inputs(tmp_path: Path) -> None:
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("task-a\ntask-b\n")
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text('{"task-a":"image@sha256:abc"}\n')
    config = tmp_path / "eval.toml"
    config.write_text(
        "[taskset]\n"
        f'task_file = "{task_file}"\n'
        f'image_manifest = "{image_manifest}"\n'
    )

    output = tmp_path / "snapshot"
    records = snapshot(config, output)

    assert (output / "source_config.toml").read_bytes() == config.read_bytes()
    assert (output / "task_file.txt").read_bytes() == task_file.read_bytes()
    assert (output / "image_manifest.json").read_bytes() == image_manifest.read_bytes()
    persisted = json.loads((output / "manifest.json").read_text())
    assert persisted == records
    assert records["task_file"]["sha256"] == hashlib.sha256(
        task_file.read_bytes()
    ).hexdigest()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        snapshot(config, output)
