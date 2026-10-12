"""Lightweight helpers shared by format-v3 SFT loading and preflight."""

from typing import cast

from prime_rl.configs.sft import LossMaskConfig


def _drop_dataset_schema_nulls(value):
    if isinstance(value, dict):
        return {key: _drop_dataset_schema_nulls(value[key]) for key in sorted(value) if value[key] is not None}
    if isinstance(value, list):
        return [_drop_dataset_schema_nulls(item) for item in value if item is not None]
    return value


def _canonicalize_attested_messages(messages: object) -> list[dict]:
    if not isinstance(messages, list):
        raise ValueError("Format-v3 messages must be a list")
    normalized: list[dict] = []
    allowed = {
        "assistant": {"content", "finish_reason", "reasoning_content", "role", "tool_calls", "trainable"},
        "system": {"content", "role", "trainable"},
        "tool": {"content", "name", "role", "tool_call_id", "trainable"},
        "user": {"content", "role", "trainable"},
    }
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in allowed:
            raise ValueError("Format-v3 message is invalid")
        role = message["role"]
        if any(key not in allowed[role] and value is not None for key, value in message.items()):
            raise ValueError("Format-v3 message contains an unsupported field")
        normalized.append(
            {
                key: _drop_dataset_schema_nulls(value)
                for key, value in message.items()
                if key in allowed[role] and (value is not None or key in {"content", "finish_reason"})
            }
        )
    return normalized


def _canonicalize_attested_tools(tools: object) -> list[dict]:
    if not isinstance(tools, list):
        raise ValueError("Format-v3 tools must be a list")
    return [_drop_dataset_schema_nulls(tool) for tool in tools]


def _message_is_trainable(message: dict, config: LossMaskConfig) -> bool:
    role = message.get("role")
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError(f"Invalid message role: {role}")

    trainable = message.get("trainable")
    if trainable is not None:
        if not isinstance(trainable, bool):
            raise TypeError("Message trainable field must be a boolean")
        return trainable

    return cast(bool, getattr(config, role))
