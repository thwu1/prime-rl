import copy
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from datasets import Dataset
from renderers import Nemotron3RendererConfig
from renderers.base import RenderedTokens
from renderers.nemotron3 import Nemotron3Renderer

from prime_rl.configs.sft import SFTDataConfig
from prime_rl.trainer.sft import export_preflight
from prime_rl.trainer.sft.data import SFTDataset
from prime_rl.trainer.sft.export_preflight import SFTPreflightError


class SyntheticTokenizer:
    eos_token_id = 99


class CharacterTokenizer:
    name_or_path = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
    unk_token_id = 0
    eos_token_id = 2
    is_fast = True
    _special_tokens = {
        "<|im_start|>": 1,
        "<|im_end|>": 2,
        "<|endoftext|>": 3,
        "<think>": 4,
        "</think>": 5,
        "<tool_call>": 6,
        "</tool_call>": 7,
        "<tool_response>": 8,
        "</tool_response>": 9,
    }

    def convert_tokens_to_ids(self, token: str) -> int:
        return self._special_tokens.get(token, self.unk_token_id)

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        assert add_special_tokens is False
        return [1_000 + ord(character) for character in text]

    def __call__(self, text: str, *, add_special_tokens: bool, return_offsets_mapping: bool) -> dict:
        assert add_special_tokens is False
        assert return_offsets_mapping is True
        return {
            "input_ids": self.encode(text, add_special_tokens=False),
            "offset_mapping": [(index, index + 1) for index in range(len(text))],
        }


class SyntheticRenderer:
    def __init__(self, *, retain_reasoning: bool = True):
        self.retain_reasoning = retain_reasoning

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
                tokens.append(11)
                indices.append(index)
                sampled.append(False)
        if add_generation_prompt:
            tokens.append(70)
            indices.append(-1)
            sampled.append(False)
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
        "expected_require_exact_provider_json": False,
        "export": {
            "artifacts": {name: artifact for name in export_preflight.REQUIRED_EXPORT_ARTIFACTS},
            "manifest": artifact,
            "root": str(root),
        },
        "kind": export_preflight.ATTESTATION_KIND,
        "rendering": {**summary, "splits": {"train": summary, "validation": empty_summary}},
        "schema_version": export_preflight.ATTESTATION_SCHEMA_VERSION,
        "source_validation": {
            "max_sequence_tokens": 262_144,
            "require_clean_stop": True,
            "require_exact_provider_json": False,
            "require_model_io": True,
            "require_reasoning": True,
            "require_request_graph_match": True,
        },
        "target_rendering": export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT,
    }


@pytest.fixture
def tokenizer_snapshot(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "tokenizer-snapshot"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "tokenizer.json").write_bytes(b'{"version":"fixture"}\n')
    (nested / "tokenizer_config.json").write_bytes(b'{"fixture":true}\n')
    for path in (root / "tokenizer.json", nested / "tokenizer_config.json"):
        path.chmod(0o400)
    nested.chmod(0o500)
    root.chmod(0o500)
    try:
        yield root
    finally:
        if root.exists() and not root.is_symlink():
            root.chmod(0o700)
            for directory, directory_names, _file_names in os.walk(root):
                Path(directory).chmod(0o700)
                for name in directory_names:
                    path = Path(directory) / name
                    if not path.is_symlink():
                        path.chmod(0o700)


def _snapshot_attestation(root: Path, snapshot: Path) -> dict:
    value = _attestation(root)
    tree = export_preflight._fingerprint_tokenizer_snapshot(snapshot)
    tokenizer = export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]
    value["tokenizer_snapshot"] = {
        "local_files_only": True,
        "path": str(snapshot),
        "repository": tokenizer["repository"],
        "revision": tokenizer["revision"],
        "tree": tree.as_dict(),
        "trust_remote_code": False,
    }
    return value


def test_tokenizer_snapshot_tree_is_deterministic_and_binds_content(tokenizer_snapshot: Path) -> None:
    first = export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot)
    second = export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot)

    assert first == second
    assert first.algorithm == "sha256-path-mode-size-content-v1"
    assert first.file_count == 2
    assert first.total_bytes == sum(path.stat().st_size for path in tokenizer_snapshot.rglob("*.json"))

    tokenizer_file = tokenizer_snapshot / "tokenizer.json"
    tokenizer_file.chmod(0o600)
    tokenizer_file.write_bytes(b'{"version":"changed"}\n')
    tokenizer_file.chmod(0o400)
    assert export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot).sha256 != first.sha256


