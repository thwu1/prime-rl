"""Compare the TRAIN-path parser (renderers.parse_qwen35) against the EVAL-path
parsers (vLLM qwen3_coder tool parser + qwen3 reasoning parser) on the SAME raw
model output, offline (no inference server).

Why: the train loop parses raw completion tokens client-side via
``renderers.parsing.parse_qwen35``; the eval loop parses via the vLLM
OpenAI-server tool/reasoning parsers configured in the run's ``inference.toml``
(``tool_call_parser="qwen3_coder"``, ``reasoning_parser="qwen3"``). If the two
disagree on ``{reasoning_content, content, tool_calls}`` the train/eval reward
signal and any parse-error penalty become inconsistent. This script finds where
they diverge on real completions decoded from a train rollout dump.

Run with the environment python that has vllm + renderers + transformers:
  ENVPY=/home/tianhaowu/.cache/uv/environments-v2/prime-rl-cp3.12.13-bf20d6dff5119af9/bin/python
  $ENVPY user/tianhaowu/fair-sc-3/scripts/parser_diff.py --limit 50

Parser invocation (verified against the pinned vLLM 0.22 source):
  TOOL (train):  parse_qwen35(tokenizer, completion_token_ids, stop_ids=..., think_id=...,
                 think_end_id=..., tool_call_id=..., tool_call_end_id=..., tools=<openai envelope>)
                 -> renderers.base.ParsedResponse(content, reasoning_content, tool_calls[ParsedToolCall])
  TOOL (eval):   ToolParserManager.get_tool_parser("qwen3_coder")(tokenizer, tools=[ChatCompletionToolsParam,...])
                 .extract_tool_calls(raw_text, ChatCompletionRequest(...))
                 -> ExtractedToolCallInformation(tools_called, tool_calls[ToolCall], content)
  REASON (eval): ReasoningParserManager.get_reasoning_parser("qwen3")(tokenizer)
                 .extract_reasoning(raw_text, request) -> (reasoning:str|None, content:str|None)
                 NB: the 0.22 method is ``extract_reasoning`` (NOT extract_reasoning_content),
                 and it returns a plain tuple, not a DeltaMessage.

The eval side splits reasoning first, then feeds the *content* remainder to the
tool parser — mirroring how the OpenAI serving layer chains reasoning_parser ->
tool_parser. The tool parser also strips the tool-call scaffold from the text it
returns as content, so eval "content" is the post-reasoning, pre-tool-call text.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from typing import Any

QWEN35_TOKENIZER = "/checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B"
DEFAULT_DUMP = (
    "/checkpoint/ram/tianhaowu/qwen35_27b_12k_100k_lr1e6_nopreserve/"
    "20260702-210909/run_default/rollouts/step_0/train_rollouts.jsonl"
)

# Stop tokens the model isn't supposed to generate past; the renderer parser
# truncates at these and the vLLM serving layer never shows them to its parsers.
STOP_TOKENS = ("<|im_end|>", "<|endoftext|>")

_TOOLS_BLOCK_RE = re.compile(r"<tools>(.*?)</tools>", re.DOTALL)


# ── normalized comparison shapes ────────────────────────────────────


@dataclass
class NormCall:
    name: str
    args: dict[str, Any]  # always a dict (JSON-decoded); {} when unparseable


@dataclass
class NormResult:
    reasoning_content: str | None
    content: str | None
    tool_calls: list[NormCall] = field(default_factory=list)
    error: str | None = None  # set when the parser raised

    def as_dict(self) -> dict[str, Any]:
        return {
            "reasoning_content": self.reasoning_content,
            "content": self.content,
            "tool_calls": [{"name": c.name, "args": c.args} for c in self.tool_calls],
            "error": self.error,
        }


# ── helpers ─────────────────────────────────────────────────────────


def _norm_text(s: str | None) -> str:
    """Compare text modulo trailing whitespace and None/empty equivalence."""
    if s is None:
        return ""
    return s.rstrip()


def _to_args_dict(arguments: Any) -> dict[str, Any]:
    """Coerce a tool-call ``arguments`` (dict OR json string OR None) to a dict."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        s = arguments.strip()
        if not s:
            return {}
        try:
            v = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return {"__raw__": arguments}
        return v if isinstance(v, dict) else {"__raw__": arguments}
    return {"__raw__": str(arguments)}


def _strip_trailing_stops(text: str) -> str:
    """Drop a trailing stop token from decoded raw text (server truncates it)."""
    out = text
    changed = True
    while changed:
        changed = False
        for stop in STOP_TOKENS:
            if out.endswith(stop):
                out = out[: -len(stop)]
                changed = True
    return out


