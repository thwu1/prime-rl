"""Catalog EVERY divergence between the TRAIN-path parser (renderers.parse_qwen35)
and the EVAL-path parsers (vLLM qwen3_coder tool + qwen3 reasoning) over real
decoded completions. Reuses the validated parsing/comparison logic in
``parser_diff.py`` verbatim; adds per-divergence recording + named-category
classification so we can report count + raw excerpt + both parsers' outputs.

  ENVPY=/home/tianhaowu/.cache/uv/environments-v2/prime-rl-cp3.12.13-bf20d6dff5119af9/bin/python
  $ENVPY user/tianhaowu/fair-sc-3/scripts/parser_diff_catalog.py --limit 400
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any

import parser_diff as pd


def classify(train: pd.NormResult, eval_: pd.NormResult, fields: dict[str, bool]) -> str:
    """Assign a divergence to a single named category (most-specific first)."""
    t_calls = train.tool_calls
    e_calls = eval_.tool_calls

    # Parser raised.
    if not fields["no_error"]:
        who = []
        if train.error:
            who.append("train")
        if eval_.error:
            who.append("eval")
        return f"parser-error ({'+'.join(who) or '?'})"

    # Tool-call cardinality / presence mismatches.
    if len(t_calls) != len(e_calls):
        if len(t_calls) > 0 and len(e_calls) == 0:
            return "tool_call-detected-by-train-only"
        if len(e_calls) > 0 and len(t_calls) == 0:
            return "tool_call-detected-by-eval-only"
        return "multi-toolcall-count-differ"

    # Same count of tool calls but they differ in name or args.
    if t_calls:
        for a, b in zip(t_calls, e_calls):
            if a.name != b.name:
                return "tool_call-name-differ"
        for a, b in zip(t_calls, e_calls):
            if a.args != b.args:
                # Distinguish structural arg diffs from pure whitespace-in-values.
                if set(a.args.keys()) != set(b.args.keys()):
                    return "args-keys-differ"
                # keys equal, values differ
                ws_only = True
                for k in a.args:
                    av, bv = a.args[k], b.args[k]
                    if isinstance(av, str) and isinstance(bv, str):
                        if av.strip() != bv.strip():
                            ws_only = False
                            break
                    elif av != bv:
                        ws_only = False
                        break
                return "args-values-whitespace" if ws_only else "args-values-differ"

    # Tool calls agree (or none) — text-field diffs.
    if not fields["reasoning"] and not fields["content"]:
        return "reasoning+content-both-differ"
    if not fields["reasoning"]:
        # was there a </think> boundary question?
        return "reasoning-boundary-differ"
    if not fields["content"]:
        # whitespace-normalized compare already ran; if still differ it's structural
        return "content-differ"

    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=pd.DEFAULT_DUMP)
    ap.add_argument("--tokenizer", default=pd.QWEN35_TOKENIZER)
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--out", default="/tmp/parser_diff_catalog.json")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)
    train_parser = pd.RendererParser(tok)
    eval_parser = pd.VllmParser(tok)

    n = 0
    matches = 0
    n_with_tools = 0
    n_parse_err_scaffold = 0  # the known closing-only scaffold failure mode
    cats: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for rid, ni, completion_ids, full_ids in pd.iter_raw_completions(
        args.dump, args.limit
    ):
        raw_text = tok.decode(completion_ids, skip_special_tokens=False)
        prompt_text = tok.decode(full_ids, skip_special_tokens=False)
        tools = pd.extract_tools_from_prompt_text(prompt_text)

        train_res = train_parser.parse(completion_ids, tools)
        eval_res = eval_parser.parse(raw_text, tools)
        ok, fields = pd.compare(train_res, eval_res)

        n += 1
        if tools:
            n_with_tools += 1
        # known scaffold failure: closing-only tool tag, no <tool_call>, no </think>
        if "</tool_call>" in raw_text and "<tool_call>" not in raw_text:
            n_parse_err_scaffold += 1

        if ok:
            matches += 1
            continue

        cat = classify(train_res, eval_res, fields)
        cats[cat].append(
            {
                "id": rid,
                "node": ni,
                "raw": raw_text,
                "fields": fields,
                "train": train_res.as_dict(),
                "eval": eval_res.as_dict(),
            }
        )

    n_div = n - matches
    print(f"\n=== parser_diff_catalog: qwen3.5 27b nopreserve step_0 ===")
    print(f"n_compared        : {n}")
    print(f"n_with_tools      : {n_with_tools}")
    print(f"n_matched         : {matches}")
    print(f"n_diverged        : {n_div}")
    print(f"scaffold(closing-only tool tag, no open): {n_parse_err_scaffold}")
    print(f"\ncategories:")
    for cat in sorted(cats, key=lambda c: -len(cats[c])):
        print(f"  {cat:38s}: {len(cats[cat])}")

    # dump full detail for downstream summarization
    detail = {
        "n_compared": n,
        "n_diverged": n_div,
        "n_with_tools": n_with_tools,
        "categories": {c: v for c, v in cats.items()},
    }
    with open(args.out, "w") as f:
        json.dump(detail, f, ensure_ascii=False)
    print(f"\nwrote detail -> {args.out}")

    # print one example per category
    for cat in sorted(cats, key=lambda c: -len(cats[c])):
        ex = cats[cat][0]
        print(f"\n--- CATEGORY {cat}  (count={len(cats[cat])}) ---")
        print(f"  id={ex['id']} node={ex['node']} fields={ex['fields']}")
        raw = ex["raw"]
        excerpt = raw if len(raw) <= 700 else raw[:350] + " ...[snip]... " + raw[-350:]
        print(f"  RAW   : {excerpt!r}")
        print(f"  TRAIN : {json.dumps(ex['train'], ensure_ascii=False)[:700]}")
        print(f"  EVAL  : {json.dumps(ex['eval'], ensure_ascii=False)[:700]}")


if __name__ == "__main__":
    main()
