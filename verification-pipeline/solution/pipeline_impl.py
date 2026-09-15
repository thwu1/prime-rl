#!/usr/bin/env python3

"""seL4 Verification Pipeline Auditor — reference solution."""

import sys
import json
import os
import re
import glob as glob_mod
from xml.etree import ElementTree
from collections import defaultdict

SPECS_DIR = '/app/specs'
ROOTS_DIR = '/app/roots'
EXCLUSIONS_FILE = '/app/config/exclusions.json'


# ---------------------------------------------------------------------------
# XML Test Spec Parsing
# ---------------------------------------------------------------------------

class TestEnv:
    __slots__ = ('cpu_timeout', 'depends')

    def __init__(self, cpu_timeout=0.0, depends=None):
        self.cpu_timeout = cpu_timeout
        self.depends = frozenset() if depends is None else depends

    def update(self, cpu_timeout=None, depends=None):
        new = TestEnv.__new__(TestEnv)
        new.cpu_timeout = cpu_timeout if cpu_timeout is not None else self.cpu_timeout
        new.depends = (self.depends | frozenset(depends)) if depends is not None else self.depends
        return new


class Test:
    __slots__ = ('name', 'cpu_timeout', 'depends')

    def __init__(self, name, cpu_timeout, depends):
        self.name = name
        self.cpu_timeout = int(cpu_timeout)
        self.depends = set(depends)


def _parse_attributes(element, env):
    cpu = element.get('cpu-timeout')
    dep = element.get('depends')
    new_cpu = float(cpu) if cpu is not None else None
    new_dep = dep.split() if dep is not None else None
    if new_cpu is not None or new_dep is not None:
        return env.update(cpu_timeout=new_cpu, depends=new_dep)
    return env


def _parse_test(element, env):
    return [Test(element.get('name'), env.cpu_timeout, env.depends)]


def _parse_sequence(element, env):
    tests = []
    for child in element:
        if child.tag not in ('test', 'set', 'sequence', 'testsuite'):
            continue
        child_env = _parse_attributes(child, env)
        new_tests = _dispatch(child, child_env)
        tests.extend(new_tests)
        env = env.update(depends=[t.name for t in new_tests])
    return tests


def _parse_set(element, env):
    tests = []
    for child in element:
        if child.tag not in ('test', 'set', 'sequence', 'testsuite'):
            continue
        child_env = _parse_attributes(child, env)
        tests.extend(_dispatch(child, child_env))
    return tests


def _dispatch(element, env):
    if element.tag == 'test':
        return _parse_test(element, env)
    if element.tag == 'sequence':
        return _parse_sequence(element, env)
    return _parse_set(element, env)


def parse_xml_file(filepath):
    tree = ElementTree.parse(filepath)
    root = tree.getroot()
    env = _parse_attributes(root, TestEnv())
    return _parse_set(root, env)


def load_all_tests():
    tests = []
    for fp in sorted(glob_mod.glob(os.path.join(SPECS_DIR, '*.xml'))):
        tests.extend(parse_xml_file(fp))
    return tests


# ---------------------------------------------------------------------------
# ROOT File Parsing (Isabelle session definitions)
# ---------------------------------------------------------------------------

class Session:
    __slots__ = ('name', 'parent', 'session_deps', 'theories')

    def __init__(self, name, parent, session_deps, theories):
        self.name = name
        self.parent = parent
        self.session_deps = list(session_deps)
        self.theories = list(theories)

    @property
    def all_deps(self):
        return sorted(set([self.parent] + self.session_deps))


def parse_root_file(filepath):
    with open(filepath) as f:
        content = f.read()

    # Strip ML-style comments (* ... *)
    content = re.sub(r'\(\*.*?\*\)', '', content, flags=re.DOTALL)

    sessions = []
    cur_name = None
    cur_parent = None
    cur_sdeps = []
    cur_theories = []
    cur_block = None

    def _flush():
        nonlocal cur_name
        if cur_name is not None:
            sessions.append(Session(cur_name, cur_parent, cur_sdeps, cur_theories))
        cur_name = None

    for line in content.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue

        m = re.match(r'^session\s+(\S+)\s*=\s*(\S+)\s*\+', stripped)
        if m:
            _flush()
            cur_name = m.group(1)
            cur_parent = m.group(2)
            cur_sdeps = []
            cur_theories = []
            cur_block = None
            continue

        if cur_name is None:
            continue

        if stripped == 'sessions':
            cur_block = 'sessions'
            continue
        if stripped == 'theories':
            cur_block = 'theories'
            continue
        if stripped.startswith('options'):
            cur_block = 'options'
            continue
        if stripped == 'directories':
            cur_block = 'directories'
            continue

        if cur_block == 'sessions':
            cur_sdeps.append(stripped)
        elif cur_block == 'theories':
            cur_theories.append(stripped.strip('"'))

    _flush()
    return sessions


