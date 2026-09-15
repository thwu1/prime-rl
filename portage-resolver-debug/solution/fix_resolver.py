#!/usr/bin/env python3
"""
Fix all bugs and implement missing functionality in the Portage world
upgrade planner, strategy evaluator, and dependency graph generator.


Bug 1 (version.py):   Absent letter suffix uses float('inf') -- should be 0
                       so that absent letter sorts BEFORE all letters per PMS.

Bug 2 (depstring.py):  The 'negate' state variable leaks across sibling USE
                        conditionals.  After processing !flag?, subsequent
                        flag? conditions at the same level are wrongly negated.

Bug 3 (solver.py):     Solution.remove() does not clean _slot_map, so
                        backtracking fails with a false SlotConflict when
                        trying an alternative version in the same slot.

Bug 4 (solver.py):     _collect_slot_op_rdeps() only finds direct := deps;
                        it must recurse to capture transitive rebuilds.

Bug 5 (config.py):     _parse_make_conf treats -flag as adding the flag
                        (strips the - prefix) instead of excluding it.

Bug 6 (database.py):   _sanitize_dep() regex strips = from slot operators
                        (:0= becomes :0), breaking := rebuild detection.

Stub 7 (planner.py):   compute_newuse_rebuilds() returns [] -- needs
                        implementation.

Stub 8 (planner.py):   compute_merge_order() returns sorted() -- needs
                        topological sort implementation.

Stub 9 (evaluator.py): evaluate() returns empty data -- needs full
                        strategy comparison implementation.

Stub 10 (graph.py):    to_dot() returns minimal DOT -- needs full
                        graph generation implementation.
"""

import os
import shutil
import sys