@pytest.mark.parametrize(
    "invalid_kind",
    ["directory_mode", "subdirectory_mode", "file_mode", "hardlink", "symlink", "fifo"],
)
def test_tokenizer_snapshot_rejects_mutable_or_nonregular_tree(
    tokenizer_snapshot: Path,
    invalid_kind: str,
) -> None:
    root = tokenizer_snapshot
    root.chmod(0o700)
    if invalid_kind == "directory_mode":
        pass
    elif invalid_kind == "subdirectory_mode":
        (root / "nested").chmod(0o700)
        root.chmod(0o500)
    elif invalid_kind == "file_mode":
        (root / "tokenizer.json").chmod(0o600)
        root.chmod(0o500)
    elif invalid_kind == "hardlink":
        os.link(root / "tokenizer.json", root / "hardlink.json")
        root.chmod(0o500)
    elif invalid_kind == "symlink":
        (root / "symlink.json").symlink_to(root / "tokenizer.json")
        root.chmod(0o500)
    else:
        os.mkfifo(root / "fifo")
        root.chmod(0o500)

    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_invalid$"):
        export_preflight._fingerprint_tokenizer_snapshot(root)


def test_tokenizer_snapshot_requires_current_owner(tokenizer_snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other_owner = os.geteuid() + 1
    monkeypatch.setattr(export_preflight.os, "geteuid", lambda: other_owner)

    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_invalid$"):
        export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot)


def test_tokenizer_snapshot_rejects_symlinked_root(tokenizer_snapshot: Path) -> None:
    alias = tokenizer_snapshot.parent / "tokenizer-alias"
    alias.symlink_to(tokenizer_snapshot, target_is_directory=True)

    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_invalid$"):
        export_preflight._fingerprint_tokenizer_snapshot(alias)


def test_local_tokenizer_load_is_offline_only_and_does_not_mutate_snapshot(
    tokenizer_snapshot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot)
    binding = export_preflight._bind_tokenizer_snapshot(tokenizer_snapshot, tree.sha256)
    calls: list[tuple[tuple, dict]] = []

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return SyntheticTokenizer()

    monkeypatch.setattr(export_preflight.AutoTokenizer, "from_pretrained", staticmethod(load))
    assert binding is not None
    tokenizer = export_preflight._load_render_tokenizer(binding)

    assert isinstance(tokenizer, SyntheticTokenizer)
    assert calls == [
        (
            (str(tokenizer_snapshot),),
            {"local_files_only": True, "trust_remote_code": False},
        )
    ]
    assert export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot) == tree


def test_local_tokenizer_load_rejects_snapshot_mutation(
    tokenizer_snapshot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot)
    binding = export_preflight._bind_tokenizer_snapshot(tokenizer_snapshot, tree.sha256)

    def mutate(*_args, **_kwargs):
        tokenizer_file = tokenizer_snapshot / "tokenizer.json"
        tokenizer_file.chmod(0o600)
        tokenizer_file.write_bytes(b'{"version":"mutated-during-load"}\n')
        tokenizer_file.chmod(0o400)
        return SyntheticTokenizer()

    monkeypatch.setattr(export_preflight.AutoTokenizer, "from_pretrained", staticmethod(mutate))
    assert binding is not None
    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_changed$"):
        export_preflight._load_render_tokenizer(binding)


def test_tokenizer_snapshot_binding_is_both_or_neither_and_digest_pinned(tokenizer_snapshot: Path) -> None:
    tree = export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot)

    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_binding_invalid$"):
        export_preflight._bind_tokenizer_snapshot(tokenizer_snapshot, None)
    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_binding_invalid$"):
        export_preflight._bind_tokenizer_snapshot(None, tree.sha256)
    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_digest_mismatch$"):
        export_preflight._bind_tokenizer_snapshot(tokenizer_snapshot, "0" * 64)
    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_invalid$"):
        export_preflight._bind_tokenizer_snapshot(
            tokenizer_snapshot.parent / "." / tokenizer_snapshot.name / ".." / tokenizer_snapshot.name,
            tree.sha256,
        )


