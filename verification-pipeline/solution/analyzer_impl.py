#!/usr/bin/env python3

"""seL4 L4V Verification Pipeline Analyzer — reference solution."""

import sys
import json
import os
import glob as glob_mod
from xml.etree import ElementTree
from collections import defaultdict

SPECS_DIR = '/app/specs'
EXCLUSIONS_FILE = '/app/config/exclusions.json'


# ---------------------------------------------------------------------------
# Environment & parsing
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
# Graph algorithms
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


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_count(tests, _tbn, _td):
    print(json.dumps({"total": len(tests)}))


def cmd_deps(_tests, tbn, td):
    name = sys.argv[2]
    if name not in tbn:
        sys.exit(f"Unknown test: {name}")
    print(json.dumps({
        "direct": sorted(tbn[name].depends),
        "transitive": sorted(td[name]),
    }))


def cmd_critical_path(_tests, tbn, td):
    arch = sys.argv[2]
    _, all_excl = _apply_exclusions(tbn, td, arch)
    available = set(tbn) - all_excl
    path, total = compute_critical_path(tbn, available)
    print(json.dumps({"path": path, "total_seconds": total}))


def cmd_cascade_exclude(_tests, tbn, td):
    arch = sys.argv[2]
    direct, all_excl = _apply_exclusions(tbn, td, arch)
    cascade = sorted(all_excl - set(direct))
    print(json.dumps({
        "directly_excluded": sorted(direct),
        "cascade_excluded": cascade,
        "total_excluded_count": len(all_excl),
    }))


def cmd_arch_tests(_tests, tbn, td):
    arch = sys.argv[2]
    _, all_excl = _apply_exclusions(tbn, td, arch)
    print(json.dumps({"runnable": len(tbn) - len(all_excl)}))


def cmd_total_cpu(_tests, tbn, td):
    arch = sys.argv[2]
    _, all_excl = _apply_exclusions(tbn, td, arch)
    available = set(tbn) - all_excl
    total = sum(tbn[n].cpu_timeout for n in available)
    print(json.dumps({"total_seconds": total}))


COMMANDS = {
    'count': cmd_count,
    'deps': cmd_deps,
    'critical-path': cmd_critical_path,
    'cascade-exclude': cmd_cascade_exclude,
    'arch-tests': cmd_arch_tests,
    'total-cpu': cmd_total_cpu,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"Usage: analyzer.py <{'|'.join(COMMANDS)}> [args]")
    tests = load_all_tests()
    tbn = {t.name: t for t in tests}
    td = compute_transitive_deps(tbn)
    COMMANDS[sys.argv[1]](tests, tbn, td)


if __name__ == '__main__':
    main()