def ensure_source_files():
    """Ensure source files exist at /app/ (restore from backup if needed)."""
    if not os.path.exists('/app/resolver/version.py'):
        backup = '/opt/task_src'
        if os.path.exists(backup):
            os.makedirs('/app/resolver', exist_ok=True)
            for item in os.listdir(backup):
                src = os.path.join(backup, item)
                dst = os.path.join('/app', item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
        else:
            print("ERROR: Source files not found", file=sys.stderr)
            sys.exit(1)


def fix_version():
    """Bug 1: letter_val for absent letter must be 0, not float('inf')."""
    path = '/app/resolver/version.py'
    with open(path) as f:
        src = f.read()

    old = "float('inf')"
    if old not in src:
        print("WARN: version.py -- target string not found", file=sys.stderr)
        return

    src = src.replace(old, '0')
    with open(path, 'w') as f:
        f.write(src)
    print("[fixed] version.py: absent-letter comparison value -> 0")


def fix_depstring():
    """Bug 2: eliminate the stateful 'negate' variable leak."""
    path = '/app/resolver/depstring.py'
    with open(path) as f:
        src = f.read()

    old = (
        "                if is_negated:\n"
        "                    negate = True\n"
        "\n"
        "                should_include = flag_active\n"
        "                if negate:\n"
        "                    should_include = not should_include"
    )
    new = (
        "                should_include = (not flag_active) if is_negated else flag_active"
    )
    if old not in src:
        print("WARN: depstring.py -- target block not found", file=sys.stderr)
        return

    src = src.replace(old, new)
    with open(path, 'w') as f:
        f.write(src)
    print("[fixed] depstring.py: USE-conditional negate state leak removed")


def fix_solver():
    """Bug 3: clean _slot_map in remove().  Bug 4: recurse in rebuilds."""
    path = '/app/resolver/solver.py'
    with open(path) as f:
        src = f.read()

    # --- Bug 3: remove() must also clean the _slot_map ----------------
    old_remove = (
        "        # NOTE: _slot_map is intentionally not updated here to preserve\n"
        "        # slot allocation history for conflict diagnostics."
    )
    new_remove = (
        "        if cp in self._slot_map:\n"
        "            for s, (v, _) in list(self._slot_map[cp].items()):\n"
        "                if v == version:\n"
        "                    del self._slot_map[cp][s]"
    )
    if old_remove not in src:
        print("WARN: solver.py -- remove() target not found", file=sys.stderr)
    else:
        src = src.replace(old_remove, new_remove)
        print("[fixed] solver.py: Solution.remove() now cleans _slot_map")

    # --- Bug 4: _collect_slot_op_rdeps must recurse -------------------
    old_rebuild = (
        "                if da.cp == changed_cp and da.slot_operator == '=':\n"
        "                    rebuilds.add(cp)\n"
        "                    break"
    )
    new_rebuild = (
        "                if da.cp == changed_cp and da.slot_operator == '=':\n"
        "                    rebuilds.add(cp)\n"
        "                    self._collect_slot_op_rdeps(\n"
        "                        cp, slot, solution, rebuilds)\n"
        "                    break"
    )
    if old_rebuild not in src:
        print("WARN: solver.py -- rebuild target not found", file=sys.stderr)
    else:
        src = src.replace(old_rebuild, new_rebuild)
        print("[fixed] solver.py: transitive := rebuild propagation added")

    with open(path, 'w') as f:
        f.write(src)


def fix_config():
    """Bug 5: make.conf parsing must handle -flag as exclusion."""
    path = '/app/resolver/config.py'
    with open(path) as f:
        src = f.read()

    old = (
        "                    for tok in m.group(1).split():\n"
        "                        # Normalize flag name \u2014 strip any prefix sigils\n"
        "                        self.global_use.add(tok.lstrip('-'))"
    )
    new = (
        "                    for tok in m.group(1).split():\n"
        "                        if tok.startswith('-'):\n"
        "                            self.global_use.discard(tok[1:])\n"
        "                        else:\n"
        "                            self.global_use.add(tok)"
    )
    if old not in src:
        print("WARN: config.py -- target block not found", file=sys.stderr)
        return

    src = src.replace(old, new)
    with open(path, 'w') as f:
        f.write(src)
    print("[fixed] config.py: -flag handling corrected in make.conf parsing")


def fix_database():
    """Bug 6: _sanitize_dep strips = from slot operators."""
    path = '/app/resolver/database.py'
    with open(path) as f:
        src = f.read()

    old = "        dep_str = re.sub(r'(?<=\\S)=(?=\\s|$)', '', dep_str)"
    new = "        # Slot operator = signs are PMS syntax, not artifacts"
    if old not in src:
        print("WARN: database.py -- sanitize target not found", file=sys.stderr)
        return

    src = src.replace(old, new)
    with open(path, 'w') as f:
        f.write(src)
    print("[fixed] database.py: _sanitize_dep no longer strips slot operator =")


def implement_newuse_rebuilds():
    """Stub 7: implement compute_newuse_rebuilds in planner.py."""
    path = '/app/resolver/planner.py'
    with open(path) as f:
        src = f.read()

    old = (
        "        # TODO: implement newuse rebuild detection\n"
        "        return []"
    )
    new = (
        "        rebuilds = []\n"
        "        for cp, inst in self.installed.items():\n"
        "            if cp in upgraded_cps:\n"
        "                continue\n"
        "            inst_use = set(inst.get('installed_use', []))\n"
        "            new_use = self.config.get_effective_use(cp)\n"
        "            if inst_use == new_use:\n"
        "                continue\n"
        "            ver_data = self.db.get_version(cp, inst['version'])\n"
        "            if not ver_data:\n"
        "                continue\n"
        "            dep_str = ver_data.get('deps', '')\n"
        "            if not dep_str:\n"
        "                continue\n"
        "            old_deps = {a.cp for a in evaluate(dep_str, inst_use)}\n"
        "            new_deps = {a.cp for a in evaluate(dep_str, new_use)}\n"
        "            if old_deps != new_deps:\n"
        "                rebuilds.append(cp)\n"
        "        return rebuilds"
    )
    if old not in src:
        print("WARN: planner.py -- newuse TODO not found", file=sys.stderr)
        return

    src = src.replace(old, new)
    with open(path, 'w') as f:
        f.write(src)
    print("[impl] planner.py: compute_newuse_rebuilds implemented")


def implement_merge_order():
    """Stub 8: implement compute_merge_order with topological sort."""
    path = '/app/resolver/planner.py'
    with open(path) as f:
        src = f.read()

    old = (
        "        # TODO: implement topological sort\n"
        "        return sorted(all_cps)"
    )
    new = (
        "        # Build dependency graph among changed packages\n"
        "        graph = {cp: set() for cp in all_cps}\n"
        "        for cp in all_cps:\n"
        "            inst = self.installed.get(cp, {})\n"
        "            inst_ver = inst.get('version', '')\n"
        "            avail = self.db.get_versions(cp)\n"
        "            target_ver = inst_ver\n"
        "            for v in avail:\n"
        "                if avail[v].get('slot', '0') == inst.get('slot', '0'):\n"
        "                    if Version(v) > Version(inst_ver):\n"
        "                        if target_ver == inst_ver or Version(v) > Version(target_ver):\n"
        "                            target_ver = v\n"
        "            ver_data = self.db.get_version(cp, target_ver) or {}\n"
        "            dep_str = ver_data.get('deps', '')\n"
        "            if dep_str:\n"
        "                use_flags = self.config.get_effective_use(cp)\n"
        "                for da in evaluate(dep_str, use_flags):\n"
        "                    if da.cp in all_cps:\n"
        "                        graph[cp].add(da.cp)\n"
        "        # Kahn's algorithm for topological sort\n"
        "        in_deg = {cp: len(deps) for cp, deps in graph.items()}\n"
        "        rev = {cp: set() for cp in all_cps}\n"
        "        for cp, deps in graph.items():\n"
        "            for d in deps:\n"
        "                rev[d].add(cp)\n"
        "        queue = sorted(cp for cp in all_cps if in_deg[cp] == 0)\n"
        "        result = []\n"
        "        while queue:\n"
        "            node = queue.pop(0)\n"
        "            result.append(node)\n"
        "            for dep in sorted(rev[node]):\n"
        "                in_deg[dep] -= 1\n"
        "                if in_deg[dep] == 0:\n"
        "                    queue.append(dep)\n"
        "                    queue.sort()\n"
        "        result.extend(sorted(all_cps - set(result)))\n"
        "        return result"
    )
    if old not in src:
        print("WARN: planner.py -- merge order TODO not found", file=sys.stderr)
        return

    src = src.replace(old, new)
    with open(path, 'w') as f:
        f.write(src)
    print("[impl] planner.py: compute_merge_order implemented")


def implement_evaluator():
    """Stub 9: implement the strategy evaluator."""
    path = '/app/resolver/evaluator.py'
    content = '''\
"""
Resolution strategy evaluator for Portage world upgrades.

Compares two upgrade strategies:
  - prefer_newest: always choose the highest available version per slot
  - minimize_rebuilds: prefer versions that preserve current subslots
    when a same-subslot newer version exists, reducing := rebuild cascades
"""

from .version import Version
from .solver import Resolver, Solution
from .depstring import evaluate


class StrategyEvaluator:
    """Compare resolution strategies for a world upgrade."""

    def __init__(self, db, config, installed):
        self.db = db
        self.config = config
        self.installed = installed

    def evaluate(self):
        """Compare prefer_newest vs minimize_rebuilds strategies."""
        pn = self._compute_strategy('prefer_newest')
        mr = self._compute_strategy('minimize_rebuilds')

        pn_merges = pn['total_merges']
        mr_merges = mr['total_merges']

        if mr_merges < pn_merges:
            recommended = 'minimize_rebuilds'
            rationale = (f'Reduces total merges from {pn_merges} to '
                         f'{mr_merges} by preserving subslots where possible')
        elif pn_merges < mr_merges:
            recommended = 'prefer_newest'
            rationale = (f'Fewer total merges ({pn_merges}) while getting '
                         f'newest versions')
        else:
            recommended = 'prefer_newest'
            rationale = (f'Same total merges ({pn_merges}); prefer newest '
                         f'versions for latest features')

        return {
            'strategies': {
                'prefer_newest': pn,
                'minimize_rebuilds': mr,
            },
            'recommended': recommended,
            'rationale': rationale,
        }

    def _compute_strategy(self, strategy):
        """Compute metrics for a single strategy."""
        upgrades = self._compute_upgrades(strategy)
        upgraded_cps = {u['cp'] for u in upgrades}

        newuse_count = self._compute_newuse_count(upgraded_cps)
        slot_rebuild_count = self._compute_slot_rebuild_count(upgrades)

        total = len(upgrades) + newuse_count + slot_rebuild_count

        return {
            'upgrades': sorted(upgrades, key=lambda u: u['cp']),
            'total_upgrades': len(upgrades),
            'slot_rebuilds': slot_rebuild_count,
            'newuse_rebuilds': newuse_count,
            'total_merges': total,
        }

    def _compute_upgrades(self, strategy):
        """Compute version upgrades under a given strategy."""
        upgrades = []
        for cp, inst in self.installed.items():
            available = self.db.get_versions(cp)
            if not available:
                continue
            inst_ver = Version(inst['version'])
            inst_slot = inst.get('slot', '0')
            inst_subslot = inst.get('subslot', '0')

            candidates = []
            for v_str, v_data in available.items():
                if v_data.get('slot', '0') != inst_slot:
                    continue
                v = Version(v_str)
                if v > inst_ver:
                    candidates.append((v_str, v_data))

            if not candidates:
                continue

            if strategy == 'minimize_rebuilds':
                same_sub = [(v, d) for v, d in candidates
                            if d.get('subslot', '0') == inst_subslot]
                if same_sub:
                    best = max(same_sub, key=lambda x: Version(x[0]))
                else:
                    best = max(candidates, key=lambda x: Version(x[0]))
            else:
                best = max(candidates, key=lambda x: Version(x[0]))

            upgrades.append({
                'cp': cp,
                'old_version': inst['version'],
                'new_version': best[0],
            })

        return upgrades

    def _compute_newuse_count(self, upgraded_cps):
        """Count packages needing USE-change rebuild."""
        count = 0
        for cp, inst in self.installed.items():
            if cp in upgraded_cps:
                continue
            inst_use = set(inst.get('installed_use', []))
            new_use = self.config.get_effective_use(cp)
            if inst_use == new_use:
                continue
            ver_data = self.db.get_version(cp, inst['version'])
            if not ver_data:
                continue
            dep_str = ver_data.get('deps', '')
            if not dep_str:
                continue
            old_deps = {a.cp for a in evaluate(dep_str, inst_use)}
            new_deps = {a.cp for a in evaluate(dep_str, new_use)}
            if old_deps != new_deps:
                count += 1
        return count

    def _compute_slot_rebuild_count(self, upgrades):
        """Count packages needing := subslot rebuild for given upgrades."""
        old_sol = Solution()
        new_sol = Solution()
        upgraded_cps = {u['cp'] for u in upgrades}

        for cp, inst in self.installed.items():
            old_sol.add(cp, inst['version'], inst.get('slot', '0'),
                        inst.get('subslot', '0'))

        for cp, inst in self.installed.items():
            if cp in upgraded_cps:
                u = next(u for u in upgrades if u['cp'] == cp)
                v_data = self.db.get_version(cp, u['new_version'])
                new_sol.add(cp, u['new_version'],
                            v_data.get('slot', '0'),
                            v_data.get('subslot', '0'))
            else:
                new_sol.add(cp, inst['version'],
                            inst.get('slot', '0'),
                            inst.get('subslot', '0'))

        use_flags = self.config.get_effective_use('')
        resolver = Resolver(self.db, use_flags)
        all_rebuilds = resolver.compute_rebuilds(old_sol, new_sol)

        return len([cp for cp in all_rebuilds if cp not in upgraded_cps])
'''
    with open(path, 'w') as f:
        f.write(content)
    print("[impl] evaluator.py: strategy evaluation implemented")


def implement_graph():
    """Stub 10: implement the DOT graph generator."""
    path = '/app/resolver/graph.py'
    content = '''\
"""
Dependency graph generator in Graphviz DOT format.
"""


class DependencyGraph:
    """Build and export a dependency graph in DOT format."""

    def __init__(self):
        self._nodes = {}
        self._edges = []

    def add_node(self, cp, old_version=None, new_version=None,
                 change_type='upgrade'):
        self._nodes[cp] = {
            'old_version': old_version,
            'new_version': new_version,
            'change_type': change_type,
        }

    def add_edge(self, from_cp, to_cp, label=''):
        self._edges.append((from_cp, to_cp, label))

    def to_dot(self):
        """Render the graph as a DOT format string."""
        lines = ['digraph dependencies {']
        lines.append('    rankdir=BT;')
        lines.append('    node [shape=box, style=filled];')

        colors = {
            'upgrade': '"#b3e2cd"',
            'newuse': '"#fdcdac"',
            'slot_rebuild': '"#cbd5e8"',
        }

        for cp, info in sorted(self._nodes.items()):
            ct = info.get('change_type', 'upgrade')
            color = colors.get(ct, '"#ffffff"')
            old_v = info.get('old_version', '')
            new_v = info.get('new_version', '')

            if new_v:
                label = f'{cp}\\\\n{old_v} -> {new_v}'
            else:
                label = f'{cp}\\\\n{old_v} ({ct})'

            lines.append(
                f'    "{cp}" [label="{label}", fillcolor={color}];')

        for from_cp, to_cp, label in sorted(self._edges):
            if label:
                lines.append(
                    f'    "{from_cp}" -> "{to_cp}" [label="{label}"];')
            else:
                lines.append(f'    "{from_cp}" -> "{to_cp}";')

        lines.append('}')
        return '\\n'.join(lines) + '\\n'

    def write_dot(self, path):
        with open(path, 'w') as f:
            f.write(self.to_dot())
'''
    with open(path, 'w') as f:
        f.write(content)
    print("[impl] graph.py: DOT graph generation implemented")


if __name__ == '__main__':
    ensure_source_files()
    fix_version()
    fix_depstring()
    fix_solver()
    fix_config()
    fix_database()
    implement_newuse_rebuilds()
    implement_merge_order()
    implement_evaluator()
    implement_graph()
    print("\nAll fixes applied and missing functionality implemented.")