def test_render_preflight_requires_reasoning_sensitive_renderer() -> None:
    with pytest.raises(SFTPreflightError, match="^row_reasoning_not_rendered$"):
        export_preflight._validate_and_render_row(
            _row(),
            SyntheticTokenizer(),
            SyntheticRenderer(retain_reasoning=False),
            262_144,
        )


def test_render_preflight_rejects_incorrect_sampled_loss_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = SyntheticRenderer()

    def incorrect_training_sample(*_args, **_kwargs):
        rendered = renderer.render(_row()["messages"])
        return rendered.token_ids, [False] * len(rendered.token_ids)

    monkeypatch.setattr(export_preflight, "build_training_sample", incorrect_training_sample)

    with pytest.raises(SFTPreflightError, match="^row_loss_mask_invalid$"):
        export_preflight._validate_and_render_row(
            _row(),
            SyntheticTokenizer(),
            renderer,
            262_144,
        )


def test_render_preflight_rejects_overlong_row() -> None:
    with pytest.raises(SFTPreflightError, match="^row_render_contract_invalid$"):
        export_preflight._validate_and_render_row(_row(), SyntheticTokenizer(), SyntheticRenderer(), 3)


@pytest.mark.parametrize(
    "arguments",
    ["[]", "null", '{"value":null}', '{"value":NaN}', '{"value":1e400}', '{"value":1,"value":2}'],
)
def test_render_preflight_rejects_lossy_tool_arguments(arguments: str) -> None:
    row = _row()
    row["messages"][-1]["tool_calls"] = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "terminal", "arguments": arguments},
        }
    ]

    with pytest.raises(SFTPreflightError, match="^row_tool_arguments_invalid$"):
        export_preflight._validate_and_render_row(
            row,
            SyntheticTokenizer(),
            SyntheticRenderer(),
            262_144,
        )


def test_render_preflight_rejects_unknown_finish_reason() -> None:
    row = _row()
    row["messages"][-1]["finish_reason"] = "content_filter"
    row["target_finish_reason"] = "content_filter"

    with pytest.raises(SFTPreflightError, match="^row_finish_reason_contract_invalid$"):
        export_preflight._validate_and_render_row(
            row,
            SyntheticTokenizer(),
            SyntheticRenderer(),
            262_144,
        )


