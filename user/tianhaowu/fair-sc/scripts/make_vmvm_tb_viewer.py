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

# Rough char->token estimate (terminal output tokenizes ~3.5-4 chars/tok); only used to
# flag whether a dropped ModelError was a context-window overflow vs a transient.
CTX_CAP = 102144
def _est_tokens(msgs):
    tot = 0
    for m in msgs:
        if not isinstance(m, dict):
            tot += len(str(m)); continue
        c = m.get('content') or ''
        if isinstance(c, list):
            c = ' '.join(p.get('text', '') if isinstance(p, dict) else str(p) for p in c)
        tot += len(c) + len(m.get('reasoning_content') or '')
        for tc in (m.get('tool_calls') or []):
            tot += len(json.dumps(tc))
    return tot // 4

def _infra(m):
    """Pull the full tb_v1 infra/budget classification out of the metrics dict."""
    g = lambda k: int(_f(m.get(k)))
    return dict(
        drops=g('infra_drops'), recovered=g('infra_recovered'), recon_attempts=g('infra_reconnect_attempts'),
        box_gone=g('infra_box_gone'), state_lost=g('infra_state_lost'), env_error=g('infra_env_error'),
        setup_fail=g('infra_setup_fail'), grade_conn_lost=g('infra_grade_conn_lost'),
        grade_upload=g('infra_grade_upload'), grade_no_reward=g('infra_grade_no_reward'),
        grade_reward_raise=g('infra_grade_reward_raise'), grade_finalize_timeout=g('infra_grade_finalize_timeout'),
        grade_timeout=g('infra_grade_timeout'), test_timeout=g('test_timeout'), walltime_cap=g('walltime_cap'),
        lost_turn=int(_f(m.get('infra_lost_turn')) if m.get('infra_lost_turn') is not None else -1),
        recon=0, lost=False, tout=False)

def to_view(r):
    """Normalize a row from either format into a uniform view dict."""
    if 'nodes' in r:  # ---- v1 prime-rl TRAIN/EVAL dump (verifiers Trace) ----
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
        inf = _infra(m)
        inf.update(recon=rc, lost=bool(lost), tout=bool(tout))
        errs = r.get('errors') or []
        # Real context size at the final turn from provider usage. Eval responses carry no
        # token_ids, so this (not the char estimate) is the reliable context-exhaustion signal.
        ctx_tokens = 0
        for n in reversed(r.get('nodes') or []):
            if n.get('sampled'):
                u = n.get('usage') or {}
                pt, ct = u.get('prompt_tokens'), u.get('completion_tokens')
                if pt is not None and ct is not None:
                    ctx_tokens = pt + ct
                break
        ctx_tokens = ctx_tokens or _est_tokens(msgs)
        return dict(
            fmt='v1' if any(k.startswith('infra_') for k in m) else 'v0-train',
            task=tname, task_key=task.get('idx', tname),
            reward=(r.get('rewards') or {}).get('reward', 0),
            turns=int(_f(m.get('num_turns'))), stop=r.get('stop_condition', '?'),
            truncated='?', tokens={'total': ctx_tokens}, est_tokens=ctx_tokens, ctx_tokens=ctx_tokens,
            traj=msgs, turn_timings=[], tb=None,
            has_error=bool(errs), err_msg=(errs[0].get('message', '') if errs else ''), infra=inf)
    # ---- v0 vf-eval results.jsonl ----
    info = r.get('info') or {}
    traj = (r.get('prompt') or []) + (r.get('completion') or [])
    rc, lost, tout = infra_flags(traj)
    tb = None
    if r.get('tb_test_output'):
        tb = dict(out=r.get('tb_test_output'), outcome=r.get('tb_outcome', '?'),
                  ec=r.get('tb_exit_code', '?'), msg=r.get('tb_message', ''))
    tname = info.get('task_name') or r.get('example_id') or '?'
    inf = _infra({})
    inf.update(recon=rc, lost=bool(lost), tout=bool(tout))
    return dict(
        fmt='v0', task=tname, task_key=tname,
        reward=r.get('reward') or 0, turns=r.get('num_turns', '?'), stop=r.get('stop_condition', '?'),
        truncated=r.get('is_truncated', '?'), tokens=r.get('token_usage') or {}, est_tokens=0, traj=traj,
        turn_timings=r.get('turn_timings') or [], tb=tb,
        has_error=False, err_msg='', infra=inf)

