import tomllib
from pathlib import Path

import pytest
import tomli_w
from figure3_eval import derive_request_seed
from prepare_rl_checkpoint_eval import materialize_eval_config, resolve_model_path


def _write_toml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        tomli_w.dump(payload, handle)


def _make_run(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    base_model = tmp_path / "models" / "snapshot" / "base"
    base_model.mkdir(parents=True)
    _write_toml(run_dir / "configs" / "trainer.toml", {"model": {"name": str(base_model)}})
    return run_dir, base_model


def test_step_zero_uses_resolved_trainer_model(tmp_path: Path) -> None:
    run_dir, base_model = _make_run(tmp_path)

    eval_path = materialize_eval_config(run_dir, 0, port=23456)

    with eval_path.open("rb") as handle:
        eval_config = tomllib.load(handle)
    with Path(eval_config["infer_config"]).open("rb") as handle:
        inference_config = tomllib.load(handle)

    assert resolve_model_path(run_dir, 0) == base_model.resolve()
    assert inference_config["model"]["name"] == str(base_model.resolve())
    assert inference_config["server"]["port"] == 23456
    assert eval_config["eval"]["model"] == str(base_model.resolve())
    assert eval_config["eval"]["api_base_url"] == "http://127.0.0.1:23456/v1"
    assert eval_config["eval"]["output_dir"] == str(run_dir / "evals" / "op11-45" / "step_0")
    assert eval_config["eval"]["request_seed"] == 20260807


def test_positive_step_requires_stable_weight_export(tmp_path: Path) -> None:
    run_dir, _ = _make_run(tmp_path)
    checkpoint = run_dir / "weights" / "step_25"
    checkpoint.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="not marked stable"):
        resolve_model_path(run_dir, 25)

    (checkpoint / "STABLE").touch()
    assert resolve_model_path(run_dir, 25) == checkpoint


def test_materialized_eval_covers_op11_through_op45(tmp_path: Path) -> None:
    run_dir, _ = _make_run(tmp_path)

    eval_path = materialize_eval_config(run_dir, 0)

    with eval_path.open("rb") as handle:
        eval_config = tomllib.load(handle)
    assert eval_config["eval"]["operations"] == list(range(11, 46))
    assert eval_config["eval"]["samples_per_prompt"] == 1
    assert eval_config["eval"]["pass_at"] == [1]


def test_request_seed_is_prompt_stable() -> None:
    row = {"op": 15, "id": "problem-a", "__idx": 7}

    assert derive_request_seed(row, 20260807) == derive_request_seed(dict(row), 20260807)
    assert derive_request_seed(row, 20260807) != derive_request_seed({**row, "id": "problem-b"}, 20260807)
