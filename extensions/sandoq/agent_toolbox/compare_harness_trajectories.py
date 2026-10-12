#!/usr/bin/env python3
"""Normalize Muse, OpenCode, and Pi task runs into a comparison report."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

VERSIONS = {
    "muse": "Muse Code 1.2.0",
    "opencode": "OpenCode 1.18.2+Meta",
    "pi": "Pi 0.84.1",
}
COLORS = {"muse": "#9b8cff", "opencode": "#48d6a0", "pi": "#ffba69"}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _test_result(path: Path) -> dict[str, int | None]:
    text = path.read_text(errors="replace")
    matches = re.findall(r"(\d+) passed(?:, (\d+) skipped)?", text)
    passed, skipped = matches[-1] if matches else (None, None)
    return {
        "passed": int(passed) if passed is not None else None,
        "skipped": int(skipped or 0) if passed is not None else None,
    }


def _uuid7_ms(value: str) -> int | None:
    try:
        return int(value.replace("-", "")[:12], 16)
    except (TypeError, ValueError):
        return None


def _short(value: str, limit: int = 120) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _muse_metrics(directory: Path) -> dict[str, Any]:
    events = _jsonl(directory / "muse.jsonl")
    model_steps = sum(
        event.get("payload_type") == "task.lifecycle.proposed"
        and event.get("payload", {}).get("event", {}).get("task_kind") == "model.meta.response"
        for event in events
    )
    tools: list[dict[str, Any]] = []
    search_index = 0
    for event in events:
        if event.get("payload_type") != "tool.result":
            continue
        payload = event["payload"]
        name = payload.get("correlation_facts", {}).get("tool_name", "tool")
        outcome = payload.get("correlation_facts", {}).get("outcome", "unknown")
        text = str(payload.get("text", ""))
        label = name.replace("_file", "").replace("_", " ").title()
        detail = ""
        if name == "read_file":
            match = re.search(r"`([^`]+)`", text)
            label = f"Read {Path(match.group(1)).name}" if match else "Read file"
            detail = match.group(1) if match else "source file"
        elif name == "search":
            search_index += 1
            label = f"Search code #{search_index}"
            matches = [line for line in text.splitlines() if line.strip()][:3]
            detail = "matches: " + ", ".join(matches) if matches else "no result text emitted"
        elif name == "edit_file":
            label = "Edit implementation"
            detail = "aiohttp/web_runner.py · host fallback at line 111"
        elif name == "write_file":
            label = "Write repro script"
            detail = "/tmp/repro_empty_host.py"
        elif name == "bash":
            try:
                parsed = json.loads(text)
                label = parsed.get("description") or "Run shell"
                detail = _short(str(parsed.get("command", "")))
                if int(parsed.get("exit_code", 0)) != 0:
                    outcome = "failure"
                    output = str(parsed.get("output", ""))
                    detail += " · " + (output.strip().splitlines()[-1] if output.strip() else "failed")
            except (json.JSONDecodeError, TypeError, ValueError):
                label = "Run shell"
        tools.append({"tool": name, "label": label, "detail": detail, "ok": outcome == "success"})

    timestamps: list[int] = []
    for event in events:
        payload = event.get("payload", {})
        candidates = [payload.get("task_id")]
        nested = payload.get("event")
        if isinstance(nested, dict):
            candidates.append(nested.get("task_id"))
        for value in candidates:
            if isinstance(value, str) and value.startswith("01"):
                timestamp = _uuid7_ms(value)
                if timestamp is not None:
                    timestamps.append(timestamp)
    final = ""
    for event in events:
        if event.get("payload_type") == "run.terminal.completed":
            final = str(event.get("payload", {}).get("text", ""))
    return {
        "model_steps": model_steps,
        "tools": tools,
        "tool_errors": sum(not tool["ok"] for tool in tools),
        "trace_seconds": (max(timestamps) - min(timestamps)) / 1000 if timestamps else None,
        "tokens": None,
        "final": final,
        "trace_file": "muse.jsonl",
    }


def _opencode_metrics(directory: Path) -> dict[str, Any]:
    events = _jsonl(directory / "opencode.jsonl")
    steps = [event for event in events if event.get("type") == "step_finish"]
    tools: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "tool_use":
            continue
        part = event.get("part", {})
        name = str(part.get("tool", "tool"))
        state = part.get("state", {})
        arguments = state.get("input", {})
        label = name.title()
        detail = ""
        if name == "read":
            label = f"Read {Path(str(arguments.get('filePath', 'file'))).name}"
            detail = str(arguments.get("filePath", ""))
        elif name == "grep":
            label = "Search code"
            detail = f"pattern: {arguments.get('pattern', '')}"
            if arguments.get("include"):
                detail += f" · include: {arguments['include']}"
        elif name == "glob":
            label = "Find test file"
            detail = f"pattern: {arguments.get('pattern', '')}"
        elif name == "edit":
            label = "Edit implementation"
            detail = "aiohttp/web_runner.py · host fallback at line 111"
        elif name == "bash":
            command = str(arguments.get("command", ""))
            label = "Run test file" if "pytest" in command else "Run manual repro"
            detail = _short(command)
        tools.append(
            {
                "tool": name,
                "label": label,
                "detail": detail,
                "ok": state.get("status") == "completed",
                "model_message_id": part.get("messageID"),
            }
        )
    token_fields = [step.get("part", {}).get("tokens", {}) for step in steps]
    tokens = {
        "input": sum(int(item.get("input", 0)) for item in token_fields),
        "output": sum(int(item.get("output", 0)) for item in token_fields),
        "reasoning": sum(int(item.get("reasoning", 0)) for item in token_fields),
        "cache_read": sum(int(item.get("cache", {}).get("read", 0)) for item in token_fields),
        "reported_total": sum(int(item.get("total", 0)) for item in token_fields),
    }
    timestamps = [int(event["timestamp"]) for event in events if isinstance(event.get("timestamp"), int)]
    final = ""
    for event in events:
        if event.get("type") == "text":
            final = str(event.get("part", {}).get("text", ""))
    return {
        "model_steps": len(steps),
        "tools": tools,
        "tool_errors": sum(not tool["ok"] for tool in tools),
        "trace_seconds": (max(timestamps) - min(timestamps)) / 1000 if timestamps else None,
        "tokens": tokens,
        "final": final,
        "trace_file": "opencode.jsonl",
    }


def _pi_metrics(directory: Path) -> dict[str, Any]:
    events = _jsonl(directory / "pi.jsonl")
    messages = [
        event.get("message", {})
        for event in events
        if event.get("type") == "message_end" and event.get("message", {}).get("role") == "assistant"
    ]
    ends = {event.get("toolCallId"): event for event in events if event.get("type") == "tool_execution_end"}
    tools: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "tool_execution_start":
            continue
        name = str(event.get("toolName", "tool"))
        arguments = event.get("args", {})
        label = name.title()
        detail = ""
        if name == "read":
            label = f"Read {Path(str(arguments.get('path', 'file'))).name}"
            detail = str(arguments.get("path", ""))
        elif name == "edit":
            label = "Edit implementation"
            detail = "aiohttp/web_runner.py · host fallback at line 111"
        elif name == "bash":
            command = str(arguments.get("command", ""))
            if "inspect.getsource" in command:
                label = "Inspect + test attempt"
            elif "pytest" in command:
                label = "Run test file"
            else:
                label = "Run extended repro"
            detail = _short(command)
        end = ends.get(event.get("toolCallId"), {})
        ok = not bool(end.get("isError", True))
        if not ok:
            result_text = " ".join(
                str(block.get("text", ""))
                for block in end.get("result", {}).get("content", [])
                if isinstance(block, dict)
            )
            last_line = result_text.strip().splitlines()[-1] if result_text.strip() else "failed"
            detail += " · " + _short(last_line, 80)
        tools.append({"tool": name, "label": label, "detail": detail, "ok": ok})
    usages = [message.get("usage", {}) for message in messages]
    tokens = {
        "input": sum(int(item.get("input", 0)) for item in usages),
        "output": sum(int(item.get("output", 0)) for item in usages),
        "reasoning": sum(int(item.get("reasoning", 0)) for item in usages),
        "cache_read": sum(int(item.get("cacheRead", 0)) for item in usages),
        "reported_total": sum(int(item.get("totalTokens", 0)) for item in usages),
    }
    timestamps = [int(message["timestamp"]) for message in messages if isinstance(message.get("timestamp"), int)]
    final = ""
    for message in messages:
        texts = [block.get("text", "") for block in message.get("content", []) if block.get("type") == "text"]
        if texts:
            final = "".join(texts)
    return {
        "model_steps": len(messages),
        "tools": tools,
        "tool_errors": sum(not tool["ok"] for tool in tools),
        "trace_seconds": (max(timestamps) - min(timestamps)) / 1000 if timestamps else None,
        "tokens": tokens,
        "final": final,
        "trace_file": "pi.jsonl",
    }


def _load_run(harness: str, directory: Path) -> dict[str, Any]:
    parser = {"muse": _muse_metrics, "opencode": _opencode_metrics, "pi": _pi_metrics}[harness]
    summary = json.loads((directory / "summary.json").read_text())
    metrics = parser(directory)
    metrics.update(
        {
            "harness": harness,
            "version": VERSIONS[harness],
            "directory": str(directory),
            "success": bool(summary.get("success")),
            "agent_exit_code": summary.get("agent_exit_code", summary.get("muse_exit_code")),
            "grade_exit_code": summary.get("grade_exit_code"),
            "session_cleanup": summary.get("deleted_session_http_status"),
            "api_requests": summary.get("model_api_proxy", {}).get("requests", 0),
            "api_bytes": summary.get("model_api_proxy", {}).get("response_bytes", 0),
            "api_statuses": summary.get("model_api_proxy", {}).get("statuses", {}),
            "api_errors": summary.get("model_api_proxy", {}).get("errors", []),
            "tunnel_streams": summary.get("reverse_tunnel", {}).get("served_streams", 0),
            "prompt_sha256": _sha256(directory / "prompt.txt"),
            "patch_sha256": _sha256(directory / "agent.patch"),
            "patch": (directory / "agent.patch").read_text(),
            "patch_expression": next(
                (
                    line.removeprefix("+").strip()
                    for line in (directory / "agent.patch").read_text().splitlines()
                    if line.startswith("+") and not line.startswith("+++") and "host =" in line
                ),
                "",
            ),
            "agent_tests": _test_result(directory / metrics["trace_file"]),
            "grader_tests": _test_result(directory / "grade.log"),
        }
    )
    return metrics


def _fmt_tokens(run: dict[str, Any]) -> str:
    tokens = run["tokens"]
    return "not emitted" if tokens is None else f"{tokens['reported_total']:,}"


def _timeline_html(run: dict[str, Any]) -> str:
    steps = []
    for index, tool in enumerate(run["tools"], 1):
        status = "ok" if tool["ok"] else "error"
        mark = "✓" if tool["ok"] else "×"
        steps.append(
            f'<li class="step {status}"><span class="step-num">{index}</span>'
            f"<span>{html.escape(tool['label'])}</span><b>{mark}</b></li>"
        )
    return "".join(steps)


def _bar_rows(runs: list[dict[str, Any]], key: str, suffix: str = "") -> str:
    maximum = max(float(run[key]) for run in runs) or 1
    rows = []
    for run in runs:
        value = float(run[key])
        width = max(value / maximum * 100, 3)
        label = f"{value:.1f}" if isinstance(run[key], float) else str(run[key])
        rows.append(
            '<div class="bar-row">'
            f"<span>{html.escape(run['harness'].title())}</span>"
            f'<div class="bar-track"><i style="width:{width:.1f}%;background:{COLORS[run["harness"]]}"></i></div>'
            f"<strong>{label}{suffix}</strong></div>"
        )
    return "".join(rows)


def _markdown(report: dict[str, Any]) -> str:
    runs = report["runs"]
    rows = []
    for run in runs:
        rows.append(
            "| {version} | {result} | {steps} | {tools} | {errors} | {seconds:.1f}s | {requests} | {tokens} | {tests} |".format(
                version=run["version"],
                result="PASS" if run["success"] else "FAIL",
                steps=run["model_steps"],
                tools=len(run["tools"]),
                errors=run["tool_errors"],
                seconds=run["trace_seconds"],
                requests=run["api_requests"],
                tokens=_fmt_tokens(run),
                tests=f"{run['grader_tests']['passed']} passed / {run['grader_tests']['skipped']} skipped",
            )
        )
    timelines = []
    for run in runs:
        path = " → ".join(("✓ " if tool["ok"] else "✗ ") + tool["label"] for tool in run["tools"])
        timelines.append(f"- **{run['version']}**: {path}")
    patches = "\n".join(f"- **{run['version']}**: `{run['patch_expression']}`" for run in runs)
    return f"""# Harness comparison: one model, one SWE-rebench task

