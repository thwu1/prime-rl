import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from renderers import Nemotron3RendererConfig
from renderers.base import RenderedTokens

from prime_rl.configs.sft import SFTDataConfig
from prime_rl.trainer.sft import export_preflight
from prime_rl.trainer.sft.export_preflight import SFTPreflightError


class SyntheticTokenizer:
    eos_token_id = 99


class SyntheticRenderer:
    def __init__(self, *, retain_reasoning: bool = True, corrupt_mask: bool = False):
        self.retain_reasoning = retain_reasoning
        self.corrupt_mask = corrupt_mask

    def render(self, messages, *, tools=None, add_generation_prompt=False):
        del tools
        tokens: list[int] = []
        indices: list[int] = []
        sampled: list[bool] = []
        for index, message in enumerate(messages):
            assistant = message["role"] == "assistant"
            if assistant:
                tokens.append(70)
                indices.append(index)
                sampled.append(False)
            else:
                tokens.append(10 + index)
                indices.append(index)
                sampled.append(False)
            reasoning = message.get("reasoning_content")
            if assistant and self.retain_reasoning and isinstance(reasoning, str) and reasoning:
                tokens.append(50 + len(reasoning))
                indices.append(index)
                sampled.append(True)
            content = message.get("content")
            if assistant and isinstance(content, str) and content:
                tokens.append(60 + len(content))
                indices.append(index)
                sampled.append(True)
            if assistant:
                tokens.append(99)
                indices.append(index)
                sampled.append(True)
        if add_generation_prompt:
            tokens.append(70)
            indices.append(-1)
            sampled.append(False)
        if self.corrupt_mask and sampled:
            sampled[-1] = False
        return RenderedTokens(
            token_ids=tokens,
            message_indices=indices,
            sampled_mask=sampled,
            is_content=list(sampled),
            message_roles=[message["role"] for message in messages],
        )


def _row() -> dict:
    return {
        "assistant_target_count": 1,
        "history_reasoning_policy": "preserve_all_assistant_reasoning",
        "is_correct": True,
        "messages": [
            {"role": "user", "content": "question", "trainable": False},
            {
                "role": "assistant",
                "content": "answer",
                "finish_reason": "stop",
                "reasoning_content": "reasoning",
                "trainable": True,
            },
        ],
        "reward": 1.0,
        "source_episode_id": "a" * 64,
        "source_node_index": 1,
        "source_split_row_index": 0,
        "source_trace_index": 0,
        "source_trajectory_assistant_turn_count": 1,
        "target_assistant_message_index": 1,
        "target_assistant_turn_index": 0,
        "target_finish_reason": "stop",
        "target_has_reasoning": True,
        "task_id": "b" * 64,
        "tools": [
            {
                "type": "function",
                "function": {"description": "synthetic", "name": "terminal", "parameters": {}},
            }
        ],
        "transcript_fidelity": {
            "retained_assistant_reasoning_fields": 1,
            "retained_sampled_finish_reasons": 1,
            "source_assistant_reasoning_fields": 1,
            "source_sampled_finish_reasons": 1,
        },
    }


def _attestation(root: Path) -> dict:
    artifact = {"bytes": 1, "sha256": "a" * 64}
    summary = {
        "max_rendered_tokens": 10,
        "nonempty_reasoning_fields": 1,
        "reasoning_fields": 1,
        "reasoning_fields_rendered": 1,
        "rendered_tokens": 10,
        "rows": 1,
        "trainable_tokens": 2,
    }
    empty_summary = {field: 0 for field in summary}
    return {
        "code": {
            "dependencies": {"datasets": "1", "renderers": "1", "tokenizers": "1", "transformers": "1"},
            "project_revision": "c" * 40,
            "renderer_repository_revision": export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["renderer"][
                "repository_revision"
            ],
            "source": {name: artifact for name in export_preflight.CODE_PATHS},
        },
        "export": {
            "artifacts": {name: artifact for name in export_preflight.REQUIRED_EXPORT_ARTIFACTS},
            "manifest": artifact,
            "root": str(root),
        },
        "kind": export_preflight.ATTESTATION_KIND,
        "rendering": {**summary, "splits": {"train": summary, "validation": empty_summary}},
        "schema_version": export_preflight.ATTESTATION_SCHEMA_VERSION,
        "target_rendering": export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT,
    }


