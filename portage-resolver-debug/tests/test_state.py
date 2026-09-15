"""
Tests for the Portage world upgrade planner, strategy evaluator, and
dependency graph generator.

Verifies the full stack: version comparison, USE-conditional evaluation,
config parsing, resolver backtracking, slot-operator rebuild propagation,
newuse rebuild detection, topological merge ordering, strategy comparison,
and DOT graph generation.

"""

import os
import sys
sys.path.insert(0, '/app')

import json
import subprocess
import pytest

from resolver.version import Version
from resolver.depstring import evaluate
from resolver.atom import Atom
from resolver.database import PackageDB
from resolver.solver import Resolver, Solution, SlotConflict, Unresolvable
from resolver.config import PortageConfig
from resolver.planner import WorldUpgradePlanner

DB_PATH = '/app/packages.db'
PORTAGE_DIR = '/app/portage'


# --- Version comparison (PMS compliance) ---------------------------------

class TestVersionOrdering:

    def test_letter_suffix_absent_before_present(self):
        """PMS: absent letter sorts before any letter: 1.3 < 1.3a."""
        assert Version('1.3') < Version('1.3a')

    def test_letter_suffix_alphabetical(self):
        assert Version('1.3a') < Version('1.3b')
        assert Version('1.3a') < Version('1.3z')

    def test_release_suffix_ordering(self):
        """PMS: _alpha < _beta < _pre < _rc < (none) < _p."""
        assert Version('1.0_alpha1') < Version('1.0_beta1')
        assert Version('1.0_beta1') < Version('1.0_pre1')
        assert Version('1.0_pre1') < Version('1.0_rc1')
        assert Version('1.0_rc1') < Version('1.0')
        assert Version('1.0') < Version('1.0_p1')

    def test_revision_equivalence(self):
        assert Version('1.0') == Version('1.0-r0')
        assert Version('1.0') < Version('1.0-r1')

    def test_combined_letter_and_suffix(self):
        assert Version('1.2') < Version('1.2a_rc1')
        assert Version('1.2a_rc1') < Version('1.2a')


# --- USE-conditional dependency evaluation -------------------------------

class TestUseConditionals:

    def test_positive_flag_active(self):
        atoms = evaluate('ssl? ( dev-libs/openssl )', {'ssl'})
        assert len(atoms) == 1
        assert atoms[0].cp == 'dev-libs/openssl'

    def test_positive_flag_inactive(self):
        atoms = evaluate('ssl? ( dev-libs/openssl )', set())
        assert len(atoms) == 0

    def test_negated_flag_inactive_includes(self):
        """!debug? means include when debug is NOT set."""
        atoms = evaluate('!debug? ( dev-libs/release-lib )', set())
        assert len(atoms) == 1

    def test_negated_flag_active_excludes(self):
        atoms = evaluate('!debug? ( dev-libs/release-lib )', {'debug'})
        assert len(atoms) == 0

    def test_sibling_conditionals_independent(self):
        """Negated conditional must not pollute subsequent sibling evaluation."""
        depstr = '!minimal? ( dev-libs/expat ) xml? ( dev-libs/libxml2 )'
        atoms = evaluate(depstr, {'xml'})
        cps = {a.cp for a in atoms}
        assert 'dev-libs/expat' in cps, \
            "expat must be included (!minimal? satisfied: minimal is unset)"
        assert 'dev-libs/libxml2' in cps, \
            "libxml2 must be included (xml? satisfied: xml is set)"

    def test_three_sibling_conditionals(self):
        """Three sibling USE conditionals with mixed negation."""
        depstr = '!minimal? ( dev-libs/expat ) xml? ( dev-libs/libxml2 ) ssl? ( dev-libs/openssl )'
        atoms = evaluate(depstr, {'xml', 'ssl'})
        cps = {a.cp for a in atoms}
        assert cps == {'dev-libs/expat', 'dev-libs/libxml2', 'dev-libs/openssl'}

    def test_any_of_picks_first(self):
        depstr = '|| ( dev-libs/openssl dev-libs/libressl )'
        atoms = evaluate(depstr, set())
        assert len(atoms) == 1
        assert atoms[0].cp == 'dev-libs/openssl'


# --- Resolver backtracking -----------------------------------------------

class TestResolverBacktracking:

    def test_fallback_to_older_version(self):
        """crypto-2.0 depends on nonexistent package; must fall back to 1.0."""
        db = PackageDB(DB_PATH)
        r = Resolver(db, use_flags=set())
        sol = r.resolve(['dev-libs/crypto'])
        assert sol.get_version('dev-libs/crypto') == '1.0'
        assert sol.has('dev-libs/icu')

    def test_backtrack_through_parent(self):
        """secure -> crypto; crypto-2.0 fails, so crypto-1.0 must be used."""
        db = PackageDB(DB_PATH)
        r = Resolver(db, use_flags=set())
        sol = r.resolve(['app-misc/secure'])
        assert sol.has('dev-libs/crypto')
        assert sol.get_version('dev-libs/crypto') == '1.0'


