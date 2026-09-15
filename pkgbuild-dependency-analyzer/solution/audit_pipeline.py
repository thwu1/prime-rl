#!/usr/bin/env python3
"""PKGBUILD Repository Audit Pipeline.

Orchestrates bash evaluation, sqlite3, graphviz (dot), and jq to analyse
an Arch-Linux-style PKGBUILD ecosystem.
"""

import bisect
import json
import os
import re
import sqlite3
import subprocess
import sys
from itertools import combinations, product
from pathlib import Path

# =====================================================================
# 1. PKGBUILD extraction via bash evaluation
# =====================================================================

_BASH_TEMPLATE = r'''
# Neuter filesystem commands so package_*() functions run without side effects
cd()      { :; }
cmake()   { :; }
make()    { :; }
install() { :; }
cp()      { :; }
mv()      { :; }
rm()      { :; }
rmdir()   { :; }
chmod()   { :; }
patch()   { :; }
go()      { :; }
python()  { :; }
npm()     { :; }
ln()      { :; }
touch()   { :; }
mkdir()   { :; }

source "PKGBUILD_PATH"

# Resolve pkgbase
_pkgbase="${pkgbase:-${pkgname[0]:-$pkgname}}"
_epoch="${epoch:-0}"

echo "@@PKGBASE@@${_pkgbase}"
echo "@@PKGVER@@${pkgver}"
echo "@@PKGREL@@${pkgrel}"
echo "@@EPOCH@@${_epoch}"
echo "@@PKGDESC@@${pkgdesc}"

_sep=$'\x1f'

_out() {
    local tag="$1"; shift
    echo -n "@@${tag}@@"
    local first=1
    for item in "$@"; do
        [ "$first" -eq 0 ] && echo -n "${_sep}"
        echo -n "$item"
        first=0
    done
    echo
}

_out ARCH "${arch[@]}"
_out MAKEDEPENDS "${makedepends[@]}"
_out NAMES "${pkgname[@]}"

for _pkg in "${pkgname[@]}"; do
    echo "@@PKG_START@@${_pkg}"

    _s_desc="$pkgdesc"
    _s_deps=("${depends[@]}")
    _s_provs=("${provides[@]}")
    _s_confs=("${conflicts[@]}")
    _s_opts=("${optdepends[@]}")

    if declare -f "package_${_pkg}" >/dev/null 2>&1; then
        "package_${_pkg}" 2>/dev/null || true
    elif [ "${#pkgname[@]}" -le 1 ] && declare -f package >/dev/null 2>&1; then
        package 2>/dev/null || true
    fi

    echo "@@P_PKGDESC@@${pkgdesc}"
    _out P_DEPENDS "${depends[@]}"
    _out P_PROVIDES "${provides[@]}"
    _out P_CONFLICTS "${conflicts[@]}"
    _out P_OPTDEPENDS "${optdepends[@]}"

    echo "@@PKG_END@@${_pkg}"

    pkgdesc="$_s_desc"
    depends=("${_s_deps[@]}")
    provides=("${_s_provs[@]}")
    conflicts=("${_s_confs[@]}")
    optdepends=("${_s_opts[@]}")
done
'''


def _split_array(raw):
    if not raw.strip():
        return []
    return [x for x in raw.split('\x1f') if x]


def _extract_pkgbuild(path):
    script = _BASH_TEMPLATE.replace('PKGBUILD_PATH', path)
    r = subprocess.run(['bash', '-c', script],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f'bash eval failed for {path}:\n{r.stderr}')

    info = {'packages': {}}
    cur = None
    for line in r.stdout.split('\n'):
        if line.startswith('@@PKGBASE@@'):     info['pkgbase'] = line[11:]
        elif line.startswith('@@PKGVER@@'):     info['pkgver'] = line[10:]
        elif line.startswith('@@PKGREL@@'):     info['pkgrel'] = line[10:]
        elif line.startswith('@@EPOCH@@'):       info['epoch'] = int(line[9:] or '0')
        elif line.startswith('@@PKGDESC@@'):    info['pkgdesc'] = line[11:]
        elif line.startswith('@@ARCH@@'):       info['arch'] = _split_array(line[8:])
        elif line.startswith('@@MAKEDEPENDS@@'):info['makedepends'] = _split_array(line[15:])
        elif line.startswith('@@NAMES@@'):      info['names'] = _split_array(line[9:])
        elif line.startswith('@@PKG_START@@'):
            cur = line[13:]
            info['packages'][cur] = {}
        elif line.startswith('@@P_PKGDESC@@') and cur:
            info['packages'][cur]['pkgdesc'] = line[13:]
        elif line.startswith('@@P_DEPENDS@@') and cur:
            info['packages'][cur]['depends'] = _split_array(line[13:])
        elif line.startswith('@@P_PROVIDES@@') and cur:
            info['packages'][cur]['provides'] = _split_array(line[14:])
        elif line.startswith('@@P_CONFLICTS@@') and cur:
            info['packages'][cur]['conflicts'] = _split_array(line[15:])
        elif line.startswith('@@P_OPTDEPENDS@@') and cur:
            info['packages'][cur]['optdepends'] = _split_array(line[16:])
        elif line.startswith('@@PKG_END@@'):
            cur = None
    return info


