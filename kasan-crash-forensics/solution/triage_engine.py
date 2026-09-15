#!/usr/bin/env python3

"""
KASAN Crash Triage Engine
Parses kernel crash data, decodes shadow memory, classifies patches,
computes correlations, and produces a SQLite database + JSON report.
"""

import re
import json
import sqlite3
import os
import glob


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------

def addr_hex(val):
    """Convert integer address to hex string for storage."""
    if val is None:
        return None
    return format(val, 'x')


# ---------------------------------------------------------------------------
# KASAN crash report parser
# ---------------------------------------------------------------------------

def parse_report(text):
    report = {}

    # BUG line
    bug_m = re.search(
        r'BUG: KASAN: ([\w-]+) in (\w+)\+0x[\da-f]+/0x[\da-f]+ (\S+):(\d+)',
        text
    )
    if bug_m:
        report['bug_type'] = bug_m.group(1)
        report['faulting_function'] = bug_m.group(2)
        report['source_location'] = {
            'file': bug_m.group(3),
            'line': int(bug_m.group(4)),
        }
    else:
        report['bug_type'] = None
        report['faulting_function'] = None
        report['source_location'] = {'file': None, 'line': None}

    # Access line
    access_m = re.search(
        r'(Read|Write) of size (\d+) at addr ([0-9a-fA-F]+) by task (.+)/(\d+)',
        text
    )
    if access_m:
        report['access_type'] = access_m.group(1)
        report['access_size'] = int(access_m.group(2))
        report['buggy_addr'] = int(access_m.group(3), 16)
        report['comm'] = access_m.group(4)
        report['pid'] = int(access_m.group(5))
    else:
        report['access_type'] = None
        report['access_size'] = None
        report['buggy_addr'] = None
        report['comm'] = None
        report['pid'] = None

    # PID/Comm from CPU line (more reliable)
    pid_m = re.search(r'PID:\s*(\d+)\s+Comm:\s*(\S+)', text)
    if pid_m:
        report['pid'] = int(pid_m.group(1))
        report['comm'] = pid_m.group(2)

    # Call stacks
    report['call_stack'] = _extract_stack(
        text, 'Call Trace:',
        ['Allocated by task', 'The buggy address', '={10,}']
    )
    alloc_m = re.search(r'Allocated by task \d+:', text)
    if alloc_m:
        report['alloc_stack'] = _extract_stack(
            text[alloc_m.start():], 'Allocated by task',
            ['Freed by task', 'The buggy address', '={10,}']
        )
    else:
        report['alloc_stack'] = []
    free_m = re.search(r'Freed by task \d+:', text)
    if free_m:
        report['free_stack'] = _extract_stack(
            text[free_m.start():], 'Freed by task',
            ['The buggy address', '={10,}', 'Last potentially']
        )
    else:
        report['free_stack'] = []

    # SLAB metadata
    cache_m = re.search(r'belongs to the cache (\S+) of size (\d+)', text)
    if cache_m:
        report['slab_cache'] = cache_m.group(1)
        report['object_size'] = int(cache_m.group(2))
    else:
        report['slab_cache'] = None
        report['object_size'] = None

    obj_m = re.search(r'belongs to the object at ([0-9a-fA-F]+)', text)
    report['object_addr'] = int(obj_m.group(1), 16) if obj_m else None

    # Shadow memory
    report['shadow_state'] = _parse_shadow(text)

    return report


def _extract_stack(text, start_marker, end_patterns):
    stack = []
    in_section = False
    for line in text.split('\n'):
        if start_marker in line:
            in_section = True
            continue
        if in_section:
            stripped = line.strip()
            if any(re.search(pat, stripped) for pat in end_patterns):
                break
            entry = _parse_stack_entry(stripped)
            if entry:
                stack.append(entry)
    return stack