def extract_tools_from_prompt_text(prompt_text: str) -> list[dict[str, Any]]:
    """Parse the OpenAI-envelope tool specs from a rendered ``<tools>`` block."""
    m = _TOOLS_BLOCK_RE.search(prompt_text)
    if not m:
        return []
    tools: list[dict[str, Any]] = []
    for line in m.group(1).strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tools.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return tools


# ── parser 1: TRAIN path (renderers.parse_qwen35) ───────────────────


class RendererParser:
    def __init__(self, tokenizer):
        from renderers.parsing import parse_qwen35  # noqa: F401 (import check)

        self._parse = parse_qwen35
        self._tok = tokenizer

        def tid(t: str) -> int:
            i = tokenizer.convert_tokens_to_ids(t)
            if i is None or i < 0:
                raise RuntimeError(f"token {t!r} not in tokenizer vocab")
            return i

        self._stop_ids = {tid("<|im_end|>"), tid("<|endoftext|>")}
        self._think = tid("<think>")
        self._think_end = tid("</think>")
        self._tc = tid("<tool_call>")
        self._tc_end = tid("</tool_call>")

    def parse(
        self, completion_ids: list[int], tools: list[dict[str, Any]] | None
    ) -> NormResult:
        from renderers.base import ToolCallParseStatus

        if not completion_ids:
            return NormResult(reasoning_content=None, content="", tool_calls=[])
        r = self._parse(
            self._tok,
            completion_ids,
            stop_ids=self._stop_ids,
            think_id=self._think,
            think_end_id=self._think_end,
            tool_call_id=self._tc,
            tool_call_end_id=self._tc_end,
            tools=tools,
        )
        calls: list[NormCall] = []
        for tc in r.tool_calls:
            # Match the RendererClient contract (from_native_response): only
            # tool calls with a name become real tool_calls; malformed/status
            # entries without a name are dropped (they surface as validation
            # messages, not tool calls).
            if not tc.name:
                continue
            calls.append(NormCall(name=tc.name, args=_to_args_dict(tc.arguments)))
        return NormResult(
            reasoning_content=r.reasoning_content,
            content=r.content,
            tool_calls=calls,
        )


# ── parser 2: EVAL path (vLLM qwen3 reasoning + qwen3_coder tool) ────


class VllmParser:
    def __init__(self, tokenizer):
        from vllm.reasoning import ReasoningParserManager
        from vllm.tool_parsers.abstract_tool_parser import ToolParserManager

        self._tok = tokenizer
        self._reason_cls = ReasoningParserManager.get_reasoning_parser("qwen3")
        self._tool_cls = ToolParserManager.get_tool_parser("qwen3_coder")
        # reasoning parser is stateless per-call for extract_reasoning; build once.
        self._reasoner = self._reason_cls(tokenizer)

    def _build_request(self, tools: list[dict[str, Any]] | None):
        from vllm.entrypoints.openai.chat_completion.protocol import (
            ChatCompletionRequest,
            ChatCompletionToolsParam,
        )

        tool_params = None
        if tools:
            tool_params = []
            for t in tools:
                # accept both flat {name,...} and {"type":"function","function":{...}}
                spec = t.get("function", t) if isinstance(t, dict) else None
                if not isinstance(spec, dict) or not spec.get("name"):
                    continue
                try:
                    tool_params.append(
                        ChatCompletionToolsParam.model_validate(
                            {"type": "function", "function": spec}
                        )
                    )
                except Exception:
                    continue
        req = ChatCompletionRequest(
            messages=[{"role": "user", "content": ""}],
            model="qwen35",
            tools=tool_params,
        )
        return req, tool_params

    def parse(
        self, raw_text: str, tools: list[dict[str, Any]] | None
    ) -> NormResult:
        text = _strip_trailing_stops(raw_text or "")
        req, tool_params = self._build_request(tools)

        # 1) reasoning split (server does reasoning_parser first)
        try:
            reasoning, content_after = self._reasoner.extract_reasoning(text, req)
        except Exception as e:  # noqa: BLE001 - report, don't crash the batch
            return NormResult(
                reasoning_content=None,
                content=None,
                error=f"reasoning: {type(e).__name__}: {e}",
            )

        tool_input = content_after if content_after is not None else ""

        # 2) tool parse on the post-reasoning remainder. Fresh instance per
        #    call: extract_tool_calls mutates streaming state (prev_tool_call_arr).
        tool_parser = self._tool_cls(self._tok, tools=tool_params)
        try:
            extracted = tool_parser.extract_tool_calls(tool_input, req)
        except Exception as e:  # noqa: BLE001
            return NormResult(
                reasoning_content=reasoning,
                content=tool_input,
                error=f"tool: {type(e).__name__}: {e}",
            )

        calls: list[NormCall] = []
        for tc in extracted.tool_calls or []:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", None) if fn is not None else None
            if not name:
                continue
            args = getattr(fn, "arguments", None)
            calls.append(NormCall(name=name, args=_to_args_dict(args)))

        # When tools fire, ExtractedToolCallInformation.content holds the
        # pre-tool-call text; otherwise it echoes the whole input.
        eval_content = extracted.content
        return NormResult(
            reasoning_content=reasoning,
            content=eval_content,
            tool_calls=calls,
        )


