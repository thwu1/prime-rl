"""Check that every captured TB4 model request renders exactly as the Nemotron SFT data did.

Rebuilds each outbound request from the delta-encoded `model_io` in results.jsonl, renders its
messages with the prime-rl nemotron-3 renderer (the SFT training configuration), and compares
the rendered prompt length with the provider-reported `usage.prompt_tokens`. A mismatch means
the served prompt differs from the training format (e.g. dropped historical reasoning).
"""

import argparse
import copy
import json

from renderers.base import create_renderer
from renderers.configs import Nemotron3RendererConfig
from transformers import AutoTokenizer

from prime_rl.utils.chat_template import deserialize_tool_calls


def rebuild_requests(nodes: list[dict]) -> dict[int, dict]:
    bodies: dict[int, dict] = {}
    for index, node in enumerate(nodes):
        model_io = node.get("model_io")
        if not model_io:
            continue
        request = model_io["request"]
        if request["kind"] == "delta":
            body = copy.deepcopy(bodies[request["base_node"]])
            for key in request["remove_fields"]:
                body.pop(key, None)
            body.update(request["set_fields"])
            for key, values in request["append_fields"].items():
                body.setdefault(key, []).extend(values)
        else:
            body = copy.deepcopy(request["body"])
        bodies[index] = body
    return bodies


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", help="results.jsonl from an eval run")
    parser.add_argument("--tokenizer", default="/checkpoint/ram/tianhaowu/models/NVIDIA-Nemotron-3-Super-120B-A12B-BF16")
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    renderer = create_renderer(
        tokenizer,
        Nemotron3RendererConfig(
            enable_thinking=True,
            preserve_all_thinking=True,
            truncate_history_thinking=False,
            normalize_tool_response_wrappers=False,
            ultra=False,
        ),
    )
    total = mismatched = 0
    for line in open(args.results):
        result = json.loads(line)
        nodes = result["nodes"]
        for index, body in rebuild_requests(nodes).items():
            usage = nodes[index]["model_io"]["response"]["body"].get("usage") or {}
            messages = []
            for message in body["messages"]:
                message = {k: v for k, v in message.items() if k != "provider_specific_fields"}
                if "reasoning" in message:
                    message["reasoning_content"] = message.pop("reasoning")
                messages.append(message)
            rendered = renderer.render(
                deserialize_tool_calls(messages), tools=body.get("tools"), add_generation_prompt=True
            ).token_ids
            served = usage.get("prompt_tokens")
            historical = sum(1 for m in body["messages"] if m.get("role") == "assistant")
            with_reasoning = sum(1 for m in body["messages"] if m.get("role") == "assistant" and m.get("reasoning"))
            total += 1
            ok = served == len(rendered)
            mismatched += not ok
            print(
                f"{result['task']['name']} node {index}: served={served} rendered={len(rendered)} "
                f"{'OK' if ok else 'MISMATCH'} (history assistant turns={historical}, with `reasoning`={with_reasoning})"
            )
    print(f"requests={total} mismatched={mismatched}")


if __name__ == "__main__":
    main()