def load_all_sessions():
    sessions = []
    for fp in sorted(glob_mod.glob(os.path.join(ROOTS_DIR, '*.ROOT'))):
        sessions.extend(parse_root_file(fp))
    return sessions


# ---------------------------------------------------------------------------
# Graph Algorithms
# ---------------------------------------------------------------------------

def compute_transitive_deps(tests_by_name):
    cache = {}

    def _get(name):
        if name in cache:
            return cache[name]
        t = tests_by_name[name]
        result = set(t.depends)
        for dep in t.depends:
            if dep in tests_by_name:
                result |= _get(dep)
        cache[name] = result
        return result

    for n in tests_by_name:
        _get(n)
    return cache


def compute_cascade_exclusions(tests_by_name, trans_deps, direct_excluded):
    direct_set = set(direct_excluded)
    cascade_set = set()
    for name in tests_by_name:
        if name not in direct_set and trans_deps[name] & direct_set:
            cascade_set.add(name)
    return cascade_set, direct_set | cascade_set


def _topo_sort(tests_by_name, available):
    in_deg = defaultdict(int)
    successors = defaultdict(list)
    for name in available:
        for dep in tests_by_name[name].depends:
            if dep in available:
                in_deg[name] += 1
                successors[dep].append(name)
    queue = sorted(n for n in available if in_deg[n] == 0)
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for s in sorted(successors[node]):
            in_deg[s] -= 1
            if in_deg[s] == 0:
                queue.append(s)
                queue.sort()
    return order


def compute_critical_path(tests_by_name, available):
    order = _topo_sort(tests_by_name, available)
    est, eft, pred = {}, {}, {}
    for name in order:
        t = tests_by_name[name]
        max_eft = 0
        max_p = None
        for dep in t.depends:
            if dep in available and eft[dep] > max_eft:
                max_eft = eft[dep]
                max_p = dep
        est[name] = max_eft
        eft[name] = max_eft + t.cpu_timeout
        pred[name] = max_p

    end = max(available, key=lambda n: (eft[n], n))
    path = []
    cur = end
    while cur is not None:
        path.append(cur)
        cur = pred[cur]
    path.reverse()
    return path, eft[end]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_exclusions():
    with open(EXCLUSIONS_FILE) as f:
        return json.load(f)


def _apply_exclusions(tests_by_name, trans_deps, arch):
    excl = _load_exclusions()
    direct = [t for t in excl.get(arch, []) if t in tests_by_name]
    _, all_excl = compute_cascade_exclusions(tests_by_name, trans_deps, direct)
    return direct, all_excl


def _apply_modified_exclusions(tests_by_name, trans_deps, arch, add_excl, remove_excl):
    excl = _load_exclusions()
    original = set(excl.get(arch, []))
    modified = (original | set(add_excl)) - set(remove_excl)
    direct = [t for t in sorted(modified) if t in tests_by_name]
    _, all_excl = compute_cascade_exclusions(tests_by_name, trans_deps, direct)
    return direct, all_excl


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_parse_sessions(_tests, _tbn, _td):
    sessions = load_all_sessions()
    result = {
        'sessions': sorted([{
            'name': s.name,
            'parent': s.parent,
            'deps': s.all_deps,
            'theories': sorted(s.theories),
        } for s in sessions], key=lambda x: x['name']),
        'total': len(sessions),
    }
    print(json.dumps(result))


def cmd_parse_tests(tests, _tbn, _td):
    result = {
        'tests': sorted([{
            'name': t.name,
            'cpu_timeout': t.cpu_timeout,
            'direct_deps': sorted(t.depends),
        } for t in tests], key=lambda x: x['name']),
        'total': len(tests),
    }
    print(json.dumps(result))


def cmd_reconcile(tests, _tbn, _td):
    sessions = load_all_sessions()
    session_names = set(s.name for s in sessions)
    test_names = set(t.name for t in tests)

    matched = sorted(session_names & test_names)
    root_only = sorted(session_names - test_names)
    test_only = sorted(test_names - session_names)

    print(json.dumps({
        'matched': matched,
        'root_only': root_only,
        'test_only': test_only,
        'matched_count': len(matched),
        'root_only_count': len(root_only),
        'test_only_count': len(test_only),
    }))


def cmd_cascade_exclude(_tests, tbn, td):
    arch = sys.argv[2]
    direct, all_excl = _apply_exclusions(tbn, td, arch)
    cascade = sorted(all_excl - set(direct))
    print(json.dumps({
        'directly_excluded': sorted(direct),
        'cascade_excluded': cascade,
        'total_excluded_count': len(all_excl),
    }))