# Fine-grained failure classification mirroring the tb_v1 taxonomy. Returns
# (label, category) where category drives color + the filter buttons.
#   pass    : solved (reward>=1)
#   dropped : has_error -> excluded from wandb reward/pass@k (ModelError, grade/* drops)
#   ctx     : context-window overflow (kept as reward-0)
#   budget  : hit a turn/output/walltime cap (kept as reward-0)
#   infra   : env/test infra failure that survived
#   parse   : malformed tool-call output
#   fail    : genuine model failure (task_complete but tests red)
def classify_failure(v):
    inf = v['infra']
    if (v['reward'] or 0) >= 1.0:
        return ('pass', 'pass')
    if v['has_error']:
        # Context-exhaustion: the last turn filled the window -> a legit reward-0 (or
        # already-solved) failure the fixed eval_sink keeps, NOT an infra drop. Detect via
        # real usage, before the infra/model-error checks.
        if v.get('ctx_tokens', 0) >= CTX_CAP:
            return ('context-truncated', 'ctx')
        msg = v['err_msg'] or 'error'
        if msg == 'ModelError':
            return ('model-error', 'dropped')  # non-context model/inference error (rare)
        for key, lab in [('grade_conn_lost', 'grade/conn_lost'), ('grade_upload', 'grade/upload'),
                         ('grade_no_reward', 'grade/no_reward'), ('grade_reward_raise', 'grade/reward_raise'),
                         ('grade_finalize_timeout', 'grade/finalize_timeout'), ('grade_timeout', 'grade/timeout')]:
            if inf.get(key):
                return (lab, 'dropped')
        if inf['box_gone']:   return ('box-gone', 'dropped')
        if inf['state_lost']: return ('state-lost', 'dropped')
        if inf['setup_fail']: return ('setup-fail', 'dropped')
        return (msg[:32], 'dropped')
    stop = v['stop']            # survivors with reward 0
    if stop == 'context_length':     return ('ctx-length', 'ctx')
    if stop == 'max_turns_reached':  return ('max-turns', 'budget')
    if stop == 'max_output_tokens':  return ('max-output-tok', 'budget')
    if stop == '_stop_parse_errors': return ('parse-errors', 'parse')
    if inf['test_timeout']:          return ('test-timeout', 'infra')
    if inf['env_error']:             return ('env-error', 'infra')
    if inf['walltime_cap']:          return ('walltime-cap', 'budget')
    return ('tests-failed', 'fail')

views = [to_view(r) for r in rows]
for v in views:
    v['fail_label'], v['fail_cat'] = classify_failure(v)
FMT = views[0]['fmt'] if views else 'v0'

cards = []
from collections import Counter
n_pass = sum(1 for v in views if v['fail_cat'] == 'pass')
n_drop = sum(1 for v in views if v['has_error'])               # excluded from wandb reward/pass@k
n_surv = len(views) - n_drop
avg_surv = (n_pass / n_surv) if n_surv else 0.0                # micro reward over survivors == wandb avg@k
hist = Counter(v['fail_label'] for v in views if v['fail_cat'] != 'pass')   # failure-type breakdown
by = {}                                                         # pass@any per task, over survivors only
for v in views:
    if v['has_error']:
        continue
    by.setdefault(v['task_key'], []).append(v['fail_cat'] == 'pass')
solved = sum(1 for vv in by.values() if any(vv))

# fail-category -> badge color class (reuses existing palette + two new ones)
BCLS = {'pass': 'pass', 'fail': 'fail', 'dropped': 'drop', 'ctx': 'ctx',
        'budget': 'tout', 'infra': 'lost', 'parse': 'recon'}

for i, v in enumerate(views):
    task = v['task']
    cat, label = v['fail_cat'], v['fail_label']
    ok = cat == 'pass'
    turns, stop, tok = v['turns'], v['stop'], v['tokens']
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
    bcls = BCLS.get(cat, 'fail')
    badge = f'<span class="badge {bcls}">{esc(label.upper())}</span>'
    ibadges = '<span class="badge drop">DROPPED</span> ' if v['has_error'] else ''
    if inf['recon']:
        ibadges += f'<span class="badge recon">reconnect&times;{inf["recon"]}</span> '
    if inf['drops']:
        lt = f" lost@turn{inf['lost_turn']}" if inf['lost_turn'] >= 0 else ""
        ibadges += f'<span class="badge recon">drop&times;{inf["drops"]} &middot; recovered {inf["recovered"]}{lt}</span> '
    if inf['box_gone']:
        ibadges += '<span class="badge lost">box-gone</span> '
    if inf['state_lost']:
        ibadges += '<span class="badge lost">state-lost</span> '
    # meta: no reward (badge already says it); show est context size; surface error msg for drops
    tot = tok.get('total') if isinstance(tok, dict) else None
    parts = [f'turns={turns}', f'stop={esc(stop)}']
    if tot:
        parts.append(f'ctx&asymp;{int(tot):,} tok')
    if v['has_error'] and v['err_msg']:
        parts.append(f'<span style="color:#ff7b72">{esc(v["err_msg"][:48])}</span>')
    head = (f'{badge} {ibadges}<b>{esc(task)}</b> '
            f'<span class="meta">{" &middot; ".join(parts)}</span>')
    card_cls = 'pass' if ok else ('drop' if v['has_error'] else 'fail')
    attrs = (f'data-pass="{int(ok)}" data-cat="{cat}" data-drop="{int(v["has_error"])}" '
             f'data-fail="{esc(label)}"')
    cards.append(f'<details class="task {card_cls}" {attrs}><summary>{head}</summary><div class="conv">{body}</div></details>')

