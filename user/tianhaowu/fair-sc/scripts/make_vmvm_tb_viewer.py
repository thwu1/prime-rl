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
PARSE_FEEDBACK = "Your last message could not be parsed as a valid tool call"

def esc(s):
    return html.escape(str(s)).replace('</script>', '<\\/script>')

def _content_text(m):
    c = m.get('content', '') if isinstance(m, dict) else str(m)
    if isinstance(c, list):
        return '\n'.join(p.get('text', '') if isinstance(p, dict) else str(p) for p in c)
    return str(c or '')

def _is_parse_feedback(m):
    return PARSE_FEEDBACK in _content_text(m)

def _tool_name(tc):
    if not isinstance(tc, dict):
        return ''
    fn = tc.get('function') or {}
    return tc.get('name') or (fn.get('name') if isinstance(fn, dict) else '') or ''

def _assistant_no_tool(m):
    return isinstance(m, dict) and m.get('role') == 'assistant' and not (m.get('tool_calls') or [])

def _assistant_bad_tool(m):
    if not isinstance(m, dict) or m.get('role') != 'assistant':
        return False
    return any(_tool_name(tc) not in ('bash', 'submit') for tc in (m.get('tool_calls') or []))

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
    if _is_parse_feedback(m):
        cls += ' parsefeedback'
    if _assistant_no_tool(m):
        cls += ' notool'
    if _assistant_bad_tool(m):
        cls += ' badtool'
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

def _cmd_preview(m):
    """Short one-line preview of an assistant turn's first tool command, for the turn summary."""
    for tc in (m.get('tool_calls') or []):
        fn = tc.get('function') or tc
        args = fn.get('arguments', '')
        cmd = args
        if isinstance(args, str):
            try:
                a = json.loads(args)
                cmd = a.get('command', args) if isinstance(a, dict) else args
            except Exception:
                cmd = args
        elif isinstance(args, dict):
            cmd = args.get('command', json.dumps(args))
        return ' '.join(str(cmd).split())[:90]
    return ' '.join(str(m.get('content') or '').split())[:90]

def turns_html(msgs):
    """Group the conversation into collapsible turns (new turn at each assistant message;
    the leading system+task is the 'prompt' group). First turn is open, the rest collapsed."""
    groups, cur = [], []
    for m in msgs:
        role = m.get('role') if isinstance(m, dict) else '?'
        if role == 'assistant' and cur:
            groups.append(cur); cur = []
        cur.append(m)
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        label = 'prompt' if i == 0 else f'turn {i}'
        prev = ''
        for m in g:
            if isinstance(m, dict) and m.get('role') == 'assistant':
                prev = _cmd_preview(m); break
        inner = ''.join(msg_html(m) for m in g)
        op = ' open' if i == 0 else ''
        has_parse = any(isinstance(m, dict) and _is_parse_feedback(m) for m in g)
        has_no_tool = any(_assistant_no_tool(m) for m in g)
        has_bad_tool = any(_assistant_bad_tool(m) for m in g)
        turn_classes = ['turn']
        tags = []
        if has_no_tool:
            turn_classes.append('notool')
            tags.append('<span class="turntag notool">no-tool</span>')
        if has_bad_tool:
            turn_classes.append('badtool')
            tags.append('<span class="turntag badtool">bad-tool</span>')
        if has_parse:
            turn_classes.append('parseerr')
            tags.append('<span class="turntag parseerr">parse-error</span>')
        out.append(f'<details class="{" ".join(turn_classes)}"{op}><summary>{esc(label)}{"".join(tags)}'
                   f'<span class="tprev">{esc(prev)}</span></summary>{inner}</details>')
    return ''.join(out)

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