def cmd_critical_path(_tests, tbn, td):
    arch = sys.argv[2]
    _, all_excl = _apply_exclusions(tbn, td, arch)
    available = set(tbn) - all_excl
    path, total = compute_critical_path(tbn, available)
    print(json.dumps({'path': path, 'total_seconds': total}))


def cmd_cross_validate(tests, tbn, td):
    sessions = load_all_sessions()
    session_names = set(s.name for s in sessions)
    test_names = set(t.name for t in tests)
    matched = session_names & test_names
    sessions_by_name = {s.name: s for s in sessions}

    results = []
    for name in sorted(matched):
        session = sessions_by_name[name]
        root_deps = set(session.all_deps)
        checked = sorted(root_deps & matched)
        trans = td.get(name, set())
        uncovered = sorted(d for d in checked if d not in trans)
        status = 'ok' if not uncovered else 'mismatch'
        results.append({
            'name': name,
            'status': status,
            'checked_deps': checked,
            'uncovered_deps': uncovered,
        })

    ok_count = sum(1 for r in results if r['status'] == 'ok')
    mismatch_count = sum(1 for r in results if r['status'] == 'mismatch')

    print(json.dumps({
        'results': results,
        'ok_count': ok_count,
        'mismatch_count': mismatch_count,
    }))


def cmd_change_impact(_tests, tbn, td):
    arch = sys.argv[2]
    change_file = sys.argv[3]
    with open(change_file) as f:
        change = json.load(f)

    add_excl = change.get('add_exclusions', [])
    remove_excl = change.get('remove_exclusions', [])

    _, old_excl = _apply_exclusions(tbn, td, arch)
    _, new_excl = _apply_modified_exclusions(tbn, td, arch, add_excl, remove_excl)

    old_runnable = len(tbn) - len(old_excl)
    new_runnable = len(tbn) - len(new_excl)

    newly_excluded = sorted(new_excl - old_excl)
    newly_included = sorted(old_excl - new_excl)

    old_available = set(tbn) - old_excl
    new_available = set(tbn) - new_excl

    _, old_cp = compute_critical_path(tbn, old_available)
    _, new_cp = compute_critical_path(tbn, new_available)

    print(json.dumps({
        'old_runnable_count': old_runnable,
        'new_runnable_count': new_runnable,
        'delta': new_runnable - old_runnable,
        'newly_excluded': newly_excluded,
        'newly_included': newly_included,
        'old_critical_path_seconds': old_cp,
        'new_critical_path_seconds': new_cp,
        'critical_path_delta': new_cp - old_cp,
    }))


def cmd_schedule(_tests, tbn, td):
    arch = sys.argv[2]
    n_cpus = int(sys.argv[3])
    _, all_excl = _apply_exclusions(tbn, td, arch)
    available = set(tbn) - all_excl

    # Build successor map for bottom-level computation
    successors = defaultdict(list)
    for name in available:
        for dep in tbn[name].depends:
            if dep in available:
                successors[dep].append(name)

    # Compute bottom level: longest weighted path to any sink (including self)
    bottom_level = {}

    def _bl(name):
        if name in bottom_level:
            return bottom_level[name]
        t = tbn[name]
        succs = successors.get(name, [])
        if not succs:
            bl = t.cpu_timeout
        else:
            bl = t.cpu_timeout + max(_bl(s) for s in succs)
        bottom_level[name] = bl
        return bl

    for n in available:
        _bl(n)

    # Priority: decreasing bottom level, then alphabetical for tie-breaking
    priority = sorted(available, key=lambda n: (-bottom_level[n], n))

    # List scheduling with greedy CPU assignment
    cpu_available = [0] * n_cpus
    finish_time = {}

    for name in priority:
        t = tbn[name]
        deps_in_avail = [d for d in t.depends if d in available]
        earliest = max((finish_time[d] for d in deps_in_avail), default=0)

        best_cpu = min(range(n_cpus), key=lambda c: (max(cpu_available[c], earliest), c))
        start = max(cpu_available[best_cpu], earliest)
        end = start + t.cpu_timeout

        cpu_available[best_cpu] = end
        finish_time[name] = end

    makespan = max(cpu_available) if cpu_available else 0
    print(json.dumps({'makespan': makespan}))


COMMANDS = {
    'parse-sessions': cmd_parse_sessions,
    'parse-tests': cmd_parse_tests,
    'reconcile': cmd_reconcile,
    'cascade-exclude': cmd_cascade_exclude,
    'critical-path': cmd_critical_path,
    'cross-validate': cmd_cross_validate,
    'change-impact': cmd_change_impact,
    'schedule': cmd_schedule,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit("Usage: pipeline.py <{}> [args]".format('|'.join(sorted(COMMANDS))))
    tests = load_all_tests()
    tbn = {t.name: t for t in tests}
    td = compute_transitive_deps(tbn)
    COMMANDS[sys.argv[1]](tests, tbn, td)


if __name__ == '__main__':
    main()
