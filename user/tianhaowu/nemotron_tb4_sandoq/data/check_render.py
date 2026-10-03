"""Verify the nemotron-3 renderer on an SFT JSONL through the exact SFTDataset._process path.

For every row checks that each assistant thinking part, text part and tool-call
argument appears inside the loss-masked (trained) token span, that no system/user/tool
text is trained, and reports token-length statistics against a sequence length.
"""

import argparse
import json
import statistics

from datasets import load_dataset
from renderers.base import create_renderer
from renderers.configs import Nemotron3RendererConfig
from transformers import AutoTokenizer

from prime_rl.configs.sft import LossMaskConfig
from prime_rl.trainer.sft.data import SFTDataset


def trained_spans(input_ids: list[int], loss_mask: list[bool]) -> list[tuple[int, int]]:
    spans, start = [], None
    for i, m in enumerate(loss_mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(loss_mask)))
    return spans


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--seq-len", type=int, default=262144)
    parser.add_argument("--dump", type=int, default=1, help="print decoded head of N rows")
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
    dataset = load_dataset("json", data_files=args.data, split="train")
    sft = SFTDataset(
        dataset, tokenizer, shuffle=False, seq_len=args.seq_len, loss_mask_config=LossMaskConfig(), renderer=renderer
    )

    lengths, trained_counts, problems, overlength = [], [], [], []
    for idx, example in enumerate(dataset):
        processed = sft._process(dict(example))
        if processed is None:
            problems.append((idx, "row skipped by _process"))
            continue
        # loss_mask is aligned with target_ids (inputs shifted left by one)
        ids, mask = processed["target_ids"], processed["loss_mask"]
        lengths.append(len(ids))
        if len(ids) > args.seq_len:
            overlength.append((idx, example.get("trace_id"), len(ids)))
        trained_counts.append(sum(mask))
        trained_text = "\n".join(tokenizer.decode(ids[a:b]) for a, b in trained_spans(ids, mask))
        untrained_text = tokenizer.decode([t for t, m in zip(ids, mask) if not m])

        for message in example["messages"]:
            texts = [message.get("reasoning_content") or "", message["content"] or ""]
            # Assistant turns marked trainable=false (context-only) must stay out of the loss.
            if message["role"] == "assistant" and message.get("trainable") is not False:
                for text in texts:
                    probe = text.strip()[:200]
                    if probe and probe not in trained_text:
                        problems.append((idx, f"assistant part not trained: {probe[:80]!r}"))
                for call in message.get("tool_calls") or []:
                    arguments = json.loads(call["function"]["arguments"])
                    for value in arguments.values():
                        probe = str(value).strip()[:120]
                        if probe and probe not in trained_text:
                            problems.append((idx, f"tool-call arg not trained: {probe[:80]!r}"))
            else:
                for text in texts:
                    probe = text.strip()[:200]
                    if probe and probe not in untrained_text:
                        problems.append((idx, f"{message['role']} text missing from prompt tokens: {probe[:80]!r}"))
                    if len(probe) > 40 and probe in trained_text:
                        problems.append((idx, f"{message['role']} text is trained: {probe[:80]!r}"))

        if idx < args.dump:
            print(f"--- row {idx} decoded head (trained spans wrapped in [[ ]]) ---")
            out, pos = [], 0
            for a, b in trained_spans(ids, mask):
                out.append(tokenizer.decode(ids[pos:a]))
                out.append("[[" + tokenizer.decode(ids[a:b]) + "]]")
                pos = b
            print("".join(out)[:6000])

    over = sum(length > args.seq_len for length in lengths)
    print(
        f"rows={len(dataset)} processed={len(lengths)} min={min(lengths)} "
        f"p50={int(statistics.median(lengths))} max={max(lengths)} total={sum(lengths)} "
        f"trained_tokens={sum(trained_counts)} over_seq_len({args.seq_len})={over}"
    )
    for idx, trace_id, length in overlength:
        print(f"   over seq_len: row {idx} {trace_id} {length} tokens")
    print(f"problems={len(problems)}")
    for problem in problems[:40]:
        print("  ", problem)


if __name__ == "__main__":
    main()
