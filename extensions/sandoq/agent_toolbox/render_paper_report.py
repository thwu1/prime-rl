#!/usr/bin/env python3
"""Render comparison.json as a restrained, paper-like trajectory report."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

ACCENTS = {"muse": "#6556a5", "opencode": "#217a62", "pi": "#9a5b16"}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def action_kind(tool: dict[str, Any]) -> str:
    name = tool["tool"]
    if "edit" in name or "write" in name:
        return "change"
    if name in {"bash", "shell"}:
        return "verify"
    if name in {"search", "grep", "glob", "find"}:
        return "inspect"
    return "read"


def actions(run: dict[str, Any]) -> str:
    groups = Counter(tool.get("model_message_id") for tool in run["tools"] if tool.get("model_message_id"))
    rendered = []
    for number, tool in enumerate(run["tools"], 1):
        kind = action_kind(tool)
        state = "ok" if tool["ok"] else "error"
        parallel = groups.get(tool.get("model_message_id"), 0) > 1
        badges = [f'<span class="kind">{esc(kind)}</span>']
        if parallel:
            badges.append('<span class="parallel">parallel batch</span>')
        rendered.append(
            f'<li class="action {state} {kind}">'
            f'<div class="action-head"><span class="number">{number:02d}</span>{"".join(badges)}'
            f'<span class="state">{"ok" if tool["ok"] else "recovered error"}</span></div>'
            f"<h4>{esc(tool['label'])}</h4>"
            f"<p>{esc(tool.get('detail') or 'No detail emitted by the harness')}</p>"
            "</li>"
        )
    return "".join(rendered)


def metric_rows(runs: list[dict[str, Any]]) -> str:
    rows = []
    for run in runs:
        tokens = run["tokens"]
        token_text = "not emitted"
        token_note = ""
        if tokens is not None:
            token_text = f"{tokens['reported_total']:,}"
            token_note = f"{tokens['input']:,} input · {tokens['cache_read']:,} cache-read"
        rows.append(
            f'<tr><th><span class="swatch" style="--accent:{ACCENTS[run["harness"]]}"></span>{esc(run["version"])}</th>'
            f"<td>{run['model_steps']}</td><td>{len(run['tools'])}</td><td>{run['tool_errors']}</td>"
            f"<td>{run['trace_seconds']:.1f}s</td><td>{run['api_requests']}</td>"
            f"<td><strong>{token_text}</strong><small>{token_note}</small></td>"
            f"<td><strong>{run['grader_tests']['passed']} passed</strong><small>{run['grader_tests']['skipped']} skipped</small></td></tr>"
        )
    return "".join(rows)


def patch_columns(runs: list[dict[str, Any]]) -> str:
    first_hash = runs[0]["patch_sha256"]
    columns = []
    for run in runs:
        relation = "byte-identical" if run["patch_sha256"] == first_hash else "semantic match"
        columns.append(
            f'<article class="patch"><header><b>{esc(run["harness"].title())}</b><span>{relation}</span></header>'
            f"<pre>{esc(run['patch_expression'])}</pre>"
            f"<footer>sha256 {esc(run['patch_sha256'][:16])}</footer></article>"
        )
    return "".join(columns)


def render(report: dict[str, Any]) -> str:
    runs = report["runs"]
    lanes = []
    for run in runs:
        lanes.append(
            f'<article class="lane" style="--accent:{ACCENTS[run["harness"]]}">'
            '<header class="lane-head">'
            f'<div><span class="harness-index">{esc(run["harness"].upper())}</span><h3>{esc(run["version"])}</h3></div>'
            f"<dl><div><dt>model turns</dt><dd>{run['model_steps']}</dd></div>"
            f"<div><dt>tool calls</dt><dd>{len(run['tools'])}</dd></div>"
            f"<div><dt>active trace</dt><dd>{run['trace_seconds']:.1f}s</dd></div></dl>"
            "</header>"
            f'<ol class="actions">{actions(run)}</ol>'
            f'<p class="lane-result"><b>Independent result</b> · {run["grader_tests"]["passed"]} passed, '
            f"{run['grader_tests']['skipped']} skipped · agent exit {run['agent_exit_code']} · session cleanup HTTP {run['session_cleanup']}</p>"
            "</article>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Muse Spark 1.3 — harness trajectory comparison</title>
<style>
:root{{--paper:#fffef9;--ink:#191918;--muted:#66645e;--rule:#cbc7bb;--soft:#f3f0e7;--error:#9d3030}}
*{{box-sizing:border-box}}
html{{background:#e9e6dc}}
body{{margin:0;color:var(--ink);font:16px/1.48 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}
main{{width:min(1500px,calc(100% - 32px));margin:32px auto;background:var(--paper);padding:58px 68px 72px;border:1px solid #d8d3c6}}
h1,h2,h3{{font-family:Georgia,'Times New Roman',serif;font-weight:500}}
h1{{font-size:56px;line-height:1.04;letter-spacing:-1.7px;margin:20px 0 18px;max-width:1050px}}
h2{{font-size:31px;margin:54px 0 22px;padding-top:18px;border-top:2px solid var(--ink)}}
h3{{font-size:25px;margin:4px 0 0}}
.masthead{{display:flex;justify-content:space-between;border-bottom:1px solid var(--ink);padding-bottom:10px;text-transform:uppercase;letter-spacing:.13em;font:700 12px/1.2 ui-monospace,monospace}}
.deck{{font:20px/1.5 Georgia,serif;color:#4e4c47;max-width:1020px;margin:0 0 30px}}
.abstract{{display:grid;grid-template-columns:170px 1fr;gap:26px;border-block:1px solid var(--rule);padding:20px 0;margin:32px 0}}
.abstract b{{text-transform:uppercase;letter-spacing:.12em;font-size:12px}}
.abstract p{{margin:0;max-width:1050px}}
.controls{{width:100%;border-collapse:collapse;margin-top:28px;font-size:14px}}
.controls th{{text-align:left;text-transform:uppercase;letter-spacing:.09em;font-size:11px;color:var(--muted);padding:0 18px 7px 0}}
.controls td{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;padding:0 18px 15px 0;border-bottom:1px solid var(--rule)}}
.finding{{font:24px/1.45 Georgia,serif;border-left:5px solid #282824;padding:4px 0 4px 24px;margin:28px 0}}
.metrics{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
.metrics thead th{{padding:10px 12px;border-block:1px solid var(--ink);text-align:right;text-transform:uppercase;letter-spacing:.08em;font-size:11px}}
.metrics thead th:first-child,.metrics tbody th{{text-align:left}}
.metrics tbody th,.metrics td{{padding:15px 12px;border-bottom:1px solid var(--rule);text-align:right}}
.metrics tbody th{{font-weight:650}} .metrics small{{display:block;color:var(--muted);font-size:11px;margin-top:2px}}
.swatch{{display:inline-block;width:11px;height:11px;background:var(--accent);margin-right:10px}}
.lane{{border-top:5px solid var(--accent);padding:20px 0 28px;margin:34px 0 44px}}
.lane-head{{display:flex;justify-content:space-between;gap:30px;align-items:flex-start;margin-bottom:18px}}
.harness-index{{font:700 11px/1 ui-monospace,monospace;letter-spacing:.14em;color:var(--accent)}}
.lane-head dl{{display:flex;gap:28px;margin:0}} .lane-head dl div{{min-width:92px;border-left:1px solid var(--rule);padding-left:12px}}
.lane-head dt{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} .lane-head dd{{font:500 22px/1.2 Georgia,serif;margin:4px 0}}
.actions{{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}}
.action{{position:relative;min-height:144px;border:1px solid #aaa69c;background:#fff;padding:14px 15px 13px}}
.action.change{{border-width:2px;border-color:var(--accent)}} .action.verify{{background:#f9f7f1}} .action.error{{border:2px solid var(--error);background:#fff8f6}}
.action-head{{display:flex;align-items:center;gap:7px;min-height:20px;font:700 9px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.07em}}
.number{{font-size:12px;color:var(--accent);margin-right:auto}} .kind{{color:#65635e}} .parallel{{background:#ece8dc;padding:4px 5px}} .state{{color:#39705c}} .error .state{{color:var(--error)}}
.action h4{{font:600 16px/1.25 Georgia,serif;margin:13px 0 8px}} .action p{{margin:0;color:var(--muted);font:11px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}}
.lane-result{{border-bottom:1px solid var(--rule);padding:13px 0;margin:10px 0 0;color:#4e4c47}}
.patches{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}} .patch{{border:1px solid var(--rule)}} .patch header{{display:flex;justify-content:space-between;padding:12px 15px;border-bottom:1px solid var(--rule)}} .patch header span{{font:700 10px/1.5 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em;color:#5f5d57}}
.patch pre{{white-space:pre-wrap;margin:0;padding:22px 15px;min-height:92px;background:#f5f2ea;font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}} .patch footer{{padding:9px 15px;color:var(--muted);font:11px ui-monospace,monospace}}
.notes{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}} .note{{padding-top:12px;border-top:1px solid var(--ink)}} .note b{{display:block;font:600 18px Georgia,serif;margin-bottom:6px}} .note p{{margin:0;color:#4e4c47}}
.method{{margin-top:50px;border:1px solid var(--rule);padding:22px 24px;background:#faf8f1}} .method h3{{font-size:20px}} .method p{{margin:8px 0;color:#4e4c47}}
.provenance{{font:12px/1.5 ui-monospace,monospace;color:var(--muted);overflow-wrap:anywhere}}
@media(max-width:900px){{main{{padding:34px 24px}}h1{{font-size:39px}}.actions{{grid-template-columns:repeat(2,1fr)}}.patches,.notes{{grid-template-columns:1fr}}.lane-head{{display:block}}.lane-head dl{{margin-top:16px}}}}
@media print{{html{{background:white}}main{{width:100%;margin:0;border:0;padding:24px}}.lane{{break-inside:avoid}}}}
</style>
</head>
<body><main>
<div class="masthead"><span>Systems experiment note</span><span>10 September 2026 · n=1 per harness</span></div>
<h1>How three coding harnesses steer the same model</h1>
<p class="deck">Muse Spark 1.3 solved the same aiohttp defect through Muse Code, OpenCode, and Pi. The answer was identical in behavior; the paths were not.</p>
<div class="abstract"><b>Result</b><p>All three agents changed one production line and passed the held-out SWE-rebench grader: <strong>17 passed, 2 skipped</strong>. Pi reached the edit with the least exploration; OpenCode batched discovery calls and made no tool error; Muse Code took the most deliberate route and created a dedicated reproduction script.</p></div>
<table class="controls"><thead><tr><th>Task</th><th>Model</th><th>Prompt digest</th><th>Base commit</th><th>Execution</th></tr></thead><tbody><tr><td>{esc(report["task"])}</td><td>{esc(report["model"])}</td><td>{esc(report["prompt_sha256"][:16])}</td><td>b9189df64353</td><td>Firecracker · Sandoq tunnel · Responses API</td></tr></tbody></table>

<h2>1. Outcome and effort</h2>
<table class="metrics"><thead><tr><th>Harness</th><th>Model turns</th><th>Tool calls</th><th>Recovered errors</th><th>Active trace</th><th>API requests</th><th>Reported tokens</th><th>Held-out grade</th></tr></thead><tbody>{metric_rows(runs)}</tbody></table>
<p class="finding"><strong>Same correctness, different orchestration.</strong> Pi used half as many tools as Muse Code; OpenCode sat between them and used one parallel three-search batch.</p>

<h2>2. Trajectory blocks</h2>
{"".join(lanes)}

<h2>3. Patch convergence</h2>
<div class="patches">{patch_columns(runs)}</div>

<h2>4. Reading the differences</h2>
<div class="notes">
  <div class="note"><b>Muse Code: deliberate</b><p>Read source, searched three times, inspected tests, edited, recovered from an invalid one-line async repro, wrote a standalone repro, then ran the test file.</p></div>
  <div class="note"><b>OpenCode: structured discovery</b><p>Read source, issued two greps and one glob together, read the target tests, edited, then performed a manual behavioral check and the focused suite without error.</p></div>
  <div class="note"><b>Pi: direct</b><p>Read once and edited immediately. A combined inspect/test command failed before pytest, so it reran the suite and added a broader behavioral repro including a live site start.</p></div>
</div>

<section class="method"><h3>Method and limits</h3><p>Same task JSON, prompt bytes, base commit, toolbox digest, model ID, high reasoning setting, resource limits, Model API endpoint, and independent grader. Each harness received its native local code tools; web tools, personal context, and extensions were disabled. The report omits model reasoning text and compares observable actions only.</p><p>Token counts use each harness's native accounting; this Muse Code JSONL version does not emit usage. API response bytes are transport diagnostics and are not treated as token estimates. One stochastic run per harness is descriptive, not a quality ranking.</p><div class="provenance">toolbox {esc(report["toolbox_digest"])}<br>prompt sha256 {esc(report["prompt_sha256"])}</div></section>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("comparison", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.comparison.read_text())
    args.output.write_text(render(report))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