def extract_all(ecosystem_dir):
    packages = []
    for subdir in sorted(Path(ecosystem_dir).iterdir()):
        pb = subdir / 'PKGBUILD'
        if not pb.exists():
            continue
        info = _extract_pkgbuild(str(pb))
        pkgbase = info['pkgbase']
        pkgver = info['pkgver']
        pkgrel = info['pkgrel']
        epoch = info['epoch']
        arch = info.get('arch', ['x86_64'])
        makedeps = info.get('makedepends', [])
        fv = f'{epoch}:{pkgver}-{pkgrel}' if epoch > 0 else f'{pkgver}-{pkgrel}'

        for name in info.get('names', [pkgbase]):
            pi = info['packages'].get(name, {})
            packages.append({
                'name': name,
                'pkgbase': pkgbase,
                'pkgver': pkgver,
                'pkgrel': pkgrel,
                'epoch': epoch,
                'full_version': fv,
                'pkgdesc': pi.get('pkgdesc', info.get('pkgdesc', '')),
                'arch': arch,
                'depends': pi.get('depends', []),
                'makedepends': makedeps,
                'provides': pi.get('provides', []),
                'conflicts': pi.get('conflicts', []),
                'optdepends': pi.get('optdepends', []),
            })
    return packages


# =====================================================================
# 2. Dependency helpers
# =====================================================================

def parse_dep(s):
    """'name>=ver' -> (name, op, ver)."""
    for op in ('>=', '<=', '>', '<', '='):
        if op in s:
            i = s.index(op)
            return s[:i], op, s[i + len(op):]
    return s, None, None


def _vercmp(a, b):
    def tok(v):
        t = []
        for p in re.split(r'[.\-+~]', v):
            for s in re.findall(r'[0-9]+|[a-zA-Z]+', p):
                try:
                    t.append((0, int(s)))
                except ValueError:
                    t.append((1, s))
        return t
    ta, tb = tok(a), tok(b)
    for x, y in zip(ta, tb):
        if x < y: return -1
        if x > y: return 1
    return (len(ta) > len(tb)) - (len(ta) < len(tb))


def _ver_ok(avail, op, req):
    c = _vercmp(avail, req)
    return {'>=':(c>=0), '<=':(c<=0), '>':(c>0), '<':(c<0), '=':(c==0)}.get(op, True)


# =====================================================================
# 3. Analysis
# =====================================================================

def find_conflict_pairs(packages):
    prov_map = {}
    for p in packages:
        prov_map.setdefault(p['name'], set()).add(p['name'])
        for pr in p['provides']:
            prov_map.setdefault(parse_dep(pr)[0], set()).add(p['name'])

    pairs = set()
    for p in packages:
        for c in p['conflicts']:
            cn = parse_dep(c)[0]
            for t in prov_map.get(cn, set()):
                if t != p['name']:
                    pairs.add(tuple(sorted([p['name'], t])))
    return sorted(pairs)


def find_version_mismatches(packages):
    prov_map = {}
    for p in packages:
        prov_map.setdefault(p['name'], []).append((p['name'], p['pkgver']))
        for pr in p['provides']:
            pn, _, pv = parse_dep(pr)
            prov_map.setdefault(pn, []).append((p['name'], pv))

    mm, seen = [], set()
    for p in packages:
        for dep in list(p['depends']) + list(p['makedepends']):
            dn, dop, dv = parse_dep(dep)
            if dn not in prov_map or dop is None:
                continue
            satisfied = False
            best = None
            for _, pv in prov_map[dn]:
                if pv is None:
                    continue
                if best is None or _vercmp(pv, best) > 0:
                    best = pv
                if _ver_ok(pv, dop, dv):
                    satisfied = True
                    break
            if not satisfied and best is not None:
                key = (p['name'], dep)
                if key not in seen:
                    seen.add(key)
                    mm.append({'type': 'VERSION_MISMATCH',
                               'package': p['name'],
                               'dependency': dep,
                               'available_version': best})
    return mm


