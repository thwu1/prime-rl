#!/usr/bin/env python3
"""Build a self-contained HTML viewer for a vmvm-tb vf-eval results.jsonl.
Usage: python3 make_vmvm_tb_viewer.py <results.jsonl> <out.html>
"""
import json, sys, html, glob, os

R = sys.argv[1] if len(sys.argv) > 1 else sorted(
    glob.glob(os.path.expanduser('~/prime-rl/environments/vmvm_tb/outputs/evals/*/*/results.jsonl')),
    key=os.path.getmtime)[-1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser('~/vmvm_tb_trajectories.html')

rows = [json.loads(l) for l in open(R) if l.strip()]

def esc(s):
    return html.escape(str(s)).replace('</script>', '<\\/script>')

def _tool_cmd(tc):
    """Render one tool_call as '$ name: command'. Handles OpenAI {function:{name,arguments}}
    and flat {name, arguments} shapes; arguments may be a JSON string or dict."""
    fn = tc.get('function') or {}
    name = tc.get('name') or fn.get('name') or 'tool'
    args = tc.get('arguments', fn.get('arguments', ''))
    cmd = args
    if isinstance(args, str):
        try:
            a = json.loads(args)
            cmd = a.get('command') if isinstance(a, dict) and 'command' in a else args
        except Exception:
            cmd = args
    elif isinstance(args, dict):
        cmd = args.get('command') if 'command' in args else json.dumps(args)
    return f'<pre class="toolcall">$ {esc(name)}: {esc(cmd)}</pre>'

def msg_html(m):
    if not isinstance(m, dict):
        return f'<div class="msg other"><div class="role">?</div><pre>{esc(m)}</pre></div>'
    role = m.get('role', '?')
    cls = {'system': 'sys', 'user': 'user', 'assistant': 'asst', 'tool': 'tool'}.get(role, 'other')
    parts = []
    rc = m.get('reasoning_content')
    if rc:
        parts.append(f'<pre class="reasoning">{esc(rc)}</pre>')
    content = m.get('content', '')
    if isinstance(content, list):  # multimodal -> flatten text parts
        content = '\n'.join(p.get('text', '') if isinstance(p, dict) else str(p) for p in content)
    if content:
        parts.append(f'<pre>{esc(content)}</pre>')
    for tc in (m.get('tool_calls') or []):
        parts.append(_tool_cmd(tc))
    return f'<div class="msg {cls}"><div class="role">{esc(role)}</div>{"".join(parts) or "<pre></pre>"}</div>'

def infra_flags(traj):
    """Orthogonal infra tags from message content (independent of reward):
    reconnect count, permanent loss, eventual wall-clock timeout."""
    txt = "\n".join((str(m.get('content') or '') if isinstance(m, dict) else str(m)) for m in traj)
    return (txt.count('dropped and was re-established'),
            'connection lost permanently' in txt,
            'Wall-clock limit reached' in txt)

cards = []
n_pass = sum(1 for r in rows if (r.get('reward') or 0) >= 1.0)
n_recon = n_lost = n_tout = 0
by = {}
for r in rows:
    t = (r.get('info') or {}).get('task_name') or r.get('example_id') or '?'
    by.setdefault(t, []).append((r.get('reward') or 0) >= 1.0)
solved = sum(1 for v in by.values() if any(v))

for i, r in enumerate(rows):
    info = r.get('info') or {}
    task = info.get('task_name') or r.get('example_id') or f'row{i}'
    rew = r.get('reward') or 0
    ok = rew >= 1.0
    turns = r.get('num_turns', '?')
    stop = r.get('stop_condition', '?')
    trunc = r.get('is_truncated', '?')
    tok = r.get('token_usage') or {}
    traj = (r.get('prompt') or []) + (r.get('completion') or [])
    body = ''.join(msg_html(m) for m in traj)
    tt = r.get('turn_timings') or []
    tt_html = ''
    if tt:
        head_row = ('<tr><th>turn</th><th>kind</th><th>gen_s</th><th>exec_s</th>'
                    '<th>gen_tok</th><th>n_cmds</th><th>asst_chars</th><th>reason_chars</th></tr>')
        body_rows = ''
        tot_gen = tot_exec = tot_tok = 0.0
        for t in tt:
            tot_gen += t.get('gen_s', 0) or 0
            tot_exec += t.get('exec_s', 0) or 0
            tot_tok += t.get('gen_tokens', 0) or 0
            body_rows += (f'<tr><td>{t.get("turn","")}</td><td>{esc(t.get("kind",""))}</td>'
                          f'<td>{t.get("gen_s","")}</td><td>{t.get("exec_s","")}</td>'
                          f'<td>{t.get("gen_tokens","")}</td><td>{t.get("n_cmds","")}</td>'
                          f'<td>{t.get("asst_chars","")}</td><td>{t.get("reasoning_chars","")}</td></tr>')
        foot = (f'<tr class="tot"><td colspan="2">TOTAL ({len(tt)} turns)</td>'
                f'<td>{round(tot_gen,1)}</td><td>{round(tot_exec,1)}</td>'
                f'<td>{int(tot_tok)}</td><td colspan="3"></td></tr>')
        tt_html = (f'<details class="timing"><summary>per-turn timing ({len(tt)} turns &middot; '
                   f'gen {round(tot_gen,1)}s &middot; exec {round(tot_exec,1)}s &middot; {int(tot_tok)} gen-tok)</summary>'
                   f'<table>{head_row}{body_rows}{foot}</table></details>')
    # final test output (grader stdout) — present for runs with tb_* state columns
    to = r.get('tb_test_output')
    if to:
        outcome = r.get('tb_outcome', '?')
        ec = r.get('tb_exit_code', '?')
        msg = r.get('tb_message', '')
        to_html = (f'<details class="testout"><summary>final test output (outcome={esc(outcome)} '
                   f'exit={esc(ec)})</summary><pre class="msg-line">{esc(msg)}</pre>'
                   f'<pre>{esc(to)}</pre></details>')
        body = tt_html + to_html + body
    else:
        body = tt_html + body
    rc, lost, tout = infra_flags(traj)
    if rc: n_recon += 1
    if lost: n_lost += 1
    if tout: n_tout += 1
    badge = 'PASS' if ok else 'FAIL'
    bcls = 'pass' if ok else 'fail'
    ibadges = ''
    if rc:   ibadges += f'<span class="badge recon">reconnect&times;{rc}</span> '
    if lost: ibadges += '<span class="badge lost">lost-perm</span> '
    if tout: ibadges += '<span class="badge tout">timeout</span> '
    head = (f'<span class="badge {bcls}">{badge}</span> {ibadges}<b>{esc(task)}</b> '
            f'<span class="meta">reward={rew} &middot; turns={turns} &middot; stop={esc(stop)} &middot; '
            f'truncated={trunc} &middot; tokens={tok.get("total", "?")}</span>')
    attrs = (f'data-pass="{int(ok)}" data-recon="{int(bool(rc))}" '
             f'data-lost="{int(lost)}" data-tout="{int(tout)}"')
    cards.append(f'<details class="task {bcls}" {attrs}><summary>{head}</summary><div class="conv">{body}</div></details>')

HTML = f'''<!doctype html><meta charset="utf-8"><title>vmvm-tb trajectories</title>
<style>
body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;background:#0d1117;color:#c9d1d9}}
header{{position:sticky;top:0;background:#161b22;padding:12px 20px;border-bottom:1px solid #30363d;z-index:5}}
h1{{margin:0 0 4px;font-size:16px}} .summary{{color:#8b949e;font-size:13px}}
.wrap{{padding:16px 20px;max-width:1100px;margin:0 auto}}
details.task{{border:1px solid #30363d;border-radius:8px;margin:8px 0;background:#161b22}}
details.task.pass{{border-left:4px solid #2ea043}} details.task.fail{{border-left:4px solid #f85149}}
summary{{cursor:pointer;padding:10px 14px;list-style:none}}
summary::-webkit-details-marker{{display:none}}
.badge{{font-weight:700;padding:1px 8px;border-radius:10px;font-size:11px}}
.badge.pass{{background:#15331d;color:#3fb950}} .badge.fail{{background:#3a1417;color:#ff7b72}}
.badge.recon{{background:#3a2e10;color:#e3b341}} .badge.lost{{background:#3a1417;color:#ff9e64}} .badge.tout{{background:#241a3a;color:#b392f0}}
.meta{{color:#8b949e;font-size:12px;margin-left:8px}}
.conv{{padding:6px 14px 14px}}
.msg{{margin:8px 0;border-radius:6px;overflow:hidden;border:1px solid #21262d}}
.msg .role{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;padding:3px 10px;color:#8b949e;background:#0d1117}}
.msg pre{{margin:0;padding:10px 12px;white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,Menlo,monospace}}
.msg.sys pre{{background:#1c2128}} .msg.user pre{{background:#0d1f2d}}
.msg.asst pre{{background:#12261a}} .msg.tool pre{{background:#251c0d}}
.msg pre.reasoning{{background:#1a1726;color:#a99bd6;font-style:italic;border-left:2px solid #6e5fa3}}
.msg pre.toolcall{{background:#0b1f1f;color:#7ee0c8;border-left:2px solid #2ea7a0}}
details.timing{{margin:8px 0;border:1px solid #30363d;border-radius:6px;background:#10151c}}
details.timing summary{{padding:6px 12px;color:#d29922;font-size:12px}}
details.timing table{{width:100%;border-collapse:collapse;font:11px ui-monospace,monospace}}
details.timing th,details.timing td{{border:1px solid #21262d;padding:2px 8px;text-align:right}}
details.timing th{{background:#161b22;color:#8b949e}} details.timing tr.tot td{{background:#161b22;font-weight:700;color:#d29922}}
details.testout{{margin:8px 0;border:1px solid #30363d;border-radius:6px;background:#1a1410}}
details.testout summary{{padding:6px 12px;color:#ff9e64;font-size:12px}}
details.testout pre{{margin:0;padding:8px 12px;white-space:pre-wrap;word-break:break-word;font:11px/1.4 ui-monospace,monospace}}
details.testout pre.msg-line{{color:#8b949e;border-bottom:1px solid #21262d}}
input{{margin-left:12px;padding:4px 8px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px}}
.controls{{margin-top:6px}} button{{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 10px;cursor:pointer;margin-right:6px}}
</style>
<header>
<h1>vmvm-tb &middot; Qwen3.5-35B-A3B &middot; terminal-bench trajectories</h1>
<div class="summary">{len(rows)} rollouts &middot; pass@1 raw {n_pass}/{len(rows)} &middot; pass@2(any) {solved}/{len(by)} tasks &middot; <span style="color:#e3b341">reconnected {n_recon}</span> &middot; <span style="color:#ff9e64">lost-perm {n_lost}</span> &middot; <span style="color:#b392f0">timeout {n_tout}</span> &middot; source: {esc(R)}</div>
<div class="controls">
<button onclick="document.querySelectorAll('details').forEach(d=>d.open=true)">expand all</button>
<button onclick="document.querySelectorAll('details').forEach(d=>d.open=false)">collapse all</button>
<button onclick="ff('')">all</button>
<button onclick="ff('recon')">reconnected</button>
<button onclick="ff('lost')">lost-perm</button>
<button onclick="ff('tout')">timeout</button>
<button onclick="ff('clean')">clean (no infra)</button>
<input id="f" placeholder="filter task name..." oninput="for(const d of document.querySelectorAll('details.task')){{d.style.display=d.querySelector('summary').textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none'}}">
</div>
<script>
function ff(k){{document.querySelectorAll('details.task').forEach(d=>{{
  let s=true;
  if(k==='clean') s=(d.dataset.recon==='0'&&d.dataset.lost==='0'&&d.dataset.tout==='0');
  else if(k) s=(d.dataset[k]==='1');
  d.style.display=s?'':'none';
}});}}
</script>
</header>
<div class="wrap">{''.join(cards)}</div>
'''
open(OUT, 'w').write(HTML)
print('WROTE', OUT, '|', len(rows), 'rollouts |', f'pass@2 {solved}/{len(by)}')