# Two-tier badge model:
#   Tier 1 outcome — PASS / FAIL by reward, UNLESS the rollout is an infra failure
#     (gray INFRA, no pass/fail: the outcome was infra-determined, not the model's doing).
#   Tier 2 chips — orthogonal "what was abnormal" attributes, shown only when present.
def is_truncate(v):
    # ran out of token budget: filled the context window, or stopped on context_length /
    # max_output_tokens (both are token-budget truncation, kept by the fixed eval_sink).
    return v.get('ctx_tokens', 0) >= CTX_CAP or v['stop'] in ('context_length', 'max_output_tokens')

def is_infra(v):
    inf = v['infra']
    if v['has_error'] and not is_truncate(v):
        return True                                      # genuine error, excluded from metric
    return bool(inf['env_error'] or inf['test_timeout'])  # infra outcome even if kept

def outcome(v):
    if is_infra(v):
        return ('INFRA', 'infra')                        # gray, no pass/fail
    return ('PASS', 'pass') if (v['reward'] or 0) >= 1.0 else ('FAIL', 'fail')

def chips(v):
    """Tier-2 attribute chips: (label, css_class, filter_key). Shown only when present."""
    inf = v['infra']; out = []
    if is_truncate(v):                    out.append(('truncate', 'lim', 'truncate'))
    if v['stop'] == 'max_turns_reached':  out.append(('max-turns', 'lim', 'maxturns'))
    if inf['walltime_cap']:               out.append(('walltime', 'lim', 'walltime'))
    if v['stop'] == '_stop_parse_errors': out.append(('parse-err', 'tout', 'parse'))
    if is_infra(v):
        reason = ('model-error' if v['err_msg'] == 'ModelError'
                  else 'grade/conn_lost' if inf['grade_conn_lost']
                  else 'grade/timeout' if inf['grade_timeout']
                  else 'grade/upload' if inf['grade_upload']
                  else 'box-gone' if inf['box_gone']
                  else 'state-lost' if inf['state_lost']
                  else 'setup-fail' if inf['setup_fail']
                  else 'env-error' if inf['env_error']
                  else 'test-timeout' if inf['test_timeout']
                  else (v['err_msg'][:24] if v['err_msg'] else 'infra'))
        out.append((reason, 'infra', 'infra'))
    elif inf['drops']:                    # recovered infra — model still produced an outcome
        lt = f" lost@{inf['lost_turn']}" if inf['lost_turn'] >= 0 else ""
        out.append((f"drop×{inf['drops']}·rec{inf['recovered']}{lt}", 'recon', 'infradrop'))
    elif inf['recon']:
        out.append((f"reconnect×{inf['recon']}", 'recon', 'infradrop'))
    return out

views = [to_view(r) for r in rows]
for v in views:
    v['outcome'], v['ocls'] = outcome(v)
    v['chips'] = chips(v)
FMT = views[0]['fmt'] if views else 'v0'

cards = []
from collections import Counter
n_pass = sum(1 for v in views if v['ocls'] == 'pass')
n_fail = sum(1 for v in views if v['ocls'] == 'fail')
n_infra = sum(1 for v in views if v['ocls'] == 'infra')
n_dropped = sum(1 for v in views if v['has_error'] and not is_truncate(v))  # excluded from wandb metric
n_kept = len(views) - n_dropped
avg_kept = (n_pass / n_kept) if n_kept else 0.0                              # == wandb avg@k
hist = Counter(k for v in views for (_, _, k) in v['chips'])                 # chip frequencies (overlapping)
by = {}                                                                      # solved(any) per task over kept
for v in views:
    if v['has_error'] and not is_truncate(v):
        continue
    by.setdefault(v['task_key'], []).append(v['ocls'] == 'pass')
solved = sum(1 for vv in by.values() if any(vv))

