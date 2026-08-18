import argparse
import copy
import importlib.metadata
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from minisweagent.exceptions import FormatError
from minisweagent.models.litellm_model import LitellmModel
from request_capture import canonical_messages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--log-path", type=Path, required=True)
    return parser.parse_args()


def post_json(url: str, payload: dict, api_key: str) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=180) as response:
        return json.load(response)


class CaptureServer(ThreadingHTTPServer):
    upstream: str
    api_key: str
    captures: list[dict]
    responses: list[dict]


class CaptureHandler(BaseHTTPRequestHandler):
    server: CaptureServer

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.captures.append(json.loads(body))
        request = urllib.request.Request(
            f"{self.server.upstream}{self.path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.server.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=180) as response:
                response_body = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as error:
            response_body = error.read()
            status = error.code
            content_type = error.headers.get("Content-Type", "application/json")

        try:
            response_payload = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response_payload = {}
        self.server.responses.append(response_payload if isinstance(response_payload, dict) else {})

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: object) -> None:
        return


def reasoning_text(message: dict) -> str:
    reasoning = message.get("reasoning") or message.get("reasoning_content")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise RuntimeError(f"Nemotron response did not contain reasoning: {message}")
    return reasoning


def query_tool_turn(
    model: LitellmModel,
    messages: list[dict],
    turn: int,
    max_attempts: int = 4,
) -> tuple[dict, int]:
    for attempt in range(max_attempts):
        try:
            return model.query(messages, seed=attempt), attempt
        except FormatError:
            if attempt + 1 == max_attempts:
                raise
            print(
                f"Thinking preflight turn {turn}: malformed tool call on attempt {attempt + 1}, retrying",
                flush=True,
            )
    raise RuntimeError("unreachable")


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    api_key = os.environ["OPENAI_API_KEY"]
    chat_template_kwargs = {
        "enable_thinking": True,
        "truncate_history_thinking": False,
    }

    server = CaptureServer(("127.0.0.1", 0), CaptureHandler)
    server.upstream = base_url
    server.api_key = api_key
    server.captures = []
    server.responses = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        model = LitellmModel(
            model_name=f"openai/{args.model_name}",
            cost_tracking="ignore_errors",
            model_kwargs={
                "api_base": f"http://127.0.0.1:{server.server_address[1]}/v1",
                "api_key": api_key,
                "custom_llm_provider": "openai",
                "drop_params": True,
                "max_tokens": 512,
                "seed": 0,
                "temperature": 1.0,
                "top_p": 0.95,
                "tool_choice": "required",
                "extra_body": {
                    "top_k": 20,
                    "chat_template_kwargs": chat_template_kwargs,
                },
            },
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a tool-use preflight. Think before every action and always call bash exactly once."
                ),
            },
            {
                "role": "user",
                "content": "Call bash exactly once with command printf turn-one-ok.",
            },
        ]
        turns = []
        responses = []
        for turn in range(1, 4):
            response, format_retries = query_tool_turn(model, messages, turn)
            reasoning = reasoning_text(response)
            tool_calls = response.get("tool_calls") or []
            if len(tool_calls) != 1:
                raise RuntimeError(f"Nemotron turn {turn} did not call bash exactly once: {response}")
            captured_request = server.captures[-1]
            api_response = server.responses[-1]
            turns.append(
                {
                    "turn": turn,
                    "format_retries": format_retries,
                    "outgoing_request": captured_request,
                    "response": {key: value for key, value in response.items() if key != "extra"},
                    "api_usage": api_response.get("usage"),
                    "reasoning_chars": len(reasoning),
                }
            )
            responses.append(response)
            print(
                f"Thinking preflight turn {turn}: "
                f"reasoning_chars={len(reasoning)} "
                f"request_messages={len(captured_request['messages'])}",
                flush=True,
            )
            if turn < 3:
                messages.append(response)
                output = {
                    "output": f"turn-{turn}-ok",
                    "returncode": 0,
                    "exception_info": "",
                }
                messages.extend(model.format_observation_messages(response, [output]))
                messages.append(
                    {
                        "role": "user",
                        "content": (f"Call bash exactly once with command printf turn-{turn + 1}-ok."),
                    }
                )

        final_request = turns[-1]["outgoing_request"]
        if final_request.get("chat_template_kwargs") != chat_template_kwargs:
            raise RuntimeError(
                "LiteLLM did not forward the required chat template kwargs: "
                f"{final_request.get('chat_template_kwargs')}"
            )

        prior_assistant_messages = [
            message for message in final_request["messages"] if message.get("role") == "assistant"
        ]
        preserved = []
        for turn, (response, forwarded_message) in enumerate(
            zip(responses[:2], prior_assistant_messages, strict=True),
            start=1,
        ):
            reasoning = reasoning_text(response)
            forwarded_reasoning = reasoning_text(forwarded_message)
            if forwarded_reasoning != reasoning:
                raise RuntimeError(f"mini-swe changed reasoning from turn {turn}")
            preserved.append(
                {
                    "turn": turn,
                    "reasoning": reasoning,
                    "exactly_forwarded_by_mini_swe": True,
                }
            )

        render_payload = copy.deepcopy(final_request)
        render_payload["messages"] = canonical_messages(final_request["messages"])
        render_response = post_json(
            f"{base_url}/v1/chat/completions/render",
            render_payload,
            api_key,
        )
        rendered_tokens = render_response.get("token_ids")
        if not isinstance(rendered_tokens, list):
            raise RuntimeError("vLLM render response did not contain token_ids")
        actual_usage = turns[-1].get("api_usage")
        actual_prompt_tokens = actual_usage.get("prompt_tokens") if isinstance(actual_usage, dict) else None
        if actual_prompt_tokens != len(rendered_tokens):
            raise RuntimeError(
                "router changed the rendered chat prompt: "
                f"chat usage={actual_prompt_tokens}, render={len(rendered_tokens)}"
            )
        rendered_prompt = post_json(
            f"{base_url}/detokenize",
            {
                "model": args.model_name,
                "tokens": rendered_tokens,
            },
            api_key,
        )["prompt"]
        for item in preserved:
            if item["reasoning"].strip() not in rendered_prompt:
                raise RuntimeError(f"vLLM rendered prompt dropped reasoning from turn {item['turn']}")
            item["present_in_vllm_rendered_prompt"] = True

        args.log_path.parent.mkdir(parents=True, exist_ok=True)
        args.log_path.write_text(
            json.dumps(
                {
                    "mini_swe_version": importlib.metadata.version("mini-swe-agent"),
                    "model": args.model_name,
                    "chat_template_kwargs": chat_template_kwargs,
                    "turns": turns,
                    "preserved_prior_reasoning": preserved,
                    "rendered_tokens": len(rendered_tokens),
                    "chat_usage_prompt_tokens": actual_prompt_tokens,
                    "rendered_prompt": rendered_prompt,
                },
                indent=2,
            )
        )
        print(
            "Thinking preflight passed: mini-swe forwarded both prior reasoning "
            "turns and vLLM rendered both into turn 3",
            flush=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