def test_real_nemotron_renderer_matches_sft_dataset_mask_and_trailing_newline() -> None:
    tokenizer = CharacterTokenizer()
    renderer = Nemotron3Renderer(
        tokenizer,
        Nemotron3RendererConfig.model_validate(
            export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]["config"]
        ),
    )
    row = _row()

    summary = export_preflight._validate_and_render_row(row, tokenizer, renderer, 262_144)
    prepared = export_preflight._prepare_messages(row["messages"])
    rendered = renderer.render(prepared, tools=row["tools"])
    target_sampled = [
        index
        for index, (message_index, sampled) in enumerate(
            zip(rendered.message_indices, rendered.sampled_mask, strict=True)
        )
        if message_index == row["target_assistant_message_index"] and sampled
    ]

    assert summary.rows == 1
    assert rendered.token_ids[target_sampled[-1]] == tokenizer.eos_token_id
    assert rendered.token_ids[-1] == 1_000 + ord("\n")
    assert rendered.sampled_mask[-1] is False

    dataset = SFTDataset(
        Dataset.from_list([row]),
        tokenizer=tokenizer,
        renderer=renderer,
        shuffle=False,
        seq_len=262_144,
        max_examples=1,
        max_epochs=1,
        attested_export=True,
    )
    sample = next(iter(dataset))
    _token_ids, expected_mask = export_preflight.build_training_sample(
        renderer,
        prepared,
        role_to_mask=lambda message: export_preflight._message_is_trainable(
            message,
            export_preflight.LossMaskConfig(),
        ),
        tools=row["tools"],
    )

    assert sample["input_ids"] == rendered.token_ids[:-1]
    assert sample["target_ids"] == rendered.token_ids[1:]
    assert sample["loss_mask"] == expected_mask[1:]


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


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("repository",), "other/repository"),
        (("revision",), "d" * 40),
        (("local_files_only",), False),
        (("trust_remote_code",), True),
        (("tree", "algorithm"), "other"),
        (("tree", "sha256"), "A" * 64),
    ],
)
def test_attestation_rejects_invalid_tokenizer_snapshot_binding(
    tmp_path: Path,
    tokenizer_snapshot: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    attestation = _snapshot_attestation(tmp_path / "export", tokenizer_snapshot)
    target = attestation["tokenizer_snapshot"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(SFTPreflightError, match="^attestation_contract_invalid$"):
        export_preflight._validate_attestation_value(attestation)


def test_attestation_write_atomically_publishes_complete_private_file(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    value = {"aggregate": 1}
    expected = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode() + b"\n"

    artifact = export_preflight._write_attestation(path, value)

    assert path.read_bytes() == expected
    assert path.stat().st_mode & 0o777 == 0o600
    assert artifact == export_preflight.FileArtifact(len(expected), hashlib.sha256(expected).hexdigest())
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


def test_attestation_partial_write_never_publishes_and_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "preflight.json"
    real_fdopen = export_preflight.os.fdopen

    class PartialWriter:
        def __init__(self, descriptor: int, mode: str):
            self._handle = real_fdopen(descriptor, mode)

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *arguments):
            return self._handle.__exit__(*arguments)

        def write(self, body: bytes) -> None:
            self._handle.write(body[: max(1, len(body) // 2)])
            raise OSError("simulated_partial_write")

        def flush(self) -> None:
            self._handle.flush()

        def fileno(self) -> int:
            return self._handle.fileno()

    with monkeypatch.context() as context:
        context.setattr(export_preflight.os, "fdopen", PartialWriter)
        with pytest.raises(SFTPreflightError, match="^attestation_write_failed$"):
            export_preflight._write_attestation(path, {"aggregate": 1})

    assert not path.exists()
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))
    export_preflight._write_attestation(path, {"aggregate": 1})
    assert path.is_file()


def test_attestation_crash_before_publish_cleans_temporary_and_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "preflight.json"

    with monkeypatch.context() as context:
        context.setattr(
            export_preflight.os,
            "link",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        with pytest.raises(KeyboardInterrupt):
            export_preflight._write_attestation(path, {"aggregate": 1})

    assert not path.exists()
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))
    export_preflight._write_attestation(path, {"aggregate": 1})
    assert path.is_file()


def test_attestation_snapshot_guard_runs_before_atomic_publication(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"

    with pytest.raises(SFTPreflightError, match="^tokenizer_snapshot_changed$"):
        export_preflight._write_attestation(
            path,
            {"aggregate": 1},
            before_publish=lambda: (_ for _ in ()).throw(SFTPreflightError("tokenizer_snapshot_changed")),
        )

    assert not path.exists()
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


def test_attestation_directory_fsync_failure_leaves_only_complete_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "preflight.json"
    value = {"aggregate": 1}
    expected = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode() + b"\n"
    real_fsync = export_preflight.os.fsync
    calls = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated_directory_fsync_failure")
        real_fsync(descriptor)

    with monkeypatch.context() as context:
        context.setattr(export_preflight.os, "fsync", fail_directory_fsync)
        with pytest.raises(SFTPreflightError, match="^attestation_write_failed$"):
            export_preflight._write_attestation(path, value)

    assert calls == 2
    assert path.read_bytes() == expected
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))
    with pytest.raises(SFTPreflightError, match="^attestation_write_failed$"):
        export_preflight._write_attestation(path, {"aggregate": 2})
    assert path.read_bytes() == expected


def test_attestation_existing_file_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    path.write_bytes(b"preserve\n")

    with pytest.raises(SFTPreflightError, match="^attestation_write_failed$"):
        export_preflight._write_attestation(path, {"aggregate": 1})

    assert path.read_bytes() == b"preserve\n"
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


def test_attestation_existing_symlink_is_never_followed_or_replaced(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"preserve\n")
    path = tmp_path / "preflight.json"
    path.symlink_to(target)

    with pytest.raises(SFTPreflightError, match="^attestation_write_failed$"):
        export_preflight._write_attestation(path, {"aggregate": 1})

    assert path.is_symlink()
    assert target.read_bytes() == b"preserve\n"
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


@pytest.mark.parametrize("require_exact_provider_json", [False, True])
def test_preflight_attestation_binds_expected_source_validation_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require_exact_provider_json: bool,
) -> None:
    root = tmp_path / "export"
    root.mkdir()
    attestation = _attestation(root)
    attestation["expected_require_exact_provider_json"] = require_exact_provider_json
    attestation["source_validation"]["require_exact_provider_json"] = require_exact_provider_json
    artifact = export_preflight.FileArtifact(1, "a" * 64)
    binding = export_preflight.ExportBinding(
        root=root,
        manifest=artifact,
        artifacts={name: artifact for name in export_preflight.REQUIRED_EXPORT_ARTIFACTS},
        manifest_value={"counts": {"emitted_rows": 1, "train_rows": 1, "validation_rows": 0}},
        source_validation=attestation["source_validation"],
        target_rendering=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT,
    )
    monkeypatch.setattr(export_preflight, "_load_export_binding", lambda *_args: binding)
    monkeypatch.setattr(export_preflight, "_repository_provenance", lambda *_args: attestation["code"])
    monkeypatch.setattr(
        export_preflight,
        "_render_export",
        lambda _binding, _tokenizer_snapshot=None: attestation["rendering"],
    )

    output = tmp_path / f"preflight-{require_exact_provider_json}.json"
    summary = export_preflight.create_sft_preflight_attestation(
        export_root=root,
        expected_manifest_sha256="a" * 64,
        project_dir=tmp_path,
        expected_project_revision="c" * 40,
        expected_require_exact_provider_json=require_exact_provider_json,
        output=output,
    )

    value = json.loads(output.read_bytes())
    assert summary["require_exact_provider_json"] is require_exact_provider_json
    assert value["expected_require_exact_provider_json"] is require_exact_provider_json
    assert value["source_validation"]["require_exact_provider_json"] is require_exact_provider_json
    assert "tokenizer_snapshot" not in value