_src_label = esc(R.split('rollouts/')[-1] if FMT == 'v1' else R)
_title = ('vmvm-tb-v1 &middot; rollouts' if FMT == 'v1' else 'vmvm-tb &middot; eval trajectories')
_note = (' &middot; <i>has_error rollouts are excluded from wandb reward/pass@k</i>' if FMT == 'v1' else '')
# failure-type histogram, most common first, as colored chips
_HCLS = {'tests-failed': 'fail', 'ctx-length': 'ctx', 'max-turns': 'tout', 'max-output-tok': 'tout',
         'walltime-cap': 'tout', 'parse-errors': 'recon', 'test-timeout': 'lost', 'env-error': 'lost'}
def _hcls(lbl):
    if lbl.startswith(('model-error', 'grade/', 'box-', 'state-', 'setup-')):
        return 'drop'
    return _HCLS.get(lbl, 'fail')
_hist_html = ' '.join(
    f'<button class="badge {_hcls(lbl)}" onclick="ff(\'fail:{esc(lbl)}\')">{esc(lbl)} {n}</button>'
    for lbl, n in hist.most_common())

HTML = f'''<!doctype html><meta charset="utf-8"><title>vmvm-tb trajectories</title>
<style>
body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;background:#0d1117;color:#c9d1d9}}
header{{position:sticky;top:0;background:#161b22;padding:12px 20px;border-bottom:1px solid #30363d;z-index:5}}
h1{{margin:0 0 4px;font-size:16px}} .summary{{color:#8b949e;font-size:13px}}
.wrap{{padding:16px 20px;max-width:1100px;margin:0 auto}}
details.task{{border:1px solid #30363d;border-radius:8px;margin:8px 0;background:#161b22}}
details.task.pass{{border-left:4px solid #2ea043}} details.task.fail{{border-left:4px solid #f85149}}
details.task.drop{{border-left:4px dashed #6e7681;opacity:.85}}
summary{{cursor:pointer;padding:10px 14px;list-style:none}}
summary::-webkit-details-marker{{display:none}}
.badge{{font-weight:700;padding:1px 8px;border-radius:10px;font-size:11px;border:0;cursor:pointer}}
.badge.pass{{background:#15331d;color:#3fb950}} .badge.fail{{background:#3a1417;color:#ff7b72}}
.badge.recon{{background:#3a2e10;color:#e3b341}} .badge.lost{{background:#3a1417;color:#ff9e64}} .badge.tout{{background:#241a3a;color:#b392f0}}
.badge.ctx{{background:#0d2230;color:#58a6ff}} .badge.drop{{background:#21262d;color:#8b949e}}
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
.controls{{margin-top:6px}} .controls button{{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 10px;cursor:pointer;margin-right:6px}}
.hist{{margin-top:6px}} .hist .badge{{margin-right:5px}}
</style>
<header>
<h1>{_title} &middot; Qwen3.5-35B-A3B</h1>
<div class="summary">{len(rows)} rollouts &middot; pass {n_pass} &middot; raw pass@1 {n_pass}/{len(rows)} = {n_pass/len(rows):.3f} &middot; <b>survivor avg {n_pass}/{n_surv} = {avg_surv:.3f}</b> (=wandb) &middot; <span style="color:#8b949e">dropped {n_drop}</span> &middot; solved(any) {solved}/{len(by)} tasks{_note} &middot; source: {_src_label}</div>
<div class="hist">{_hist_html}</div>
<div class="controls">
<button onclick="document.querySelectorAll('details.task').forEach(d=>d.open=true)">expand all</button>
<button onclick="document.querySelectorAll('details.task').forEach(d=>d.open=false)">collapse all</button>
<button onclick="ff('')">all</button>
<button onclick="ff('pass')">pass</button>
<button onclick="ff('cat:fail')">tests-failed</button>
<button onclick="ff('cat:dropped')">dropped</button>
<button onclick="ff('cat:ctx')">ctx</button>
<button onclick="ff('cat:budget')">budget</button>
<button onclick="ff('cat:infra')">infra</button>
<button onclick="ff('cat:parse')">parse</button>
<input id="f" placeholder="filter task name..." oninput="for(const d of document.querySelectorAll('details.task')){{d.style.display=d.querySelector('summary').textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none'}}">
</div>
<script>
function ff(k){{document.querySelectorAll('details.task').forEach(d=>{{
  let s=true;
  if(k==='pass') s=(d.dataset.pass==='1');
  else if(k.startsWith('cat:')) s=(d.dataset.cat===k.slice(4));
  else if(k.startsWith('fail:')) s=(d.dataset.fail===k.slice(5));
  d.style.display=s?'':'none';
}});}}
</script>
</header>
<div class="wrap">{''.join(cards)}</div>
'''
open(OUT, 'w').write(HTML)
print('WROTE', OUT, '|', len(rows), 'rollouts |', f'format={FMT} |', f'pass@2 {solved}/{len(by)}')