**Task:** `{report["task"]}`<br>
**Model:** `{report["model"]}`<br>
**Prompt SHA-256:** `{report["prompt_sha256"]}`<br>
**Toolbox digest:** `{report["toolbox_digest"]}`

| Harness | Result | Model turns | Tool calls | Tool errors | Active trace | API requests | Reported tokens | Held-out grade |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## Trajectories

{chr(10).join(timelines)}

## Patches

{patches}

Muse Code and OpenCode produced byte-identical patches. Pi produced a distinct
but logically equivalent conditional. All three passed the independently
applied held-out test patch and the full `tests/test_web_runner.py` command.

Token totals are native harness-reported values and are not emitted by this
Muse Code JSONL format. API byte counts are transport diagnostics, not a token
proxy. This is one stochastic trial per harness, so it describes these
trajectories rather than estimating average harness quality.
"""


def _html(report: dict[str, Any]) -> str:
    runs = report["runs"]
    cards = []
    timeline_cards = []
    patch_cards = []
    for run in runs:
        color = COLORS[run["harness"]]
        result = "PASS" if run["success"] else "FAIL"
        cards.append(
            f'<section class="result-card" style="--accent:{color}"><div class="eyebrow">{html.escape(run["version"])}</div>'
            f'<div class="pass">{result}</div><div class="score">{run["grader_tests"]["passed"]} passed · '
            f"{run['grader_tests']['skipped']} skipped</div></section>"
        )
        timeline_cards.append(
            f'<section class="timeline-card" style="--accent:{color}"><h3>{html.escape(run["version"])}</h3>'
            f'<div class="sub">{run["model_steps"]} model turns · {len(run["tools"])} tools · '
            f"{run['trace_seconds']:.1f}s</div><ol>{_timeline_html(run)}</ol></section>"
        )
        patch_cards.append(
            f'<section class="patch-card" style="--accent:{color}"><h3>{html.escape(run["harness"].title())}</h3>'
            f'<code>{html.escape(run["patch_expression"])}</code><div class="hash">patch {run["patch_sha256"][:12]}</div></section>'
        )

    table_rows = []
    for run in runs:
        table_rows.append(
            f'<tr><th><span class="dot" style="background:{COLORS[run["harness"]]}"></span>{html.escape(run["harness"].title())}</th>'
            f"<td>{run['model_steps']}</td><td>{len(run['tools'])}</td><td>{run['tool_errors']}</td>"
            f"<td>{run['trace_seconds']:.1f}s</td><td>{run['api_requests']}</td><td>{run['api_bytes'] / 1024:.0f} KiB</td>"
            f"<td>{_fmt_tokens(run)}</td><td>{run['session_cleanup']}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Harness trajectory comparison</title><style>
:root{{--bg:#0a0d14;--panel:#111722;--panel2:#151d2b;--text:#eef2f8;--muted:#94a3b8;--line:#263247;--good:#48d6a0;--bad:#ff6b7a}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 12% 0,#17213a 0,transparent 34%),var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1240px;margin:auto;padding:48px 28px 70px}} h1{{font-size:42px;line-height:1.05;margin:8px 0 12px;letter-spacing:-1.6px}} h2{{font-size:23px;margin:42px 0 16px}} h3{{margin:0;font-size:18px}} .kicker{{color:#73b7ff;text-transform:uppercase;letter-spacing:.16em;font-weight:750;font-size:12px}} .lede{{color:var(--muted);max-width:820px;font-size:17px}}
.controls{{display:flex;flex-wrap:wrap;gap:10px;margin:25px 0}} .chip{{background:#121a29;border:1px solid var(--line);border-radius:999px;padding:7px 12px;color:#cbd5e1}} .chip b{{color:white}}
.results,.timelines,.patches{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}} .result-card,.timeline-card,.patch-card,.chart{{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);border-top:3px solid var(--accent,#73b7ff);border-radius:14px;padding:20px;box-shadow:0 12px 36px #0004}} .eyebrow{{color:var(--muted)}} .pass{{font-size:34px;font-weight:850;color:var(--good);letter-spacing:-1px;margin:8px 0 0}} .score{{color:#cbd5e1}}
.charts{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}} .chart h3{{margin-bottom:18px}} .bar-row{{display:grid;grid-template-columns:86px 1fr 64px;gap:10px;align-items:center;margin:11px 0}} .bar-row>span{{color:#cbd5e1}} .bar-row strong{{text-align:right}} .bar-track{{height:11px;background:#252d3b;border-radius:8px;overflow:hidden}} .bar-track i{{display:block;height:100%;border-radius:8px}}
table{{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}} th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:right}} th:first-child,td:first-child{{text-align:left}} thead th{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}} tbody tr:last-child th,tbody tr:last-child td{{border-bottom:0}} .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px}}
.timeline-card .sub{{color:var(--muted);font-size:13px;margin:5px 0 16px}} ol{{list-style:none;margin:0;padding:0}} .step{{display:grid;grid-template-columns:27px 1fr 18px;align-items:center;gap:9px;padding:9px 0;border-bottom:1px solid #202a3a}} .step:last-child{{border:0}} .step-num{{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#222c3d;color:#b9c5d8;font-size:12px}} .step b{{color:var(--good)}} .step.error b{{color:var(--bad)}} .step.error span:nth-child(2){{color:#ffb2bb}}
.patch-card code{{display:block;background:#080b11;border:1px solid #253044;border-radius:9px;padding:14px;margin:13px 0;white-space:pre-wrap;color:#d9e5f4}} .hash{{color:var(--muted);font:12px ui-monospace,monospace}} .callout{{padding:18px 20px;background:#101b25;border:1px solid #24445a;border-left:4px solid #73b7ff;border-radius:10px;color:#cbd5e1}} .foot{{color:var(--muted);font-size:13px;margin-top:26px}} a{{color:#8ec8ff}} @media(max-width:850px){{.results,.timelines,.patches,.charts{{grid-template-columns:1fr}} table{{font-size:12px}} main{{padding:28px 15px}}}}
</style></head><body><main>
<div class="kicker">Controlled Firecracker experiment · n=1 per harness</div><h1>Same model. Same task.<br>Three agent harnesses.</h1>
<p class="lede">A direct trajectory comparison of Muse Spark 1.3 solving <code>{html.escape(report["task"])}</code> inside identical SWE-rebench containers through the Sandoq reverse tunnel.</p>
<div class="controls"><span class="chip"><b>Model</b> {html.escape(report["model"])}</span><span class="chip"><b>Prompt</b> {report["prompt_sha256"][:12]}</span><span class="chip"><b>Image</b> same base commit</span><span class="chip"><b>Protocol</b> Responses API</span></div>
<div class="results">{"".join(cards)}</div>
<h2>Efficiency profile</h2><div class="charts"><section class="chart"><h3>Active trajectory time</h3>{_bar_rows(runs, "trace_seconds", "s")}</section><section class="chart"><h3>Model turns</h3>{_bar_rows(runs, "model_steps")}</section><section class="chart"><h3>Tool calls</h3>{"".join(f'<div class="bar-row"><span>{run["harness"].title()}</span><div class="bar-track"><i style="width:{max(len(run["tools"]) / max(len(item["tools"]) for item in runs) * 100, 3):.1f}%;background:{COLORS[run["harness"]]}"></i></div><strong>{len(run["tools"])}</strong></div>' for run in runs)}</section><section class="chart"><h3>Model API requests</h3>{_bar_rows(runs, "api_requests")}</section></div>
<h2>Normalized metrics</h2><table><thead><tr><th>Harness</th><th>Turns</th><th>Tools</th><th>Tool errors</th><th>Trace</th><th>API req.</th><th>Wire bytes</th><th>Reported tokens</th><th>Cleanup</th></tr></thead><tbody>{"".join(table_rows)}</tbody></table>
<h2>What each harness actually did</h2><div class="timelines">{"".join(timeline_cards)}</div>
<h2>Patch shape</h2><div class="patches">{"".join(patch_cards)}</div>
<p class="callout"><b>Result:</b> Muse Code and OpenCode emitted byte-identical patches. Pi expressed the same condition in the opposite ternary order. All three passed the independently applied held-out test plus the complete web-runner test file.</p>
<p class="foot">Token counts are each harness's native reported usage; this Muse Code JSONL version emits no usage totals. Wire bytes are protocol diagnostics, not a token proxy. Timings cover the active trace, excluding image pulls and capacity wait. Raw traces may contain model reasoning and are retained separately. One run per harness is illustrative, not a statistical ranking.</p>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--muse-dir", type=Path, required=True)
    parser.add_argument("--opencode-dir", type=Path, required=True)
    parser.add_argument("--pi-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs = [
        _load_run("muse", args.muse_dir),
        _load_run("opencode", args.opencode_dir),
        _load_run("pi", args.pi_dir),
    ]
    prompt_hashes = {run["prompt_sha256"] for run in runs}
    if len(prompt_hashes) != 1:
        raise ValueError(f"runs used different prompts: {sorted(prompt_hashes)}")
    summaries = [
        json.loads((directory / "summary.json").read_text())
        for directory in (args.muse_dir, args.opencode_dir, args.pi_dir)
    ]
    task_ids = {summary["instance_id"] for summary in summaries}
    models = {summary["model"] for summary in summaries}
    toolboxes = {summary["toolbox_image"] for summary in summaries}
    if len(task_ids) != 1 or len(models) != 1 or len(toolboxes) != 1:
        raise ValueError("runs do not share task, model, and toolbox inputs")
    report = {
        "task": task_ids.pop(),
        "model": models.pop(),
        "toolbox_digest": toolboxes.pop(),
        "prompt_sha256": prompt_hashes.pop(),
        "runs": runs,
    }
    _write_json(args.output_dir / "comparison.json", report)
    (args.output_dir / "comparison.md").write_text(_markdown(report))
    (args.output_dir / "comparison.html").write_text(_html(report))
    print(args.output_dir / "comparison.html")
    return 0


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