def test_preflight_attestation_binds_strict_local_tokenizer_snapshot(
    tmp_path: Path,
    tokenizer_snapshot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "export"
    root.mkdir()
    attestation = _attestation(root)
    artifact = export_preflight.FileArtifact(1, "a" * 64)
    binding = export_preflight.ExportBinding(
        root=root,
        manifest=artifact,
        artifacts={name: artifact for name in export_preflight.REQUIRED_EXPORT_ARTIFACTS},
        manifest_value={"counts": {"emitted_rows": 1, "train_rows": 1, "validation_rows": 0}},
        source_validation=attestation["source_validation"],
        target_rendering=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT,
    )
    tree = export_preflight._fingerprint_tokenizer_snapshot(tokenizer_snapshot)
    rendered_snapshots: list[export_preflight.TokenizerSnapshotBinding | None] = []
    monkeypatch.setattr(export_preflight, "_load_export_binding", lambda *_args: binding)
    monkeypatch.setattr(export_preflight, "_repository_provenance", lambda *_args: attestation["code"])

    def render(
        _binding: export_preflight.ExportBinding,
        snapshot: export_preflight.TokenizerSnapshotBinding | None = None,
    ) -> dict:
        rendered_snapshots.append(snapshot)
        return attestation["rendering"]

    monkeypatch.setattr(export_preflight, "_render_export", render)
    output = tmp_path / "preflight-strict.json"

    export_preflight.create_sft_preflight_attestation(
        export_root=root,
        expected_manifest_sha256="a" * 64,
        project_dir=tmp_path,
        expected_project_revision="c" * 40,
        expected_require_exact_provider_json=False,
        output=output,
        tokenizer_snapshot_path=tokenizer_snapshot,
        expected_tokenizer_snapshot_sha256=tree.sha256,
    )

    value = json.loads(output.read_bytes())
    tokenizer = export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]
    assert rendered_snapshots == [
        export_preflight.TokenizerSnapshotBinding(
            path=tokenizer_snapshot,
            repository=tokenizer["repository"],
            revision=tokenizer["revision"],
            tree=tree,
        )
    ]
    assert value["schema_version"] == 2
    assert value["tokenizer_snapshot"] == {
        "local_files_only": True,
        "path": str(tokenizer_snapshot),
        "repository": tokenizer["repository"],
        "revision": tokenizer["revision"],
        "tree": tree.as_dict(),
        "trust_remote_code": False,
    }


def test_preflight_rejects_source_validation_expectation_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "export"
    root.mkdir()
    artifact = export_preflight.FileArtifact(1, "a" * 64)
    binding = export_preflight.ExportBinding(
        root=root,
        manifest=artifact,
        artifacts={},
        manifest_value={},
        source_validation={
            "max_sequence_tokens": 262_144,
            "require_clean_stop": True,
            "require_exact_provider_json": False,
            "require_model_io": True,
            "require_reasoning": True,
            "require_request_graph_match": True,
        },
        target_rendering=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT,
    )
    monkeypatch.setattr(export_preflight, "_load_export_binding", lambda *_args: binding)

    with pytest.raises(SFTPreflightError, match="^source_validation_expectation_mismatch$"):
        export_preflight.create_sft_preflight_attestation(
            export_root=root,
            expected_manifest_sha256="a" * 64,
            project_dir=tmp_path,
            expected_project_revision="c" * 40,
            expected_require_exact_provider_json=True,
            output=tmp_path / "preflight.json",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("require_reasoning", False),
        ("require_model_io", False),
        ("require_request_graph_match", False),
        ("require_clean_stop", False),
        ("require_exact_provider_json", 1),
        ("max_sequence_tokens", 1),
    ],
)
def test_attestation_rejects_invalid_source_validation_policy(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    attestation = _attestation(tmp_path / "export")
    attestation["source_validation"][field] = value

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


def test_training_start_loads_attested_tokenizer_snapshot_without_hub_fallback(
    tmp_path: Path,
    tokenizer_snapshot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "export"
    split = root / "train"
    split.mkdir(parents=True)
    attestation = _snapshot_attestation(root, tokenizer_snapshot)
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
    calls: list[tuple[tuple, dict]] = []

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return SyntheticTokenizer()

    monkeypatch.setattr(export_preflight.AutoTokenizer, "from_pretrained", staticmethod(load))

    tokenizer = export_preflight.load_attested_sft_tokenizer(config)

    assert isinstance(tokenizer, SyntheticTokenizer)
    assert tokenizer.pad_token_id == tokenizer.eos_token_id
    assert calls == [
        (
            (str(tokenizer_snapshot),),
            {"local_files_only": True, "trust_remote_code": False},
        )
    ]


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
        manifest_value={"counts": {"emitted_rows": 1, "train_rows": 1, "validation_rows": 0}},
        source_validation=attestation["source_validation"],
        target_rendering=export_preflight.EXPECTED_TARGET_RENDERING_CONTRACT,
    )
    monkeypatch.setattr(export_preflight, "_format_v3_root", lambda _data: root)
    monkeypatch.setattr(export_preflight, "_load_export_binding", lambda *_args: binding)
    monkeypatch.setattr(export_preflight, "_repository_provenance", lambda *_args: attestation["code"])
    monkeypatch.setattr(
        export_preflight,
        "_render_export",
        lambda _binding, _tokenizer_snapshot=None: attestation["rendering"],
    )

    assert export_preflight.validate_sft_training_preflight(config) is True

    changed_rendering = copy.deepcopy(attestation["rendering"])
    changed_rendering["rendered_tokens"] += 1
    monkeypatch.setattr(
        export_preflight,
        "_render_export",
        lambda _binding, _tokenizer_snapshot=None: changed_rendering,
    )
    with pytest.raises(SFTPreflightError, match="^attested_rendering_mismatch$"):
        export_preflight.validate_sft_training_preflight(config)

    monkeypatch.setattr(
        export_preflight,
        "_render_export",
        lambda _binding, _tokenizer_snapshot=None: attestation["rendering"],
    )
    changed_code = copy.deepcopy(attestation["code"])
    changed_code["source"][export_preflight.CODE_PATHS[0]] = {"bytes": 1, "sha256": "f" * 64}
    monkeypatch.setattr(export_preflight, "_repository_provenance", lambda *_args: changed_code)
    with pytest.raises(SFTPreflightError, match="^attested_code_changed$"):
        export_preflight.validate_sft_training_preflight(config)

    changed_source_validation = dict(binding.source_validation)
    changed_source_validation["require_exact_provider_json"] = True
    monkeypatch.setattr(
        export_preflight,
        "_load_export_binding",
        lambda *_args: replace(binding, source_validation=changed_source_validation),
    )
    with pytest.raises(SFTPreflightError, match="^attested_export_changed$"):
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