def test_render_preflight_requires_reasoning_sensitive_renderer() -> None:
    with pytest.raises(SFTPreflightError, match="^row_reasoning_not_rendered$"):
        export_preflight._validate_and_render_row(
            _row(),
            SyntheticTokenizer(),
            SyntheticRenderer(retain_reasoning=False),
            262_144,
        )


def test_render_preflight_rejects_incorrect_sampled_loss_mask() -> None:
    with pytest.raises(SFTPreflightError, match="^row_loss_mask_invalid$"):
        export_preflight._validate_and_render_row(
            _row(),
            SyntheticTokenizer(),
            SyntheticRenderer(corrupt_mask=True),
            262_144,
        )


def test_render_preflight_rejects_overlong_row() -> None:
    with pytest.raises(SFTPreflightError, match="^row_render_contract_invalid$"):
        export_preflight._validate_and_render_row(_row(), SyntheticTokenizer(), SyntheticRenderer(), 3)


def test_training_config_is_bound_to_exact_tokenizer_renderer_and_loss_mask(tmp_path: Path) -> None:
    root = tmp_path / "export"
    (root / "train").mkdir(parents=True)
    data = SFTDataConfig(name=str(root / "train"), seq_len=16, pack_function="fixed_stack")
    config = SimpleNamespace(
        tokenizer=SimpleNamespace(
            name=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]["repository"],
            revision=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]["revision"],
            trust_remote_code=False,
            chat_template=None,
        ),
        renderer=Nemotron3RendererConfig.model_validate(
            export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]["config"]
        ),
    )
    attestation = _attestation(root)

    export_preflight._validate_config_binding(config, [data], attestation)
    config.tokenizer.revision = "d" * 40
    with pytest.raises(SFTPreflightError, match="^training_rendering_contract_mismatch$"):
        export_preflight._validate_config_binding(config, [data], attestation)

    config.tokenizer.revision = export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]["revision"]
    config.renderer = config.renderer.model_copy(update={"preserve_all_thinking": False})
    with pytest.raises(SFTPreflightError, match="^training_rendering_contract_mismatch$"):
        export_preflight._validate_config_binding(config, [data], attestation)

    config.renderer = Nemotron3RendererConfig.model_validate(
        export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]["config"]
    )
    data.loss_mask = data.loss_mask.model_copy(update={"system": True})
    with pytest.raises(SFTPreflightError, match="^training_data_contract_mismatch$"):
        export_preflight._validate_config_binding(config, [data], attestation)


def test_attestation_rejects_renderer_gitlink_tamper(tmp_path: Path) -> None:
    attestation = _attestation(tmp_path / "export")
    attestation["code"]["renderer_repository_revision"] = "d" * 40

    with pytest.raises(SFTPreflightError, match="^attestation_contract_invalid$"):
        export_preflight._validate_attestation_value(attestation)


def test_repository_provenance_rejects_checked_out_renderer_gitlink_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(export_preflight.__file__).resolve().parents[4]
    expected_revision = "c" * 40

    def fake_run_git(directory: Path, arguments: list[str], _code: str) -> str:
        if directory == project and arguments == ["rev-parse", "--show-toplevel"]:
            return f"{project}\n"
        if directory == project and arguments == ["rev-parse", "HEAD"]:
            return f"{expected_revision}\n"
        if directory == project and arguments == ["status", "--porcelain=v1", "--untracked-files=all"]:
            return ""
        if directory == project and arguments == ["ls-tree", expected_revision, "--", "deps/renderers"]:
            return f"160000 commit {'d' * 40}\tdeps/renderers\n"
        raise AssertionError((directory, arguments))

    monkeypatch.setattr(export_preflight, "_run_git", fake_run_git)

    with pytest.raises(SFTPreflightError, match="^renderer_revision_invalid$"):
        export_preflight._repository_provenance(project, expected_revision)