# --- Slot-operator rebuild propagation ------------------------------------

class TestSlotRebuildPropagation:

    def test_transitive_rebuild(self):
        """
        Dependency chain: viewer -> render:0= -> codec:0=

        When codec's subslot changes from '2' to '3', both render
        (direct :=) and viewer (transitive :=) must be rebuilt.
        """
        db = PackageDB(DB_PATH)
        r = Resolver(db, use_flags=set())

        old = Solution()
        old.add('media-libs/codec', '3.0', '0', '2')
        old.add('dev-libs/render', '1.0', '0', '0')
        old.add('app-misc/viewer', '1.0', '0', '0')

        new = Solution()
        new.add('media-libs/codec', '3.0', '0', '3')
        new.add('dev-libs/render', '1.0', '0', '0')
        new.add('app-misc/viewer', '1.0', '0', '0')

        rebuilds = r.compute_rebuilds(old, new)
        assert 'dev-libs/render' in rebuilds, \
            "render must rebuild (direct := dep on codec)"
        assert 'app-misc/viewer' in rebuilds, \
            "viewer must rebuild (transitive := dep through render)"


# --- Portage configuration parsing ----------------------------------------

class TestConfigParsing:

    def test_global_use_positive_flags(self):
        config = PortageConfig(PORTAGE_DIR)
        assert 'ssl' in config.global_use
        assert 'xml' in config.global_use

    def test_global_use_negative_flag_excluded(self):
        """Flags prefixed with - in USE= must be excluded, not included."""
        config = PortageConfig(PORTAGE_DIR)
        assert 'minimal' not in config.global_use

    def test_effective_use_merges_overrides(self):
        config = PortageConfig(PORTAGE_DIR)
        use = config.get_effective_use('app-misc/client')
        assert 'ssl' in use
        assert 'xml' in use


# --- Version upgrade detection --------------------------------------------

class TestVersionUpgrades:

    def test_zlib_letter_suffix_upgrade(self):
        """zlib 1.3 -> 1.3a must be detected (PMS letter ordering)."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        cps = {u['cp'] for u in upgrades}
        assert 'sys-libs/zlib' in cps
        z = next(u for u in upgrades if u['cp'] == 'sys-libs/zlib')
        assert z['old_version'] == '1.3'
        assert z['new_version'] == '1.3a'

    def test_all_expected_upgrades(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        cps = {u['cp'] for u in upgrades}
        expected = {
            'sys-libs/zlib', 'dev-libs/openssl', 'dev-libs/icu',
            'dev-libs/boost', 'net-misc/curl', 'dev-libs/expat',
            'media-libs/codec'
        }
        assert cps == expected

    def test_codec_upgrades_to_newest(self):
        """codec must upgrade to 3.0 (newest), not 2.1."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        c = next(u for u in upgrades if u['cp'] == 'media-libs/codec')
        assert c['new_version'] == '3.0'

    def test_no_spurious_upgrades(self):
        """Packages at latest version must not appear in upgrades."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        cps = {u['cp'] for u in upgrades}
        assert 'dev-libs/libxml2' not in cps
        assert 'dev-libs/render' not in cps
        assert 'app-misc/viewer' not in cps
        assert 'app-misc/client' not in cps


# --- Newuse rebuild detection ---------------------------------------------

class TestNewuseRebuilds:

    def test_client_detected(self):
        """client USE changed {xml} -> {ssl,xml}, adding openssl dep."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        upgraded_cps = {u['cp'] for u in upgrades}
        newuse = planner.compute_newuse_rebuilds(upgraded_cps)
        assert 'app-misc/client' in newuse

    def test_no_false_positives(self):
        """Only packages with actual dependency changes qualify."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        upgraded_cps = {u['cp'] for u in upgrades}
        newuse = planner.compute_newuse_rebuilds(upgraded_cps)
        assert len(newuse) == 1


# --- Slot rebuilds in planner context -------------------------------------

class TestSlotRebuilds:

    def test_render_and_viewer_in_slot_rebuilds(self):
        """codec subslot 2->3 triggers render (direct) and viewer (transitive)."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        upgraded_cps = {u['cp'] for u in upgrades}
        newuse = planner.compute_newuse_rebuilds(upgraded_cps)
        slot = planner.compute_slot_rebuilds(upgraded_cps, set(newuse))
        assert 'dev-libs/render' in slot
        assert 'app-misc/viewer' in slot

    def test_upgraded_excluded_from_slot_rebuilds(self):
        """Packages already upgrading must not appear in slot_rebuilds."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        upgrades = planner.compute_version_upgrades()
        upgraded_cps = {u['cp'] for u in upgrades}
        newuse = planner.compute_newuse_rebuilds(upgraded_cps)
        slot = planner.compute_slot_rebuilds(upgraded_cps, set(newuse))
        for u in upgrades:
            assert u['cp'] not in slot


# --- Topological merge ordering -------------------------------------------

class TestMergeOrder:

    def test_all_packages_present(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        plan = planner.generate_plan('/app/upgrade_plan.json')
        all_changed = (
            {u['cp'] for u in plan['upgrades']}
            | set(plan['newuse_rebuilds'])
            | set(plan['slot_rebuilds'])
        )
        assert set(plan['merge_order']) == all_changed

    def test_dependency_ordering(self):
        """Dependencies must appear before their dependents."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        plan = planner.generate_plan('/app/upgrade_plan.json')
        order = plan['merge_order']
        pos = {cp: i for i, cp in enumerate(order)}

        assert pos['sys-libs/zlib'] < pos['dev-libs/openssl'], \
            "zlib must merge before openssl (zlib:0= dep)"
        assert pos['dev-libs/openssl'] < pos['net-misc/curl'], \
            "openssl must merge before curl (openssl:0= dep)"
        assert pos['dev-libs/icu'] < pos['dev-libs/boost'], \
            "icu must merge before boost (icu:0= dep)"
        assert pos['media-libs/codec'] < pos['dev-libs/render'], \
            "codec must merge before render (codec:0= dep)"
        assert pos['dev-libs/render'] < pos['app-misc/viewer'], \
            "render must merge before viewer (render:0= dep)"
        assert pos['dev-libs/expat'] < pos['app-misc/client'], \
            "expat must merge before client (!minimal? dep)"
        assert pos['dev-libs/openssl'] < pos['app-misc/client'], \
            "openssl must merge before client (ssl? dep)"