for i, v in enumerate(views):
    task = v['task']
    oc_label, oc_cls = v['outcome'], v['ocls']
    turns, stop, tok = v['turns'], v['stop'], v['tokens']
    body = turns_html(v['traj'])
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
    badge = f'<span class="badge {oc_cls}">{oc_label}</span>'
    chip_html = ''.join(f'<span class="badge {c}">{esc(lab)}</span> ' for lab, c, _ in v['chips'])
    # meta: outcome badge already carries pass/fail; show turns, stop, context size, error text
    tot = tok.get('total') if isinstance(tok, dict) else None
    parts = [f'turns={turns}', f'stop={esc(stop)}']
    if tot:
        parts.append(f'ctx&asymp;{int(tot):,} tok')
    if v['has_error'] and v['err_msg']:
        parts.append(f'<span style="color:#8b949e">{esc(v["err_msg"][:48])}</span>')
    head = (f'{badge} {chip_html}<b>{esc(task)}</b> '
            f'<span class="meta">{" &middot; ".join(parts)}</span>')
    attr_keys = ' '.join(sorted({k for _, _, k in v['chips']}))
    attrs = f'data-outcome="{oc_cls}" data-attrs="{attr_keys}"'
    cards.append(f'<details class="task {oc_cls}" {attrs}><summary>{head}</summary><div class="conv">{body}</div></details>')

_src_label = esc(R.split('rollouts/')[-1] if FMT == 'v1' else R)
_title = ('vmvm-tb-v1 &middot; rollouts' if FMT == 'v1' else 'vmvm-tb &middot; eval trajectories')
_note = (' &middot; <i>INFRA = excluded from wandb reward/pass@k</i>' if FMT == 'v1' else '')
# attribute-frequency histogram (clickable). Rollouts may have >1 chip, so counts overlap.
_KCSS = {'truncate': 'lim', 'maxturns': 'lim', 'walltime': 'lim', 'parse': 'tout', 'infra': 'infra', 'infradrop': 'recon'}
_KLAB = {'truncate': 'truncate', 'maxturns': 'max-turns', 'walltime': 'walltime', 'parse': 'parse-err', 'infra': 'infra', 'infradrop': 'drop·rec'}
_hist_html = ' '.join(
    f'<button class="badge {_KCSS.get(k, "fail")}" onclick="ff(\'attr:{k}\')">{_KLAB.get(k, k)} {n}</button>'
    for k, n in hist.most_common())