# ── comparison ──────────────────────────────────────────────────────


def compare(train: NormResult, eval_: NormResult) -> tuple[bool, dict[str, bool]]:
    """tool_calls must match on name+args; reasoning/content modulo trailing ws."""
    reasoning_ok = _norm_text(train.reasoning_content) == _norm_text(
        eval_.reasoning_content
    )
    content_ok = _norm_text(train.content) == _norm_text(eval_.content)

    tc_ok = len(train.tool_calls) == len(eval_.tool_calls)
    if tc_ok:
        for a, b in zip(train.tool_calls, eval_.tool_calls):
            if a.name != b.name or a.args != b.args:
                tc_ok = False
                break

    no_error = eval_.error is None and train.error is None
    match = reasoning_ok and content_ok and tc_ok and no_error
    return match, {
        "reasoning": reasoning_ok,
        "content": content_ok,
        "tool_calls": tc_ok,
        "no_error": no_error,
    }


# ── data loading: decode masked completion tokens from a train dump ──


def iter_raw_completions(dump_path: str, limit: int):
    """Yield (record_id, node_idx, completion_ids, tools) for sampled assistant
    nodes. ``completion_ids`` = the model's raw completion tokens (mask==True
    span); ``tools`` = OpenAI-envelope specs parsed from the rendered prompt.
    """
    yielded = 0
    with open(dump_path) as f:
        for line in f:
            if yielded >= limit:
                return
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rid = rec.get("id")
            for ni, node in enumerate(rec.get("nodes", [])):
                if yielded >= limit:
                    return
                if not node.get("sampled"):
                    continue
                tids = node.get("token_ids") or []
                mask = node.get("mask") or []
                if not tids or not mask or len(tids) != len(mask):
                    continue
                completion_ids = [t for t, m in zip(tids, mask) if m]
                if not completion_ids:
                    continue
                yield rid, ni, completion_ids, tids
                yielded += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DEFAULT_DUMP)
    ap.add_argument("--tokenizer", default=QWEN35_TOKENIZER)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--show", type=int, default=3, help="num divergences to print")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)
    train_parser = RendererParser(tok)
    eval_parser = VllmParser(tok)

    n = 0
    matches = 0
    field_fail = {"reasoning": 0, "content": 0, "tool_calls": 0, "no_error": 0}
    divergences: list[dict[str, Any]] = []

    for rid, ni, completion_ids, full_ids in iter_raw_completions(
        args.dump, args.limit
    ):
        raw_text = tok.decode(completion_ids, skip_special_tokens=False)
        prompt_text = tok.decode(full_ids, skip_special_tokens=False)
        tools = extract_tools_from_prompt_text(prompt_text)

        train_res = train_parser.parse(completion_ids, tools)
        eval_res = eval_parser.parse(raw_text, tools)
        ok, fields = compare(train_res, eval_res)

        n += 1
        if ok:
            matches += 1
        else:
            for k, v in fields.items():
                if not v:
                    field_fail[k] += 1
            if len(divergences) < args.show:
                divergences.append(
                    {
                        "id": rid,
                        "node": ni,
                        "raw_tail": raw_text[-400:],
                        "fields": fields,
                        "train": train_res.as_dict(),
                        "eval": eval_res.as_dict(),
                    }
                )

    print(f"\n=== parser_diff: qwen3.5 27b nopreserve step_0 ===")
    print(f"samples compared : {n}")
    print(f"match            : {matches}/{n} ({100.0 * matches / max(n, 1):.1f}%)")
    print(f"field disagreements (count of samples where field differed):")
    for k, v in field_fail.items():
        print(f"  {k:12s}: {v}")

    for i, d in enumerate(divergences):
        print(f"\n--- divergence {i + 1}  id={d['id']} node={d['node']} ---")
        print(f"  fields ok: {d['fields']}")
        print(f"  raw tail : {d['raw_tail']!r}")
        print(f"  TRAIN    : {json.dumps(d['train'], ensure_ascii=False)[:600]}")
        print(f"  EVAL     : {json.dumps(d['eval'], ensure_ascii=False)[:600]}")


if __name__ == "__main__":
    main()
