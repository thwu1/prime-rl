"""Generate coaching rubrics for Terminal-Bench tasks.

Compares teacher (target) vs student trajectories to produce actionable rules
(interviewer-style hints) that guide the student model toward better approaches
without leaking the specific solution.

Two modes:
1. contrastive: teacher pass + student fail traces (best quality)
2. teacher_only: only teacher pass trace available (no student trace)
"""

import argparse
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

from agents.common.llm_engines.sr_client_model_utils import (
    extract_response_text,
    ModelName,
    request_api_raw,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============ Constants ============
# Token budget: ~200K tokens for prompt (two traces + template).
MAX_TOTAL_TRACE_CHARS = 600000  # total budget for both traces combined
MAX_TRACE_CHARS = 300000  # per-trace hard cap
MAX_TOOL_OUTPUT_CHARS = 8000
MAX_TOOL_OUTPUT_LINES = 100
MAX_ACTIONS_PER_TRACE = 200

# Custom IPNext tiers for internal models
CUSTOM_TIERS = {
    "kimi-k2.5": "smc.rift_lufang_kimi_76a8d6t",
}


# ============ LLM ============


async def get_llm_response(
    prompt: str,
    model_name: str,
    metagen_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    request_timeout: int = 600,
    max_retries: int = 3,
) -> str | None:
    """Call LLM with retry logic."""
    model_tier = CUSTOM_TIERS.get(model_name)
    if not model_tier and not metagen_key:
        metagen_key = os.environ.get("METAGEN_KEY")

    # MetaGen models: pass prompt as plain string
    # IPNext models: wrap as messages
    if metagen_key:
        content = prompt
    else:
        content = [{"role": 0, "prompt": [{"text": prompt}]}]

    for attempt in range(1 + max_retries):
        try:
            result = await request_api_raw(
                model_name=model_name,
                content=content,
                model_tier=model_tier,
                metagen_key=metagen_key,
                max_tokens=max_tokens,
                temperature=temperature,
                request_timeout=request_timeout,
            )
            text = extract_response_text(
                result,
                model_name=model_name,
                use_metagen=metagen_key is not None,
            )
            return text if text else None
        except Exception as e:
            error_msg = str(e)
            if (
                "ServiceOverloadedException" in error_msg
                or "active request limit" in error_msg
            ) and attempt < max_retries:
                delay = (2**attempt) + 0.5
                logger.warning(
                    f"Rate limited, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(delay)
                continue
            if attempt < max_retries:
                logger.warning(f"LLM call failed (attempt {attempt + 1}): {e}")
                await asyncio.sleep(1)
                continue
            logger.error(f"LLM call failed after {max_retries + 1} attempts: {e}")
            return None

    return None


# ============ Trace Processing ============

def _get_body_text(msg: dict) -> str:
    """Extract body text from a message."""
    content = msg.get("content", {})
    if isinstance(content, str):
        return content
    return content.get("body_text", "") or ""


def _get_recipient(msg: dict) -> str | None:
    """Extract recipient from a message."""
    recip = msg.get("recipient")
    if recip and isinstance(recip, dict):
        return recip.get("recipient")
    return recip if isinstance(recip, str) else None


def truncate_tool_output(output: str) -> str:
    """Truncate long tool outputs, keeping head and tail."""
    if not output:
        return ""
    if (
        len(output) <= MAX_TOOL_OUTPUT_CHARS
        and output.count("\n") < MAX_TOOL_OUTPUT_LINES
    ):
        return output
    lines = output.split("\n")
    if len(lines) > MAX_TOOL_OUTPUT_LINES:
        keep_head = MAX_TOOL_OUTPUT_LINES - 20
        result = (
            "\n".join(lines[:keep_head])
            + f"\n... [{len(lines) - MAX_TOOL_OUTPUT_LINES} lines truncated] ...\n"
            + "\n".join(lines[-20:])
        )
    else:
        result = output
    if len(result) > MAX_TOOL_OUTPUT_CHARS:
        keep_head = MAX_TOOL_OUTPUT_CHARS - 2000
        result = (
            result[:keep_head]
            + f"\n... [truncated at {MAX_TOOL_OUTPUT_CHARS} chars] ...\n"
            + result[-1000:]
        )
    return result


def extract_trace_entries(messages: list) -> list[dict]:
    """Extract interleaved thinking + action + tool output entries from TB messages.

    Returns list of dicts:
        - {"type": "thinking", "text": "..."} — assistant reasoning
        - {"type": "action", "tool": "...", "command": "...", "output": "..."} — tool call + result
    """
    entries = []
    skipped_initial_user = False

    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("author", {}).get("role", "")
        body = _get_body_text(msg)
        recipient = _get_recipient(msg)

        if role == "system":
            i += 1
            continue

        if role == "user" and not skipped_initial_user:
            skipped_initial_user = True
            i += 1
            continue

        if role == "assistant":
            if recipient and recipient not in ("user", "self"):
                # Tool call
                tool_name = recipient
                # Look ahead for tool result
                output = ""
                if i + 1 < len(messages):
                    next_msg = messages[i + 1]
                    next_role = next_msg.get("author", {}).get("role", "")
                    if next_role == "tool":
                        output = truncate_tool_output(_get_body_text(next_msg))
                        i += 1  # consume the tool result

                entries.append(
                    {
                        "type": "action",
                        "tool": tool_name,
                        "command": body[:500] if body else "",
                        "output": output,
                    }
                )
            else:
                # Thinking / reasoning
                if body.strip():
                    entries.append({"type": "thinking", "text": body.strip()})
        elif role == "tool":
            # Orphan tool result (shouldn't happen often)
            pass

        i += 1

    return entries


def summarize_trace(entries: list[dict], label: str, resolved: bool) -> str:
    """Produce a detailed summary of a trace for the LLM prompt."""
    action_entries = [e for e in entries if e["type"] == "action"]
    thinking_entries = [e for e in entries if e["type"] == "thinking"]

    total_thinking_chars = sum(len(e["text"]) for e in thinking_entries)

    # Compute stats
    commands = [e.get("command", "") for e in action_entries]
    n_bash = sum(
        1
        for e in action_entries
        if "bash" in e.get("tool", "").lower() or "exec" in e.get("tool", "").lower()
    )
    n_total = len(action_entries)

    sections = [
        f"### {label}",
        f"- Resolved: {'YES' if resolved else 'NO'}",
        f"- Total actions: {n_total}",
        f"- Bash commands: {n_bash}",
        f"- Thinking blocks: {len(thinking_entries)} ({total_thinking_chars:,} chars)",
        "- Trace (actions, outputs, and agent thinking):",
    ]

    # Apply action limit
    if n_total > MAX_ACTIONS_PER_TRACE:
        kept = MAX_ACTIONS_PER_TRACE // 2
        action_indices_to_keep = set(range(kept)) | set(range(n_total - kept, n_total))
    else:
        action_indices_to_keep = set(range(n_total))

    action_idx = 0
    inserted_ellipsis = False
    for entry in entries:
        if entry["type"] == "thinking":
            # Include thinking if adjacent to kept actions
            if (
                action_idx in action_indices_to_keep
                or (action_idx - 1) in action_indices_to_keep
            ):
                for line in entry["text"].split("\n")[:50]:  # cap thinking lines
                    sections.append(f"    [THINKING] {line}")
        elif entry["type"] == "action":
            if action_idx in action_indices_to_keep:
                tool = entry.get("tool", "?")
                cmd = entry.get("command", "")[:200]
                sections.append(f"    > [{tool}] {cmd}")
                if entry.get("output"):
                    for line in entry["output"].split("\n"):
                        sections.append(f"      {line}")
            elif not inserted_ellipsis:
                sections.append(
                    f"    ... ({n_total - MAX_ACTIONS_PER_TRACE} more actions) ..."
                )
                inserted_ellipsis = True
            action_idx += 1

    summary = "\n".join(sections)
    if len(summary) > MAX_TRACE_CHARS:
        summary = summary[:MAX_TRACE_CHARS] + "\n...[trace summary truncated]"
    return summary


# ============ Prompt Templates ============

_TB_COACHING_RUBRIC_INSTRUCTION = """\
7. **Write rubrics like hints from an interviewer.** Each rule should nudge the agent \
toward the right approach WITHOUT leaking the specific solution. Think of it as: \
the interviewer knows the answer, and gives a general hint that makes the agent more likely \
to arrive at the correct solution themselves.
   - BAD (too specific): "Run `make` with the `-j4` flag to fix the build"
   - GOOD (general hint): "When a build fails, check whether parallelism flags or \
environment variables affect the compilation process"
   - Rules should be phrased as INSTRUCTIONS the agent can follow on future problems.
8. Use the agent's THINKING text (shown as [THINKING] blocks) to understand WHERE \
the agent's reasoning went wrong. Identify decision points where the failing agent diverged.
9. **Focus on the failing agent's deficiencies.** Generate at most 1 rubric where \
the failing agent did well. All other rubrics should capture behaviors it got wrong.
10. **NEVER mention agent names or model names in the rubrics.** Use "the agent", \
"the successful agent", "the failing agent", or imperative form instead.
11. **Keep rules general — do NOT reference specific file names, function names, or \
line numbers from the traces.** Describe behavioral patterns abstractly.
12. **The rubric should NOT reveal the correct solution.** Guide the agent's process \
and reasoning strategy instead."""

_TB_RUBRIC_FIELD_DESCRIPTIONS = """\
Each rubric is a dict with these required fields:
- `name`: UPPER_SNAKE_CASE identifier as an imperative instruction (e.g., VERIFY_ENVIRONMENT_BEFORE_CODING)
- `category`: one of exploration, implementation, testing, debugging, strategy
- `description`: Actionable rule the agent should follow. Phrase as an instruction.
- `when`: What situation triggers this rule.
- `positive`: What the successful agent did (behavioral pattern).
- `negative`: What the failing agent did (behavioral pattern to avoid).
- `evidence`: Specific evidence from the traces showing the contrast.
- `verdict`: "yes", "no", or "partial" followed by " — " and explanation."""

CONTRASTIVE_PROMPT = (
    """\
You are an expert software engineer analyzing two agent trajectories on the same \
terminal-based task. One agent (the teacher) succeeded, the other (the student) failed. \
Your job is to extract actionable coaching rules by comparing their approaches.

## Task

Produce a structured analysis. Pay special attention to:
1. Extract **actionable rules** from the contrast between the two approaches.
2. For each rubric, provide Evidence BEFORE Verdict (chain-of-thought: reason before judging).
3. Generate 3-6 general rubrics and 1-3 problem-specific rubrics.
4. Focus on knowledge or strategies the teacher uses that the student lacks — \
things like domain expertise, tool usage patterns, debugging strategies, \
environment setup, or reading documentation.
5. Identify if the teacher uses specific **domain knowledge** (e.g., knowing which \
package to install, understanding a file format, knowing a command-line tool) \
that the student doesn't have.
6. DO NOT mention specific agent names or model names anywhere.
"""
    + _TB_COACHING_RUBRIC_INSTRUCTION
    + """

## Category Definitions
- `exploration`: How the agent navigates the codebase and understands the problem.
- `implementation`: How the agent writes code or modifies files.
- `testing`: How the agent validates its work.
- `debugging`: How the agent diagnoses and fixes errors.
- `strategy`: High-level approach, planning, and decision-making.

## Task Description
{instruction}

## Teacher Trace (PASSED — resolve rate: {target_rate:.0%})
{teacher_trace}

## Student Trace (FAILED — resolve rate: {student_rate:.0%})
{student_trace}

---

## Output Template — follow this EXACTLY:

## Outcome Summary
- Teacher: PASS (resolve rate {target_rate:.0%})
- Student: FAIL (resolve rate {student_rate:.0%})

## Key Differences
[What are the most important differences in approach? What knowledge or strategies \
does the teacher have that the student lacks?]

## Domain Knowledge Gaps
[Does the teacher use specific domain knowledge, tool expertise, or technical \
understanding that the student is missing? Be specific about what knowledge would help.]

## RL Steering Rubrics

Output rubrics as a JSON code block wrapped in `<rubrics>` tags. The JSON must be a dict \
with two keys: `general_rules` (3-6 rubrics) and `problem_specific` (1-3 rubrics).

"""
    + _TB_RUBRIC_FIELD_DESCRIPTIONS
    + """

<rubrics>
```json
{{
  "general_rules": [
    {{
      "name": "RULE_NAME_AS_IMPERATIVE_INSTRUCTION",
      "category": "exploration|implementation|testing|debugging|strategy",
      "description": "Actionable hint (do NOT leak the solution): ...",
      "when": "...",
      "positive": "What the successful agent did: ...",
      "negative": "What the failing agent did: ...",
      "evidence": "...",
      "verdict": "no — ..."
    }}
  ],
  "problem_specific": [
    {{
      "name": "RULE_NAME_AS_IMPERATIVE_INSTRUCTION",
      "category": "exploration|implementation|testing|debugging|strategy",
      "description": "Actionable hint (do NOT leak the solution): ...",
      "when": "...",
      "positive": "...",
      "negative": "...",
      "evidence": "...",
      "verdict": "no — ..."
    }}
  ]
}}
```
</rubrics>
"""
)

TEACHER_ONLY_PROMPT = (
    """\
You are an expert software engineer analyzing a successful agent trajectory on a \
terminal-based task. Extract reusable behavioral rules that a weaker agent should learn.

## Task

Produce coaching rubrics based on the successful approach. Focus on:
1. Non-obvious strategies and knowledge the agent uses.
2. Domain expertise or tool knowledge demonstrated.
3. Write each rule as an interviewer-style hint.
"""
    + _TB_COACHING_RUBRIC_INSTRUCTION
    + """

## Task Description
{instruction}

## Successful Agent Trace (resolve rate: {target_rate:.0%})
{teacher_trace}

---

## Output Template:

## Key Behaviors
[What strategies and knowledge does the agent demonstrate?]

## RL Steering Rubrics

<rubrics>
```json
{{
  "general_rules": [...],
  "problem_specific": [...]
}}
```
</rubrics>

"""
    + _TB_RUBRIC_FIELD_DESCRIPTIONS
)


# ============ Rubric Parsing ============


def parse_rubrics(response_text: str) -> dict | None:
    """Parse <rubrics>...</rubrics> JSON from LLM response."""
    match = re.search(
        r"<rubrics>\s*```json\s*(.*?)\s*```\s*</rubrics>", response_text, re.DOTALL
    )
    if not match:
        # Try without code fence
        match = re.search(r"<rubrics>\s*(.*?)\s*</rubrics>", response_text, re.DOTALL)
    if not match:
        logger.warning("No <rubrics> tags found in LLM response")
        return None

    rubrics_str = match.group(1).strip()
    try:
        return json.loads(rubrics_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse rubrics JSON: {e}")
        logger.debug(f"Raw: {rubrics_str[:500]}")
        return None


# ============ Core Processing ============


async def process_instance(
    record: dict,
    model_name: str,
    metagen_key: str | None,
    output_dir: Path,
    overwrite: bool = False,
) -> dict | None:
    """Process a single task: generate rubrics from teacher vs student comparison."""
    instance_id = record["instance_id"]
    rubric_dir = output_dir / "rubrics" / instance_id
    analysis_path = rubric_dir / "analysis.md"

    if analysis_path.exists() and not overwrite:
        logger.debug(f"Skipping {instance_id}: already exists")
        # Load existing
        try:
            text = analysis_path.read_text()
            rubrics = parse_rubrics(text)
            return {"instance_id": instance_id, "rubrics": rubrics, "cached": True}
        except Exception:
            pass

    instruction = record.get("instruction", "(no instruction)")

    # Extract and summarize traces
    target_traj = record.get("target_trajectory")
    student_traj = record.get("20b_trajectory")

    has_teacher = target_traj is not None and target_traj.get("conversation", {}).get(
        "messages"
    )
    has_student = student_traj is not None and student_traj.get("conversation", {}).get(
        "messages"
    )

    if has_teacher:
        teacher_entries = extract_trace_entries(target_traj["conversation"]["messages"])
        teacher_summary = summarize_trace(
            teacher_entries,
            "Teacher Agent (PASSED)",
            target_traj.get("resolved", True),
        )
    else:
        logger.warning(f"No teacher trace for {instance_id}")
        return None

    if has_student:
        student_entries = extract_trace_entries(
            student_traj["conversation"]["messages"]
        )
        student_summary = summarize_trace(
            student_entries,
            "Student Agent (FAILED)",
            student_traj.get("resolved", False),
        )

    # Choose prompt template
    target_rate = record.get("target_rate", 1.0)
    student_rate = record.get("20b_rate", 0.0)

    if has_teacher and has_student:
        mode = "contrastive"
        prompt = CONTRASTIVE_PROMPT.format(
            instruction=instruction[:10000],
            teacher_trace=teacher_summary,
            student_trace=student_summary,
            target_rate=target_rate,
            student_rate=student_rate,
        )
    else:
        mode = "teacher_only"
        prompt = TEACHER_ONLY_PROMPT.format(
            instruction=instruction[:10000],
            teacher_trace=teacher_summary,
            target_rate=target_rate,
        )

    # Enforce total trace budget
    if len(prompt) > MAX_TOTAL_TRACE_CHARS + 50000:  # 50K overhead for template
        logger.warning(
            f"{instance_id}: prompt too long ({len(prompt)} chars), truncating"
        )
        prompt = prompt[: MAX_TOTAL_TRACE_CHARS + 50000]

    # Call LLM
    start = time.time()
    response = await get_llm_response(
        prompt=prompt,
        model_name=model_name,
        metagen_key=metagen_key,
        max_tokens=8192,
        temperature=0.7,
    )
    latency = time.time() - start

    if response is None:
        logger.error(f"LLM returned None for {instance_id}")
        return None

    rubrics = parse_rubrics(response)

    # Write analysis.md
    rubric_dir.mkdir(parents=True, exist_ok=True)
    with open(analysis_path, "w") as f:
        f.write(f"# Rubrics: {instance_id}\n\n")
        f.write(f"Mode: {mode}\n")
        f.write(f"target rate: {target_rate:.0%} | 20B rate: {student_rate:.0%}\n")
        f.write(f"Latency: {latency:.1f}s\n\n")
        f.write(response)

    n_general = len(rubrics.get("general_rules", [])) if rubrics else 0
    n_specific = len(rubrics.get("problem_specific", [])) if rubrics else 0
    logger.info(
        f"  {instance_id}: {mode}, {n_general} general + {n_specific} specific rubrics, "
        f"{latency:.1f}s"
    )

    return {
        "instance_id": instance_id,
        "mode": mode,
        "rubrics": rubrics,
        "latency_s": round(latency, 1),
        "cached": False,
    }


# ============ Main ============


def main():
    parser = argparse.ArgumentParser(description="Generate TB coaching rubrics")
    parser.add_argument(
        "--input", required=True, help="Paired JSONL from compile_tb_hint_pairs.py"
    )
    parser.add_argument(
        "--output_dir", required=True, help="Output directory for rubrics"
    )
    parser.add_argument("--model", default="target-4-6-opus-genai", help="Model name")
    parser.add_argument("--metagen_key", default=None, help="MetaGen API key")
    parser.add_argument(
        "--num_workers", type=int, default=16, help="Concurrent LLM calls"
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit tasks (0=all)")
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing rubrics"
    )
    parser.add_argument(
        "--instance_ids", type=str, default="", help="Comma-separated IDs"
    )
    args = parser.parse_args()

    # Load paired JSONL
    records = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    logger.info(f"Loaded {len(records)} task pairs from {args.input}")

    # Filter by instance IDs if specified
    if args.instance_ids:
        ids = {x.strip() for x in args.instance_ids.split(",") if x.strip()}
        records = [r for r in records if r["instance_id"] in ids]
        logger.info(f"Filtered to {len(records)} tasks by instance_ids")

    if args.limit > 0:
        records = records[: args.limit]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"Processing {len(records)} tasks with model={args.model}, "
        f"workers={args.num_workers}"
    )

    # Process with async concurrency
    semaphore = asyncio.Semaphore(args.num_workers)
    results = []

    async def _process_with_semaphore(record):
        async with semaphore:
            return await process_instance(
                record, args.model, args.metagen_key, output_dir, args.overwrite
            )

    async def run_all():
        tasks = [_process_with_semaphore(r) for r in records]
        return await asyncio.gather(*tasks)

    all_results = asyncio.run(run_all())

    # Collect results
    success = 0
    failed = 0
    cached = 0
    for r in all_results:
        if r is None:
            failed += 1
        elif r.get("cached"):
            cached += 1
            success += 1
            results.append(r)
        else:
            success += 1
            results.append(r)

    # Write summary JSONL
    summary_path = output_dir / "rubrics_output.jsonl"
    with open(summary_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    logger.info("=" * 60)
    logger.info("RUBRIC GENERATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Success: {success} (cached: {cached})")
    logger.info(f"  Failed:  {failed}")
    logger.info(f"  Rubrics dir: {output_dir / 'rubrics'}")
    logger.info(f"  Summary: {summary_path}")
    logger.info("=" * 60)


if __name__ == "__main__":
    import fire

    fire.Fire(main)