HTML = f'''<!doctype html><meta charset="utf-8"><title>vmvm-tb trajectories</title>
<style>
body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;background:#0d1117;color:#c9d1d9}}
header{{position:sticky;top:0;background:#161b22;padding:12px 20px;border-bottom:1px solid #30363d;z-index:5}}
h1{{margin:0 0 4px;font-size:16px}} .summary{{color:#8b949e;font-size:13px}}
.wrap{{padding:16px 20px;max-width:1100px;margin:0 auto}}
details.task{{border:1px solid #30363d;border-radius:8px;margin:8px 0;background:#161b22}}
details.task.pass{{border-left:4px solid #2ea043}} details.task.fail{{border-left:4px solid #f85149}}
details.task.infra{{border-left:4px dashed #6e7681;opacity:.85}}
summary{{cursor:pointer;padding:10px 14px;list-style:none}}
summary::-webkit-details-marker{{display:none}}
.badge{{font-weight:700;padding:1px 8px;border-radius:10px;font-size:11px;border:0;cursor:pointer}}
.badge.pass{{background:#15331d;color:#3fb950}} .badge.fail{{background:#3a1417;color:#ff7b72}}
.badge.recon{{background:#3a2e10;color:#e3b341}} .badge.lost{{background:#3a1417;color:#ff9e64}} .badge.tout{{background:#241a3a;color:#b392f0}}
.badge.ctx{{background:#0d2230;color:#58a6ff}} .badge.drop{{background:#21262d;color:#8b949e}}
.badge.lim{{background:#0d2230;color:#58a6ff}} .badge.infra{{background:#21262d;color:#8b949e}}
.meta{{color:#8b949e;font-size:12px;margin-left:8px}}
.conv{{padding:6px 14px 14px}}
details.turn{{margin:6px 0;border:1px solid #21262d;border-radius:6px;background:#0d1117}}
details.turn.notool{{border-color:#d29922}}
details.turn.badtool{{border-color:#b392f0}}
details.turn.parseerr{{border-color:#f85149}}
details.turn>summary{{padding:5px 12px;color:#8b949e;font-size:12px;font-weight:600;cursor:pointer}}
details.turn[open]>summary{{border-bottom:1px solid #21262d}}
.turntag{{display:inline-block;margin-left:8px;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:700}}
.turntag.notool{{background:#3a2e10;color:#e3b341;border:1px solid #6b5716}}
.turntag.badtool{{background:#241a3a;color:#d2b7ff;border:1px solid #4f3b76}}
.turntag.parseerr{{background:#3a1417;color:#ff7b72;border:1px solid #6e252a}}
.tprev{{color:#6e7681;font-weight:400;margin-left:10px;font:11px ui-monospace,Menlo,monospace}}
.msg{{margin:8px 0;border-radius:6px;overflow:hidden;border:1px solid #21262d}}
.msg .role{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;padding:3px 10px;color:#8b949e;background:#0d1117}}
.msg pre{{margin:0;padding:10px 12px;white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,Menlo,monospace}}
.msg.sys pre{{background:#1c2128}} .msg.user pre{{background:#0d1f2d}}
.msg.asst pre{{background:#12261a}} .msg.tool pre{{background:#251c0d}}
.msg.notool pre{{background:#2b250d;color:#ffdf8a;border-left:2px solid #d29922}}
.msg.badtool pre.toolcall{{background:#241a3a;color:#d2b7ff;border-left:2px solid #b392f0}}
.msg.parsefeedback pre{{background:#3a1417;color:#ffdad7;border-left:2px solid #f85149}}
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
<div class="summary">{len(rows)} rollouts &middot; <span style="color:#3fb950">PASS {n_pass}</span> / <span style="color:#ff7b72">FAIL {n_fail}</span> / <span style="color:#8b949e">INFRA {n_infra}</span> &middot; raw pass@1 {n_pass}/{len(rows)} = {n_pass/len(rows):.3f} &middot; <b>survivor avg {avg_kept:.3f}</b> (=wandb) &middot; dropped {n_dropped} &middot; solved(any) {solved}/{len(by)} tasks{_note} &middot; source: {_src_label}</div>
<div class="hist">{_hist_html}</div>
<div class="controls">
<button onclick="document.querySelectorAll('details.task').forEach(d=>d.open=true)">expand all</button>
<button onclick="document.querySelectorAll('details.task').forEach(d=>d.open=false)">collapse all</button>
<button onclick="ff('')">all</button>
<button onclick="ff('out:pass')">PASS</button>
<button onclick="ff('out:fail')">FAIL</button>
<button onclick="ff('out:infra')">INFRA</button>
<button onclick="ff('attr:truncate')">truncate</button>
<button onclick="ff('attr:maxturns')">max-turns</button>
<button onclick="ff('attr:walltime')">walltime</button>
<button onclick="ff('attr:parse')">parse-err</button>
<button onclick="ff('attr:infradrop')">drop·rec</button>
<button onclick="ff('clean')">clean</button>
<input id="f" placeholder="filter task name..." oninput="for(const d of document.querySelectorAll('details.task')){{d.style.display=d.querySelector('summary').textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none'}}">
</div>
<script>
function ff(k){{document.querySelectorAll('details.task').forEach(d=>{{
  let s=true;
  if(k.startsWith('out:')) s=(d.dataset.outcome===k.slice(4));
  else if(k.startsWith('attr:')) s=((' '+d.dataset.attrs+' ').includes(' '+k.slice(5)+' '));
  else if(k==='clean') s=(d.dataset.attrs===''&&d.dataset.outcome!=='infra');
  d.style.display=s?'':'none';
}});}}
</script>
</header>
<div class="wrap">{''.join(cards)}</div>
'''
open(OUT, 'w').write(HTML)
print('WROTE', OUT, '|', len(rows), 'rollouts |', f'format={FMT} |', f'pass@2 {solved}/{len(by)}')
