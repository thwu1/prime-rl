import json

from request_capture import CaptureServer, canonicalize_chat_request, is_context_window_exhaustion
from submit_eval import mini_swe_config


def test_canonicalize_chat_request_preserves_reasoning_through_router() -> None:
    body = json.dumps(
        {
            "model": "deepswe-job-alias",
            "messages": [
                {
                    "role": "assistant",
                    "reasoning_content": "deprecated alias",
                    "tool_calls": [],
                },
                {
                    "role": "assistant",
                    "reasoning": "canonical",
                    "reasoning_content": "ignored alias",
                    "tool_calls": [],
                },
            ]
        }
    ).encode()

    payload, forwarded, normalized = canonicalize_chat_request(
        body,
        upstream_model="nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16",
    )

    assert normalized == 2
    assert payload["model"] == "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
    assert payload["messages"][0]["reasoning"] == "deprecated alias"
    assert payload["messages"][1]["reasoning"] == "canonical"
    assert all("reasoning_content" not in message for message in payload["messages"])
    assert json.loads(forwarded) == payload


def test_capped_eval_uses_noninteractive_agent() -> None:
    assert "agent_class: default" in mini_swe_config(100)
    assert "agent_class: default" not in mini_swe_config(None)


def test_failed_context_request_does_not_replace_latest_success(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    summary_path = tmp_path / "capture.jsonl"
    server = CaptureServer(
        ("127.0.0.1", 0),
        upstream="http://unused",
        upstream_model=None,
        latest_dir=latest_dir,
        summary_path=summary_path,
    )
    try:
        successful_payload = {
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "task"},
            ],
            "chat_template_kwargs": {
                "enable_thinking": True,
                "truncate_history_thinking": False,
            },
        }
        successful = server.capture_request(successful_payload, 0)
        server.capture_response(successful, 200, b'{"usage":{"prompt_tokens":1}}')

        oversized_payload = {
            **successful_payload,
            "messages": [
                *successful_payload["messages"],
                {"role": "assistant", "reasoning": "prior reasoning"},
                {"role": "tool", "content": "large observation"},
            ],
        }
        oversized = server.capture_request(oversized_payload, 0)
        error = {
            "error": {
                "message": (
                    "The prompt is 262145 tokens, which exceeds the model's maximum "
                    "context length of 262144 tokens."
                ),
                "param": "input_tokens",
            }
        }
        server.capture_response(oversized, 400, json.dumps(error).encode())
    finally:
        server.server_close()

    key = successful["task_key"]
    assert json.loads((latest_dir / f"{key}.json").read_text()) == successful_payload
    summaries = [json.loads(line) for line in summary_path.read_text().splitlines()]
    assert is_context_window_exhaustion(summaries[-1])
