#!/usr/bin/env python
"""Benchmark one inference node across prompt-concurrency levels."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-prompts", type=int, default=256)
    parser.add_argument("--samples-per-prompt", type=int, default=128)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[8, 16, 32, 64, 128, 256])
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--top-k", type=int, default=-1)
    parser.add_argument("--request-timeout-seconds", type=float, default=3600.0)
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def load_prompts(path: Path, limit: int) -> list[str]:
    prompts: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            question = f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question>"
            prompts.append(f"{question} <solution>")
            if len(prompts) == limit:
                break
    if len(prompts) != limit:
        raise ValueError(f"Expected {limit} prompts in {path}, found {len(prompts)}")
    return prompts


async def request(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    prompt: str,
    seed: int,
    args: argparse.Namespace,
) -> tuple[int, int]:
    async with semaphore:
        response = await client.completions.create(
            model=args.model,
            prompt=prompt,
            n=args.samples_per_prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            stop=["</answer>"],
            seed=seed,
            extra_body={"skip_special_tokens": False, "top_k": args.top_k},
        )
    if response.usage is None:
        raise RuntimeError("Inference response did not include token usage")
    if len(response.choices) != args.samples_per_prompt:
        raise RuntimeError(f"Expected {args.samples_per_prompt} choices, found {len(response.choices)}")
    return int(response.usage.completion_tokens), len(response.choices)


async def run_level(
    client: AsyncOpenAI,
    prompts: list[str],
    concurrency: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [request(client, semaphore, prompt, index, args) for index, prompt in enumerate(prompts)]
    completion_tokens = 0
    trajectories = 0
    started = time.perf_counter()
    completed = 0
    for task in asyncio.as_completed(tasks):
        tokens, choices = await task
        completion_tokens += tokens
        trajectories += choices
        completed += 1
        if completed % 32 == 0 or completed == len(tasks):
            print(f"concurrency={concurrency} completed={completed}/{len(tasks)}", flush=True)
    elapsed = time.perf_counter() - started
    return {
        "concurrency": concurrency,
        "elapsed_seconds": elapsed,
        "requests": len(prompts),
        "trajectories": trajectories,
        "completion_tokens": completion_tokens,
        "completion_tokens_per_second": completion_tokens / elapsed,
        "trajectories_per_second": trajectories / elapsed,
        "mean_completion_tokens": completion_tokens / trajectories,
    }


async def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.num_prompts < max(args.concurrency):
        raise ValueError("num_prompts must be at least the maximum concurrency")
    prompts = load_prompts(args.prompts, args.num_prompts)
    client = AsyncOpenAI(
        base_url=args.api_base_url,
        api_key="unused",
        timeout=args.request_timeout_seconds,
        max_retries=2,
    )
    try:
        await request(client, asyncio.Semaphore(1), prompts[0], 1_000_000, args)
        results = []
        payload = {
            "api_base_url": args.api_base_url,
            "model": args.model,
            "prompts": str(args.prompts.resolve()),
            "num_prompts_per_level": args.num_prompts,
            "samples_per_prompt": args.samples_per_prompt,
            "sampling": {
                "max_tokens": args.max_tokens,
                "temperature": args.temperature,
                "top_p": args.top_p,
                "top_k": args.top_k,
                "stop": ["</answer>"],
            },
            "results": results,
        }
        for concurrency in args.concurrency:
            result = await run_level(client, prompts, concurrency, args)
            results.append(result)
            write_json(args.output, payload)
            print(json.dumps(result, sort_keys=True), flush=True)
        payload["best_by_completion_tokens_per_second"] = max(
            results,
            key=lambda result: result["completion_tokens_per_second"],
        )
        write_json(args.output, payload)
        return payload
    finally:
        await client.close()


def main() -> None:
    args = parse_args()
    print(json.dumps(asyncio.run(benchmark(args)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