def _parse_stack_entry(line):
    if not line:
        return None
    skip = ('<', 'RIP:', 'RSP:', 'RAX:', 'RBX:', 'RCX:', 'RDX:',
            'RSI:', 'RDI:', 'RBP:', 'R08:', 'R09:', 'R10:', 'R11:',
            'R12:', 'R13:', 'R14:', 'R15:', 'Code:', 'flags:', 'raw:',
            'page', 'Hardware', 'CPU:')
    if line.startswith(skip):
        return None
    m = re.match(
        r'(\w+)\+0x[\da-f]+/0x[\da-f]+\s+([\w/.+_-]+\.\w+):(\d+)', line)
    if m:
        return {'function': m.group(1),
                'location': f'{m.group(2)}:{m.group(3)}'}
    m = re.match(
        r'(\w+)\s+([\w/.+_-]+/[\w/.+_-]+\.\w+):(\d+)', line)
    if m:
        return {'function': m.group(1),
                'location': f'{m.group(2)}:{m.group(3)}'}
    return None


def _parse_shadow(text):
    shadow_lines = []
    in_shadow = False
    for line in text.split('\n'):
        if 'Memory state around' in line:
            in_shadow = True
            continue
        if not in_shadow:
            continue
        stripped = line.strip()
        if stripped.startswith('^') or not stripped:
            continue
        if stripped.startswith('='):
            break
        is_current = line.lstrip().startswith('>') or line.startswith('>')
        cleaned = line.lstrip('>').strip()
        colon_idx = cleaned.find(':')
        if colon_idx < 0:
            continue
        addr_str = cleaned[:colon_idx].strip()
        vals_str = cleaned[colon_idx + 1:].strip()
        try:
            addr = int(addr_str, 16)
        except ValueError:
            continue
        values = []
        for v in vals_str.split():
            try:
                values.append(int(v, 16))
            except ValueError:
                continue
        if values:
            shadow_lines.append({
                'addr': addr, 'values': values,
                'is_buggy_line': is_current,
            })
    return shadow_lines


# ---------------------------------------------------------------------------
# Shadow memory decoder
# ---------------------------------------------------------------------------

