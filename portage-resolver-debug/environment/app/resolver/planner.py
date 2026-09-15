"""
World upgrade planner for Gentoo-style package systems.

Computes an upgrade plan consisting of:
  - Version upgrades (newer versions available in same slot)
  - Newuse rebuilds (USE flag changes alter dependency evaluation)
  - Slot-operator rebuilds (transitive := subslot change propagation)
  - Merge order (dependency-respecting installation sequence)

Also produces:
  - Strategy comparison (prefer_newest vs minimize_rebuilds)
  - Dependency graph in Graphviz DOT format
"""

import json
import os

from .config import PortageConfig
from .database import PackageDB
from .depstring import evaluate
from .solver import Resolver, Solution
from .version import Version


class WorldUpgradePlanner:
    """Compute a world upgrade plan."""

    def __init__(self, db_path, portage_dir):
        self.db = PackageDB(db_path)
        self.config = PortageConfig(portage_dir)
        self.installed = self.db.all_installed()

    def compute_version_upgrades(self):
        """Find installed packages with newer versions available in the same slot.

        Always chooses the newest available version (prefer-newest strategy).
        Returns list of dicts with keys: cp, old_version, new_version
        """
        upgrades = []
        for cp, inst in self.installed.items():
            available = self.db.get_versions(cp)
            if not available:
                continue
            inst_ver = Version(inst['version'])
            inst_slot = inst['slot']
            best = None
            for v_str, v_data in available.items():
                if v_data.get('slot', '0') != inst_slot:
                    continue
                v = Version(v_str)
                if v > inst_ver:
                    if best is None or v > Version(best):
                        best = v_str
            if best:
                upgrades.append({
                    'cp': cp,
                    'old_version': inst['version'],
                    'new_version': best
                })
        return upgrades

    def compute_newuse_rebuilds(self, upgraded_cps):
        """Identify packages needing rebuild because USE flag changes alter their deps.

        A package qualifies when it is NOT already being upgraded AND its
        effective USE flags (from current Portage config) differ from its
        installed USE flags AND this difference changes the set of
        dependencies produced by evaluating its dependency string.

        Args:
            upgraded_cps: packages already being version-upgraded (exclude these)

        Returns:
            List of cp strings
        """
        # TODO: implement newuse rebuild detection
        return []

    def compute_slot_rebuilds(self, upgraded_cps, newuse_cps):
        """Find packages needing rebuild from slot-operator subslot changes.

        Excludes packages already in upgraded_cps or newuse_cps.
        """
        already = upgraded_cps | newuse_cps
        old_sol = Solution()
        new_sol = Solution()

        for cp, inst in self.installed.items():
            old_sol.add(cp, inst['version'], inst['slot'], inst['subslot'])

        for cp, inst in self.installed.items():
            if cp in upgraded_cps:
                avail = self.db.get_versions(cp)
                best = None
                for v_str, v_data in avail.items():
                    if v_data.get('slot', '0') != inst['slot']:
                        continue
                    if Version(v_str) > Version(inst['version']):
                        if best is None or Version(v_str) > Version(best):
                            best = v_str
                if best:
                    vd = avail[best]
                    new_sol.add(cp, best, vd.get('slot', '0'),
                                vd.get('subslot', '0'))
                    continue
            new_sol.add(cp, inst['version'], inst['slot'], inst['subslot'])

        use_flags = self.config.get_effective_use('')
        resolver = Resolver(self.db, use_flags)
        all_rebuilds = resolver.compute_rebuilds(old_sol, new_sol)
        return [cp for cp in all_rebuilds if cp not in already]

    def compute_merge_order(self, all_cps):
        """Produce a dependency-first installation order for all affected packages.

        Must respect dependency constraints: if package A depends on
        package B and both are in all_cps, B must appear before A.
        Use the target version's dependency string for upgraded packages
        and the current version's for rebuilds.

        Args:
            all_cps: set of all cp strings being changed

        Returns:
            List of cp strings in valid topological order
        """
        # TODO: implement topological sort
        return sorted(all_cps)

    def _populate_graph(self, graph, plan):
        """Populate a DependencyGraph from the upgrade plan."""
        upgraded_map = {u['cp']: u for u in plan['upgrades']}
        all_cps = set(plan['merge_order'])

        for cp in plan['merge_order']:
            if cp in upgraded_map:
                u = upgraded_map[cp]
                graph.add_node(cp, old_version=u['old_version'],
                               new_version=u['new_version'],
                               change_type='upgrade')
            elif cp in plan['newuse_rebuilds']:
                inst = self.installed.get(cp, {})
                graph.add_node(cp, old_version=inst.get('version', ''),
                               change_type='newuse')
            else:
                inst = self.installed.get(cp, {})
                graph.add_node(cp, old_version=inst.get('version', ''),
                               change_type='slot_rebuild')

        for cp in all_cps:
            inst = self.installed.get(cp, {})
            target_ver = inst.get('version', '')
            if cp in upgraded_map:
                target_ver = upgraded_map[cp]['new_version']
            ver_data = self.db.get_version(cp, target_ver)
            if not ver_data:
                continue
            dep_str = ver_data.get('deps', '')
            if not dep_str:
                continue
            use_flags = self.config.get_effective_use(cp)
            for da in evaluate(dep_str, use_flags):
                if da.cp in all_cps:
                    label = ':=' if da.slot_operator == '=' else ''
                    graph.add_edge(cp, da.cp, label=label)

    def generate_plan(self, output_path):
        """Generate and write the full upgrade plan and analyses."""
        upgrades = self.compute_version_upgrades()
        upgraded_cps = {u['cp'] for u in upgrades}

        newuse = self.compute_newuse_rebuilds(upgraded_cps)
        newuse_cps = set(newuse)

        slot_rebuilds = self.compute_slot_rebuilds(upgraded_cps, newuse_cps)

        all_cps = upgraded_cps | newuse_cps | set(slot_rebuilds)
        merge_order = self.compute_merge_order(all_cps)

        plan = {
            'upgrades': sorted(upgrades, key=lambda u: u['cp']),
            'newuse_rebuilds': sorted(newuse),
            'slot_rebuilds': sorted(slot_rebuilds),
            'merge_order': merge_order
        }

        with open(output_path, 'w') as f:
            json.dump(plan, f, indent=2)

        # Strategy comparison
        from .evaluator import StrategyEvaluator
        evaluator = StrategyEvaluator(self.db, self.config, self.installed)
        comparison = evaluator.evaluate()

        base_dir = os.path.dirname(output_path)
        comp_path = os.path.join(base_dir, 'strategy_comparison.json')
        with open(comp_path, 'w') as f:
            json.dump(comparison, f, indent=2)

        # Dependency graph
        from .graph import DependencyGraph
        graph = DependencyGraph()
        self._populate_graph(graph, plan)
        graph_path = os.path.join(base_dir, 'dependency_graph.dot')
        graph.write_dot(graph_path)

        return plan
