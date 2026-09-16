import tomllib
from pathlib import Path

import pytest

CONFIG_DIR = Path(__file__).parents[1] / "configs" / "eval"
EVAL_CONFIGS = sorted(CONFIG_DIR.glob("*.toml"))
FORBIDDEN_SAMPLING_FIELDS = {
    "logprobs",
    "prompt_logprobs",
    "top_logprobs",
    "return_token_ids",
}


@pytest.mark.parametrize("config_path", EVAL_CONFIGS, ids=lambda path: path.name)
def test_eval_config_does_not_request_token_metadata(config_path: Path) -> None:
    config = tomllib.loads(config_path.read_text())

    assert FORBIDDEN_SAMPLING_FIELDS.isdisjoint(config.get("sampling", {}))