def compute_build_order(packages, mismatches):
    bad_pkgs = {m['package'] for m in mismatches}
    bad_bases = {p['pkgbase'] for p in packages if p['name'] in bad_pkgs}
    bases = {p['pkgbase'] for p in packages if p['pkgbase'] not in bad_bases}

    prov_to_base = {}
    for p in packages:
        prov_to_base.setdefault(p['name'], p['pkgbase'])
        for pr in p['provides']:
            prov_to_base.setdefault(parse_dep(pr)[0], p['pkgbase'])

    deps = {b: set() for b in bases}
    for p in packages:
        if p['pkgbase'] not in bases:
            continue
        for d in list(p['depends']) + list(p['makedepends']):
            dn = parse_dep(d)[0]
            db = prov_to_base.get(dn)
            if db and db in bases and db != p['pkgbase']:
                deps[p['pkgbase']].add(db)

    indeg = {b: len(deps[b]) for b in bases}
    q = sorted(b for b in bases if indeg[b] == 0)
    order = []
    while q:
        n = q.pop(0)
        order.append(n)
        for b in sorted(bases):
            if n in deps[b]:
                indeg[b] -= 1
                if indeg[b] == 0:
                    bisect.insort(q, b)
    return order


def compute_installable_groups(packages, conflict_pairs, mismatches):
    bad_pkgs = {m['package'] for m in mismatches}
    bad_bases = {p['pkgbase'] for p in packages if p['name'] in bad_pkgs}
    eligible = sorted(p['name'] for p in packages if p['pkgbase'] not in bad_bases)
    eset = set(eligible)

    adj = {n: set() for n in eligible}
    for a, b in conflict_pairs:
        if a in eset and b in eset:
            adj[a].add(b)
            adj[b].add(a)

    visited = set()
    components = []
    for n in eligible:
        if n in visited or not adj[n]:
            continue
        comp = set()
        stk = [n]
        while stk:
            nd = stk.pop()
            if nd in visited:
                continue
            visited.add(nd)
            comp.add(nd)
            for nb in adj[nd]:
                if nb not in visited:
                    stk.append(nb)
        components.append(sorted(comp))

    base = sorted(eset - visited)

    def _mis(comp):
        nodes = list(comp)
        n = len(nodes)
        results = []
        for sz in range(n, 0, -1):
            for sub in combinations(nodes, sz):
                ss = set(sub)
                if any(adj[nd] & ss for nd in sub):
                    continue
                if all(any(nd2 in adj[nd] for nd2 in sub) for nd in comp if nd not in ss):
                    results.append(sorted(sub))
            if results:
                break
        return results or [sorted(comp)]

    opts = [_mis(c) for c in components]
    if not opts:
        return [base]

    groups = []
    for combo in product(*opts):
        g = list(base)
        for sel in combo:
            g.extend(sel)
        groups.append(sorted(g))
    return sorted(groups)


# =====================================================================
# 4. SQLite database
# =====================================================================