def find_object_bounds(shadow_data, buggy_addr):
    """Reconstruct object boundaries from KASAN shadow memory."""
    shadow_map = {}
    for line in shadow_data:
        base = line['addr']
        for i, val in enumerate(line['values']):
            shadow_map[base + i * 8] = val

    aligned = (buggy_addr // 8) * 8
    buggy_shadow = shadow_map.get(aligned)
    if buggy_shadow is None:
        return None

    result = {'object_start': 0, 'object_size': 0,
              'is_freed': False, 'oob_distance': 0}

    if buggy_shadow == 0xfa:
        # Use-after-free: walk freed region
        result['is_freed'] = True
        addr = aligned
        while (addr - 8) in shadow_map and shadow_map[addr - 8] == 0xfa:
            addr -= 8
        result['object_start'] = addr
        addr = aligned
        while (addr + 8) in shadow_map and shadow_map[addr + 8] == 0xfa:
            addr += 8
        result['object_size'] = (addr + 8) - result['object_start']

    elif buggy_shadow in (0xfc, 0xfe):
        # Out-of-bounds: access in redzone
        addr = aligned
        while (addr - 8) in shadow_map and shadow_map[addr - 8] in (0xfc, 0xfe):
            addr -= 8
        obj_end = addr
        addr = obj_end - 8
        accessible = []
        while addr in shadow_map:
            sv = shadow_map[addr]
            if sv == 0x00 or (0x01 <= sv <= 0x07):
                accessible.insert(0, (addr, sv))
                addr -= 8
            else:
                break
        if accessible:
            result['object_start'] = accessible[0][0]
            result['object_size'] = sum(
                8 if sv == 0x00 else sv for _, sv in accessible)
        else:
            result['object_start'] = obj_end
            result['object_size'] = 0
        result['oob_distance'] = buggy_addr - (
            result['object_start'] + result['object_size'])

    elif 0x00 <= buggy_shadow <= 0x07:
        # Within object
        addr = aligned
        while (addr - 8) in shadow_map and (
            shadow_map[addr - 8] == 0x00 or
            0x01 <= shadow_map[addr - 8] <= 0x07
        ):
            addr -= 8
        result['object_start'] = addr
        a = result['object_start']
        size = 0
        while a in shadow_map and (
            shadow_map[a] == 0x00 or 0x01 <= shadow_map[a] <= 0x07
        ):
            size += 8 if shadow_map[a] == 0x00 else shadow_map[a]
            a += 8
        result['object_size'] = size

    return result


# ---------------------------------------------------------------------------
# Multi-VM voting protocol
# ---------------------------------------------------------------------------

def classify_patch(results):
    """Classify a patch based on multi-VM test outcomes."""
    total = len(results)
    if total == 0:
        return {'verdict': 'Pass', 'confidence': 0.0}

    counts = {'no_crash': 0, 'crash_same': 0, 'crash_different': 0,
              'boot_fail': 0, 'timeout': 0}
    for r in results:
        o = r.get('outcome', 'timeout')
        if o in counts:
            counts[o] += 1

    crash_count = counts['crash_same'] + counts['crash_different']
    clean_count = counts['no_crash'] + counts['timeout']

    if counts['boot_fail'] > 0:
        verdict = 'BootFail'
        confidence = counts['boot_fail'] / total
    elif crash_count == 0:
        verdict = 'Pass'
        confidence = clean_count / total
    elif crash_count > total / 2:
        verdict = 'Trigger'
        confidence = counts['crash_same'] / total
    else:
        verdict = 'Racey'
        confidence = 1.0 - abs(crash_count - clean_count) / total

    return {'verdict': verdict, 'confidence': round(confidence, 4)}


# ---------------------------------------------------------------------------
# Patch correlator
# ---------------------------------------------------------------------------

def parse_diff(text):
    """Extract modified files and functions from a unified diff."""
    files = set()
    functions = set()
    for line in text.split('\n'):
        if line.startswith('--- a/'):
            p = line[6:].strip()
            if p != '/dev/null':
                files.add(p)
        elif line.startswith('+++ b/'):
            p = line[6:].strip()
            if p != '/dev/null':
                files.add(p)
        hunk_m = re.match(r'@@ [^@]+ @@\s*(.*)', line)
        if hunk_m:
            ctx = hunk_m.group(1).strip()
            if ctx:
                fm = re.match(r'(?:[\w*]+\s+)*(\w+)\s*\(', ctx)
                if fm:
                    functions.add(fm.group(1))
    return {'files': sorted(files), 'functions': sorted(functions)}


def correlate(report, patch_text):
    """Score how likely a patch addresses a given crash."""
    diff = parse_diff(patch_text)
    patch_files = set(diff['files'])
    patch_funcs = set(diff['functions'])

    stack_files = set()
    stack_funcs = set()
    for key in ('call_stack', 'alloc_stack', 'free_stack'):
        stack = report.get(key)
        if not stack:
            continue
        for entry in stack:
            fn = entry.get('function', '')
            if fn:
                stack_funcs.add(fn)
            loc = entry.get('location', '')
            if ':' in loc:
                stack_files.add(loc.rsplit(':', 1)[0])

    src = report.get('source_location')
    if src and src.get('file'):
        stack_files.add(src['file'])

    faulting = report.get('faulting_function', '')
    file_overlap = sorted(patch_files & stack_files)
    func_overlap = sorted(patch_funcs & stack_funcs)
    touches = faulting in patch_funcs

    score = 0.0
    if file_overlap:
        score += 0.3
    if touches:
        score += 0.4
    elif func_overlap:
        score += 0.2
    if func_overlap and not touches:
        score += 0.1
    score = min(score, 1.0)

    return {
        'touches_faulting_function': touches,
        'file_overlap': file_overlap,
        'plausibility_score': round(score, 2),
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    crash_dir = '/app/crash_data'

    # Discover files
    report_files = sorted(glob.glob(os.path.join(crash_dir, 'report_*.txt')))
    patch_files_list = sorted(glob.glob(os.path.join(crash_dir, 'patch_*.diff')))
    vm_files = sorted(glob.glob(os.path.join(crash_dir, 'vm_results_*.json')))

    # Parse crash reports
    crashes = []
    for rf in report_files:
        with open(rf) as f:
            rpt = parse_report(f.read())
        rpt['_file'] = os.path.basename(rf)
        if rpt['shadow_state']:
            rpt['_shadow'] = find_object_bounds(
                rpt['shadow_state'], rpt['buggy_addr'])
        else:
            rpt['_shadow'] = None
        crashes.append(rpt)

    # Classify patches via VM results
    verdicts = []
    for vf in vm_files:
        with open(vf) as f:
            vm_data = json.load(f)
        v = classify_patch(vm_data)
        num = re.search(r'(\d+)', os.path.basename(vf)).group(1)
        v['_patch_file'] = f'patch_{num}.diff'
        verdicts.append(v)

    # Read patch texts
    patches = {}
    for pf in patch_files_list:
        with open(pf) as f:
            patches[os.path.basename(pf)] = f.read()

    # ------------------------------------------------------------------
    # Build SQLite database
    # ------------------------------------------------------------------
    db_path = '/app/triage.db'
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)

    db.execute('''CREATE TABLE crashes (
        id INTEGER PRIMARY KEY,
        report_file TEXT,
        bug_type TEXT,
        access_type TEXT,
        access_size INTEGER,
        faulting_function TEXT,
        faulting_file TEXT,
        faulting_line INTEGER,
        pid INTEGER,
        comm TEXT,
        slab_cache TEXT,
        object_size INTEGER,
        buggy_addr TEXT,
        object_addr TEXT,
        shadow_object_start TEXT,
        shadow_object_size INTEGER,
        shadow_is_freed INTEGER,
        shadow_oob_distance INTEGER
    )''')

    db.execute('''CREATE TABLE patch_verdicts (
        id INTEGER PRIMARY KEY,
        patch_file TEXT,
        verdict TEXT,
        confidence REAL
    )''')

    db.execute('''CREATE TABLE correlations (
        crash_id INTEGER,
        patch_id INTEGER,
        touches_faulting_function INTEGER,
        file_overlap TEXT,
        plausibility_score REAL
    )''')

    # Insert crashes
    for i, c in enumerate(crashes, 1):
        s = c.get('_shadow')
        db.execute(
            'INSERT INTO crashes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (i, c['_file'], c['bug_type'], c['access_type'], c['access_size'],
             c['faulting_function'], c['source_location']['file'],
             c['source_location']['line'], c['pid'], c['comm'],
             c['slab_cache'], c['object_size'],
             addr_hex(c['buggy_addr']), addr_hex(c['object_addr']),
             addr_hex(s['object_start']) if s else None,
             s['object_size'] if s else None,
             1 if s and s['is_freed'] else (0 if s else None),
             s['oob_distance'] if s else None))

    # Insert patch verdicts
    for i, v in enumerate(verdicts, 1):
        db.execute('INSERT INTO patch_verdicts VALUES (?,?,?,?)',
                   (i, v['_patch_file'], v['verdict'], v['confidence']))

    # Insert correlations (every crash x every patch)
    for ci, crash in enumerate(crashes, 1):
        for pi, v in enumerate(verdicts, 1):
            pf = v['_patch_file']
            if pf in patches:
                corr = correlate(crash, patches[pf])
            else:
                corr = {'touches_faulting_function': False,
                        'file_overlap': [], 'plausibility_score': 0.0}
            db.execute('INSERT INTO correlations VALUES (?,?,?,?,?)',
                       (ci, pi,
                        1 if corr['touches_faulting_function'] else 0,
                        json.dumps(corr['file_overlap']),
                        corr['plausibility_score']))

    db.commit()
    db.close()

    # ------------------------------------------------------------------
    # Generate JSON triage report
    # ------------------------------------------------------------------
    report_entries = []
    for ci, crash in enumerate(crashes, 1):
        s = crash.get('_shadow')
        shadow_analysis = None
        if s:
            shadow_analysis = {
                'object_start': addr_hex(s['object_start']),
                'object_size': s['object_size'],
                'is_freed': s['is_freed'],
                'oob_distance': s['oob_distance'],
            }

        rec_patches = []
        for v in verdicts:
            pf = v['_patch_file']
            corr = correlate(crash, patches[pf]) if pf in patches else {
                'plausibility_score': 0.0}
            rec_patches.append({
                'patch_file': pf,
                'verdict': v['verdict'],
                'confidence': v['confidence'],
                'plausibility_score': corr['plausibility_score'],
            })
        rec_patches.sort(key=lambda x: x['plausibility_score'], reverse=True)

        report_entries.append({
            'crash_id': ci,
            'report_file': crash['_file'],
            'bug_type': crash['bug_type'],
            'faulting_function': crash['faulting_function'],
            'shadow_analysis': shadow_analysis,
            'recommended_patches': rec_patches,
        })

    with open('/app/triage_report.json', 'w') as f:
        json.dump(report_entries, f, indent=2)

    print('Triage complete: /app/triage.db + /app/triage_report.json')


if __name__ == '__main__':
    main()
