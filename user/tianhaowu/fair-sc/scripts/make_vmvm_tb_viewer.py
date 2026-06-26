#!/usr/bin/env python3
"""Build a self-contained HTML viewer for vmvm-tb trajectories.

Handles BOTH formats automatically:
  * v0 eval  : a vf-eval ``results.jsonl`` (rows have prompt/completion + tb_* state cols).
  * v1 train : a prime-rl ``run_default/rollouts/step_N/train_rollouts.jsonl`` dump
               (verifiers Trace: nodes/metrics/rewards). v1 recovery is seamless, so
               infra is read from the ``infra_*`` metrics, not the trajectory text.

Usage: make_vmvm_tb_viewer.py <results.jsonl | train_rollouts.jsonl> [out.html]
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
    """v0 infra tags from message content (independent of reward):
    reconnect count, permanent loss, eventual wall-clock timeout."""
    txt = "\n".join((str(m.get('content') or '') if isinstance(m, dict) else str(m)) for m in traj)
    return (txt.count('dropped and was re-established'),
            'connection lost permanently' in txt,
            'Wall-clock limit reached' in txt)

def _f(x):
    try: return float(x)
    except Exception: return 0.0

def to_view(r):
    """Normalize a row from either format into a uniform view dict."""
    if 'nodes' in r:  # ---- v1 prime-rl TRAIN dump (verifiers Trace) ----
        m = r.get('metrics') or {}
        task = r.get('task') or {}
        msgs = [(n.get('message') or {}) for n in (r.get('nodes') or [])]
        tname = task.get('name')
        if not tname:  # task.name is None in the dump; derive from the prompt heading
            for ln in (task.get('prompt', '') or '').split('\n'):
                s = ln.strip().lstrip('#').strip()
                if s and s.lower() != 'task:':
                    tname = s[:80]
                    break
        tname = tname or f"task#{task.get('idx')}"
        rc, lost, tout = infra_flags(msgs)  # v0-train messages carry the text markers; v1 is seamless (0)
        return dict(
            fmt='v1' if any(k.startswith('infra_') for k in m) else 'v0-train',
            task=tname, task_key=task.get('idx', tname),
            reward=(r.get('rewards') or {}).get('reward', 0),
            turns=int(_f(m.get('num_turns'))), stop=r.get('stop_condition', '?'),
            truncated='?', tokens={}, traj=msgs, turn_timings=[], tb=None,
            infra=dict(recon=rc, lost=bool(lost), tout=bool(tout),
                       drops=int(_f(m.get('infra_drops'))), recovered=int(_f(m.get('infra_recovered'))),
                       box_gone=int(_f(m.get('infra_box_gone'))), state_lost=int(_f(m.get('infra_state_lost'))),
                       lost_turn=int(_f(m.get('infra_lost_turn')) if m.get('infra_lost_turn') is not None else -1)))
    # ---- v0 vf-eval results.jsonl ----
    info = r.get('info') or {}
    traj = (r.get('prompt') or []) + (r.get('completion') or [])
    rc, lost, tout = infra_flags(traj)
    tb = None
    if r.get('tb_test_output'):
        tb = dict(out=r.get('tb_test_output'), outcome=r.get('tb_outcome', '?'),
                  ec=r.get('tb_exit_code', '?'), msg=r.get('tb_message', ''))
    tname = info.get('task_name') or r.get('example_id') or '?'
    return dict(
        fmt='v0', task=tname, task_key=tname,
        reward=r.get('reward') or 0, turns=r.get('num_turns', '?'), stop=r.get('stop_condition', '?'),
        truncated=r.get('is_truncated', '?'), tokens=r.get('token_usage') or {}, traj=traj,
        turn_timings=r.get('turn_timings') or [], tb=tb,
        infra=dict(recon=rc, lost=bool(lost), tout=bool(tout), drops=0, recovered=0,
                   box_gone=0, state_lost=0, lost_turn=-1))

views = [to_view(r) for r in rows]
FMT = views[0]['fmt'] if views else 'v0'

cards = []
n_pass = sum(1 for v in views if (v['reward'] or 0) >= 1.0)
n_recon = sum(1 for v in views if v['infra']['recon'] or v['infra']['drops'])   # drop-affected
n_lost = sum(1 for v in views if v['infra']['lost'] or v['infra']['box_gone'] or v['infra']['state_lost'])
n_tout = sum(1 for v in views if v['infra']['tout'])
by = {}
for v in views:
    by.setdefault(v['task_key'], []).append((v['reward'] or 0) >= 1.0)
solved = sum(1 for vv in by.values() if any(vv))

for i, v in enumerate(views):
    task, rew = v['task'], v['reward']
    ok = (rew or 0) >= 1.0
    turns, stop, trunc, tok = v['turns'], v['stop'], v['truncated'], v['tokens']
    body = ''.join(msg_html(m) for m in v['traj'])
    tt = v['turn_timings']
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
    tb = v['tb']
    if tb:
        to_html = (f'<details class="testout"><summary>final test output (outcome={esc(tb["outcome"])} '
                   f'exit={esc(tb["ec"])})</summary><pre class="msg-line">{esc(tb["msg"])}</pre>'
                   f'<pre>{esc(tb["out"])}</pre></details>')
        body = tt_html + to_html + body
    else:
        body = tt_html + body
    inf = v['infra']
    badge = 'PASS' if ok else 'FAIL'
    bcls = 'pass' if ok else 'fail'
    ibadges = ''
    if inf['recon']:
        ibadges += f'<span class="badge recon">reconnect&times;{inf["recon"]}</span> '
    if inf['drops']:
        lt = f" lost@turn{inf['lost_turn']}" if inf['lost_turn'] >= 0 else ""
        ibadges += f'<span class="badge recon">drop&times;{inf["drops"]} &middot; recovered {inf["recovered"]}{lt}</span> '
    if inf['box_gone']:
        ibadges += '<span class="badge lost">box-gone</span> '
    if inf['state_lost']:
        ibadges += '<span class="badge lost">state-lost</span> '
    if inf['lost']:
        ibadges += '<span class="badge lost">lost-perm</span> '
    if inf['tout']:
        ibadges += '<span class="badge tout">timeout</span> '
    head = (f'<span class="badge {bcls}">{badge}</span> {ibadges}<b>{esc(task)}</b> '
            f'<span class="meta">reward={rew} &middot; turns={turns} &middot; stop={esc(stop)} &middot; '
            f'truncated={trunc} &middot; tokens={tok.get("total", "?")}</span>')
    drop_attr = int(bool(inf['recon']) or bool(inf['drops']))
    lost_attr = int(bool(inf['lost']) or bool(inf['box_gone']) or bool(inf['state_lost']))
    attrs = (f'data-pass="{int(ok)}" data-recon="{drop_attr}" '
             f'data-lost="{lost_attr}" data-tout="{int(bool(inf["tout"]))}"')
    cards.append(f'<details class="task {bcls}" {attrs}><summary>{head}</summary><div class="conv">{body}</div></details>')

_src_label = esc(R.split('rollouts/')[-1] if FMT == 'v1' else R)
_title = ('vmvm-tb-v1 &middot; TRAIN rollouts' if FMT == 'v1' else 'vmvm-tb &middot; eval trajectories')
_infra_label = ('drop-affected' if FMT == 'v1' else 'reconnected')
_lost_label = ('box-gone (in-dump)' if FMT == 'v1' else 'lost-perm')
_note = (' &middot; <i>box_gone rollouts are raised&rarr;dropped, not in this dump</i>' if FMT == 'v1' else '')

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
<h1>{_title} &middot; Qwen3.5-35B-A3B</h1>
<div class="summary">{len(rows)} rollouts &middot; pass@1 raw {n_pass}/{len(rows)} &middot; pass@2(any) {solved}/{len(by)} tasks &middot; <span style="color:#e3b341">{_infra_label} {n_recon}</span> &middot; <span style="color:#ff9e64">{_lost_label} {n_lost}</span> &middot; <span style="color:#b392f0">timeout {n_tout}</span>{_note} &middot; source: {_src_label}</div>
<div class="controls">
<button onclick="document.querySelectorAll('details').forEach(d=>d.open=true)">expand all</button>
<button onclick="document.querySelectorAll('details').forEach(d=>d.open=false)">collapse all</button>
<button onclick="ff('')">all</button>
<button onclick="ff('recon')">{_infra_label}</button>
<button onclick="ff('lost')">{_lost_label}</button>
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
print('WROTE', OUT, '|', len(rows), 'rollouts |', f'format={FMT} |', f'pass@2 {solved}/{len(by)}')