def create_database(packages, db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript('''
        CREATE TABLE packages (
            name TEXT PRIMARY KEY, pkgbase TEXT, pkgver TEXT,
            pkgrel TEXT, epoch INTEGER DEFAULT 0,
            full_version TEXT, pkgdesc TEXT);
        CREATE TABLE package_arch (
            package_name TEXT REFERENCES packages(name), arch TEXT);
        CREATE TABLE depends (
            package_name TEXT REFERENCES packages(name),
            dep_name TEXT, dep_constraint TEXT, dep_type TEXT);
        CREATE TABLE provides (
            package_name TEXT REFERENCES packages(name),
            provided_name TEXT, provided_version TEXT);
        CREATE TABLE conflicts (
            package_name TEXT REFERENCES packages(name),
            conflict_name TEXT);
    ''')
    for p in packages:
        conn.execute('INSERT INTO packages VALUES (?,?,?,?,?,?,?)',
                     (p['name'], p['pkgbase'], p['pkgver'], p['pkgrel'],
                      p['epoch'], p['full_version'], p['pkgdesc']))
        for a in p['arch']:
            conn.execute('INSERT INTO package_arch VALUES (?,?)', (p['name'], a))
        for d in p['depends']:
            dn = parse_dep(d)[0]
            conn.execute('INSERT INTO depends VALUES (?,?,?,?)',
                         (p['name'], dn, d, 'depends'))
        for d in p['makedepends']:
            dn = parse_dep(d)[0]
            conn.execute('INSERT INTO depends VALUES (?,?,?,?)',
                         (p['name'], dn, d, 'makedepends'))
        for o in p.get('optdepends', []):
            dp = o.split(':')[0].strip()
            dn = parse_dep(dp)[0]
            conn.execute('INSERT INTO depends VALUES (?,?,?,?)',
                         (p['name'], dn, dp, 'optdepends'))
        for pr in p['provides']:
            if '=' in pr:
                pn, pv = pr.split('=', 1)
            else:
                pn, pv = pr, None
            conn.execute('INSERT INTO provides VALUES (?,?,?)',
                         (p['name'], pn, pv))
        for c in p['conflicts']:
            conn.execute('INSERT INTO conflicts VALUES (?,?)', (p['name'], c))
    conn.commit()
    conn.close()


# =====================================================================
# 5. DOT / SVG graph
# =====================================================================

def generate_dot(packages, issues, dot_path):
    pkg_names = {p['name'] for p in packages}
    prov2pkg = {}
    for p in packages:
        prov2pkg[p['name']] = p['name']
        for pr in p['provides']:
            prov2pkg.setdefault(parse_dep(pr)[0], p['name'])

    by_base = {}
    for p in packages:
        by_base.setdefault(p['pkgbase'], []).append(p)

    unsat = {i['package'] for i in issues if i['type'] == 'VERSION_MISMATCH'}
    L = ['digraph dependencies {', '    rankdir=LR;', '    node [fontsize=10];', '']

    for base in sorted(by_base):
        pkgs = by_base[base]
        if len(pkgs) > 1:
            L.append(f'    subgraph cluster_{base} {{')
            L.append(f'        label="{base}"; style=dashed;')
            for p in pkgs:
                sh = 'doubleoctagon' if p['name'] in unsat else 'box'
                lb = f"{p['name']}\\n{p['full_version']}"
                L.append(f'        "{p["name"]}" [label="{lb}", shape={sh}];')
            L.append('    }')
        else:
            p = pkgs[0]
            sh = 'doubleoctagon' if p['name'] in unsat else 'box'
            lb = f"{p['name']}\\n{p['full_version']}"
            L.append(f'    "{p["name"]}" [label="{lb}", shape={sh}];')
    L.append('')

    seen = set()
    for p in packages:
        for d in p['depends']:
            dn = parse_dep(d)[0]
            t = dn if dn in pkg_names else prov2pkg.get(dn)
            if t and (p['name'], t, 'solid') not in seen:
                seen.add((p['name'], t, 'solid'))
                L.append(f'    "{p["name"]}" -> "{t}" [style=solid];')
        for d in p['makedepends']:
            dn = parse_dep(d)[0]
            t = dn if dn in pkg_names else prov2pkg.get(dn)
            if t and (p['name'], t, 'dashed') not in seen:
                seen.add((p['name'], t, 'dashed'))
                L.append(f'    "{p["name"]}" -> "{t}" [style=dashed];')

    for a, b in find_conflict_pairs(packages):
        L.append(f'    "{a}" -> "{b}" [dir=both, color=red];')

    L.append('}')
    with open(dot_path, 'w') as f:
        f.write('\n'.join(L))


# =====================================================================
# 6. Main
# =====================================================================

def main():
    eco = sys.argv[1] if len(sys.argv) > 1 else '/app/ecosystem'

    packages = extract_all(eco)
    cpairs = find_conflict_pairs(packages)
    mm = find_version_mismatches(packages)

    issues = [{'type': 'CONFLICT', 'packages': list(p),
               'detail': f'{p[0]} and {p[1]} conflict'} for p in cpairs]
    issues.extend(mm)

    bo = compute_build_order(packages, mm)
    grps = compute_installable_groups(packages, cpairs, mm)

    create_database(packages, '/app/repo.db')

    generate_dot(packages, issues, '/app/depgraph.dot')
    subprocess.run(['dot', '-Tsvg', '-o', '/app/depgraph.svg', '/app/depgraph.dot'],
                   check=True)

    report = {
        'package_count': len(packages),
        'pkgbase_count': len({p['pkgbase'] for p in packages}),
        'packages': {p['name']: {
            'pkgbase': p['pkgbase'], 'pkgver': p['pkgver'],
            'pkgrel': p['pkgrel'], 'epoch': p['epoch'],
            'full_version': p['full_version'], 'pkgdesc': p['pkgdesc'],
            'arch': p['arch'], 'depends': p['depends'],
            'makedepends': p['makedepends'], 'provides': p['provides'],
            'conflicts': p['conflicts'], 'optdepends': p.get('optdepends', []),
        } for p in packages},
        'build_order': bo,
        'issues': issues,
        'installable_groups': grps,
    }

    raw = json.dumps(report)
    jq = subprocess.run(['jq', '.'], input=raw,
                        capture_output=True, text=True, check=True)
    with open('/app/audit.json', 'w') as f:
        f.write(jq.stdout)

    print(f'Done: {len(packages)} pkgs, {len(bo)} in build order, '
          f'{len(issues)} issues, {len(grps)} groups')


if __name__ == '__main__':
    main()
