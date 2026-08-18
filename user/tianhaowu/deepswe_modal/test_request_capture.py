import json

from request_capture import canonicalize_chat_request


def test_canonicalize_chat_request_preserves_reasoning_through_router() -> None:
    body = json.dumps(
        {
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

    payload, forwarded, normalized = canonicalize_chat_request(body)

    assert normalized == 2
    assert payload["messages"][0]["reasoning"] == "deprecated alias"
    assert payload["messages"][1]["reasoning"] == "canonical"
    assert all("reasoning_content" not in message for message in payload["messages"])
    assert json.loads(forwarded) == payload