# --- End-to-end plan generation -------------------------------------------

class TestFullPlan:

    def test_plan_json_structure(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        plan = planner.generate_plan('/app/upgrade_plan.json')

        assert 'upgrades' in plan
        assert 'newuse_rebuilds' in plan
        assert 'slot_rebuilds' in plan
        assert 'merge_order' in plan

        with open('/app/upgrade_plan.json') as f:
            loaded = json.load(f)
        assert loaded == plan

    def test_plan_correctness(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        plan = planner.generate_plan('/app/upgrade_plan.json')

        upgrade_cps = {u['cp'] for u in plan['upgrades']}
        assert len(upgrade_cps) == 7
        assert 'sys-libs/zlib' in upgrade_cps

        assert plan['newuse_rebuilds'] == ['app-misc/client']
        assert sorted(plan['slot_rebuilds']) == ['app-misc/viewer', 'dev-libs/render']
        assert len(plan['merge_order']) == 10


# --- Strategy comparison -------------------------------------------------

class TestStrategyComparison:

    def test_prefer_newest_metrics(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        with open('/app/strategy_comparison.json') as f:
            comp = json.load(f)
        pn = comp['strategies']['prefer_newest']
        assert pn['total_upgrades'] == 7
        assert pn['slot_rebuilds'] == 2
        assert pn['newuse_rebuilds'] == 1
        assert pn['total_merges'] == 10

    def test_minimize_rebuilds_metrics(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        with open('/app/strategy_comparison.json') as f:
            comp = json.load(f)
        mr = comp['strategies']['minimize_rebuilds']
        assert mr['total_upgrades'] == 7
        assert mr['slot_rebuilds'] == 0
        assert mr['newuse_rebuilds'] == 1
        assert mr['total_merges'] == 8

    def test_minimize_rebuilds_codec_version(self):
        """minimize_rebuilds should choose codec 2.1 (same subslot) over 3.0."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        with open('/app/strategy_comparison.json') as f:
            comp = json.load(f)
        mr_upgrades = comp['strategies']['minimize_rebuilds']['upgrades']
        codec = next(u for u in mr_upgrades if u['cp'] == 'media-libs/codec')
        assert codec['new_version'] == '2.1'

    def test_recommended_strategy(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        with open('/app/strategy_comparison.json') as f:
            comp = json.load(f)
        assert comp['recommended'] == 'minimize_rebuilds'
        assert len(comp['rationale']) > 0


# --- Dependency graph (DOT) ----------------------------------------------

class TestDependencyGraph:

    def test_dot_file_exists(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        assert os.path.isfile('/app/dependency_graph.dot')

    def test_dot_contains_digraph(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        with open('/app/dependency_graph.dot') as f:
            dot = f.read()
        assert 'digraph' in dot

    def test_dot_valid_syntax(self):
        """DOT must be parseable by graphviz dot command."""
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        result = subprocess.run(
            ['dot', '-Tsvg', '/app/dependency_graph.dot'],
            capture_output=True
        )
        assert result.returncode == 0, \
            f"dot validation failed: {result.stderr.decode()}"

    def test_dot_contains_all_nodes(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        plan = planner.generate_plan('/app/upgrade_plan.json')
        with open('/app/dependency_graph.dot') as f:
            dot = f.read()
        for cp in plan['merge_order']:
            assert cp in dot, f"{cp} not found in DOT graph"

    def test_dot_contains_edges(self):
        planner = WorldUpgradePlanner(DB_PATH, PORTAGE_DIR)
        planner.generate_plan('/app/upgrade_plan.json')
        with open('/app/dependency_graph.dot') as f:
            dot = f.read()
        assert '->' in dot, "DOT graph must contain dependency edges"