def test_format_v3_manifest_requires_attestation_before_training(tmp_path: Path) -> None:
    root = tmp_path / "export"
    split = root / "train"
    split.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({"exporter": {"format_version": 3}}))
    config = SimpleNamespace(data=SFTDataConfig(name=str(split)), val=None)

    with pytest.raises(SFTPreflightError, match="^format_v3_preflight_required$"):
        export_preflight.validate_sft_training_preflight(config)


def test_sft_data_config_requires_complete_immutable_attestation_binding(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be set together"):
        SFTDataConfig(preflight_attestation=tmp_path / "preflight.json")
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        SFTDataConfig(
            preflight_attestation=tmp_path / "preflight.json",
            preflight_attestation_sha256="A" * 64,
        )


def test_attestation_digest_is_rechecked_at_training_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "export"
    split = root / "train"
    split.mkdir(parents=True)
    attestation_path = tmp_path / "preflight.json"
    attestation_path.write_text("{}")
    attestation_path.chmod(0o600)
    data = SFTDataConfig(
        name=str(split),
        preflight_attestation=attestation_path,
        preflight_attestation_sha256="f" * 64,
    )
    config = SimpleNamespace(data=data, val=None)
    monkeypatch.setattr(export_preflight, "_format_v3_root", lambda _data: root)

    with pytest.raises(SFTPreflightError, match="^attestation_digest_mismatch$"):
        export_preflight.validate_sft_training_preflight(config)


def test_training_start_rechecks_attested_code_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "export"
    split = root / "train"
    split.mkdir(parents=True)
    attestation = _attestation(root)
    body = (json.dumps(attestation, indent=2, sort_keys=True) + "\n").encode()
    attestation_path = tmp_path / "preflight.json"
    attestation_path.write_bytes(body)
    attestation_path.chmod(0o600)
    data = SFTDataConfig(
        name=str(split),
        seq_len=16,
        pack_function="fixed_stack",
        preflight_attestation=attestation_path,
        preflight_attestation_sha256=hashlib.sha256(body).hexdigest(),
    )
    config = SimpleNamespace(
        data=data,
        val=None,
        tokenizer=SimpleNamespace(
            name=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]["repository"],
            revision=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]["revision"],
            trust_remote_code=False,
            chat_template=None,
        ),
        renderer=Nemotron3RendererConfig.model_validate(
            export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]["config"]
        ),
    )
    artifact = export_preflight.FileArtifact(1, "a" * 64)
    binding = export_preflight.ExportBinding(
        root=root,
        manifest=artifact,
        artifacts={name: artifact for name in export_preflight.REQUIRED_EXPORT_ARTIFACTS},
        manifest_value={},
        target_rendering=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT,
    )
    monkeypatch.setattr(export_preflight, "_format_v3_root", lambda _data: root)
    monkeypatch.setattr(export_preflight, "_load_export_binding", lambda *_args: binding)
    monkeypatch.setattr(export_preflight, "_repository_provenance", lambda *_args: attestation["code"])

    assert export_preflight.validate_sft_training_preflight(config) is True

    changed_code = copy.deepcopy(attestation["code"])
    changed_code["source"][export_preflight.CODE_PATHS[0]] = {"bytes": 1, "sha256": "f" * 64}
    monkeypatch.setattr(export_preflight, "_repository_provenance", lambda *_args: changed_code)
    with pytest.raises(SFTPreflightError, match="^attested_code_changed$"):
        export_preflight.validate_sft_training_preflight(config)


def test_attested_row_rejects_noncanonical_tool_type() -> None:
    row = _row()
    row["tools"][0]["type"] = "custom"

    with pytest.raises(SFTPreflightError, match="^row_tool_contract_invalid$"):
        export_preflight._validate_and_render_row(row, SyntheticTokenizer(), SyntheticRenderer(), 262_144)


def test_embedded_target_contract_matches_exporter_sidecar() -> None:
    project = Path(__file__).resolve().parents[4]
    sidecar = (
        project
        / "user"
        / "tianhaowu"
        / "terminal_bench_vmvm"
        / "configs"
        / "sft"
        / export_preflight.TARGET_RENDERING_CONTRACT_FILENAME
    )

    body = sidecar.read_bytes()
    assert hashlib.sha256(body).hexdigest() == export_preflight.TARGET_RENDERING_CONTRACT_SHA256
    assert json.loads(body) == export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT
