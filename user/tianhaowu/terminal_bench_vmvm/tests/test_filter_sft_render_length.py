from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import filter_sft_render_length as length_filter
from prime_rl.trainer.sft import export_preflight as preflight


class FakeRenderer:
    def render(self, messages, *, tools):
        del tools
        size = 11 if messages[0]["content"] == "drop" else 5
        return SimpleNamespace(
            token_ids=list(range(size)),
            message_indices=[0] * size,
            sampled_mask=[True] * size,
        )


def row(content: str) -> bytes:
    value = {
        "messages": [
            {
                "content": content,
                "finish_reason": "stop",
                "reasoning_content": "reasoning",
                "role": "assistant",
                "trainable": True,
            }
        ],
        "target_assistant_message_index": 0,
        "task_id": "a" * 64,
        "tools": [
            {
                "function": {"description": "shell", "name": "bash", "parameters": {"type": "object"}},
                "type": "function",
            }
        ],
    }
    return json.dumps(value, sort_keys=True).encode() + b"\n"


def artifact(path: Path) -> preflight.FileArtifact:
    body = path.read_bytes()
    return preflight.FileArtifact(len(body), hashlib.sha256(body).hexdigest())


def test_filter_split_omits_only_overlength_rows_and_preserves_task(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_bytes(row("keep") + row("drop"))
    source.chmod(0o600)

    summary = length_filter._filter_split(
        source=source,
        destination=destination,
        expected=artifact(source),
        tokenizer=object(),
        renderer=FakeRenderer(),
        max_tokens=10,
    )

    assert destination.read_bytes() == row("keep")
    assert summary.as_dict() == {
        "source_rows": 2,
        "retained_rows": 1,
        "rejected_rows": 1,
        "source_tasks": 1,
        "retained_tasks": 1,
        "max_retained_tokens": 5,
        "min_rejected_tokens": 11,
        "max_rejected_tokens": 11,
    }


def test_filter_split_fails_if_a_task_loses_every_row(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_bytes(row("drop"))
    source.chmod(0o600)

    with pytest.raises(length_filter.FilterError, match="task_coverage_lost"):
        length_filter._filter_split(
            source=source,
            destination=destination,
            expected=artifact(source),
            tokenizer=object(),
            renderer=FakeRenderer(),
            max_tokens=10,
        )
