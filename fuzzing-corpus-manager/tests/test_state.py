"""Tests for fuzzcorp coverage-guided fuzzing framework.

"""

import math
import sys

sys.path.insert(0, "/app")

import pytest

from fuzzcorp.types import Branch, Location, Fingerprint
from fuzzcorp.corpus import Corpus
from fuzzcorp.scheduler import FuzzScheduler, softmax, TargetState
from fuzzcorp.coverage import CoverageCollector


# ===== Helper constructors =====

def make_branch(line1, col1, line2, col2, filename="test.py"):
    return Branch(Location(filename, line1, col1), Location(filename, line2, col2))


def make_fingerprint(*branches):
    return frozenset(branches)


# ===== CoverageCollector Tests =====

class TestCoverageCollector:

    def test_basic_branch_tracking(self):
        """CoverageCollector tracks branches in a simple function."""
        def target(x):
            if x > 0:
                return "positive"
            else:
                return "non-positive"

        with CoverageCollector() as cov:
            target(5)

        assert len(cov.branches) > 0
        for branch in cov.branches:
            assert isinstance(branch, Branch)
            assert isinstance(branch.start, Location)
            assert isinstance(branch.end, Location)

    def test_different_paths_different_branches(self):
        """Different execution paths produce different branch sets."""
        def target(x):
            if x > 0:
                return "positive"
            else:
                return "non-positive"

        with CoverageCollector() as cov1:
            target(5)
        branches_positive = cov1.branches.copy()

        with CoverageCollector() as cov2:
            target(-5)
        branches_negative = cov2.branches.copy()

        assert branches_positive != branches_negative

    def test_filters_stdlib(self):
        """CoverageCollector filters out stdlib branches."""
        import os.path

        with CoverageCollector() as cov:
            os.path.join("a", "b")

        stdlib_path = str(__import__("pathlib").Path(__import__("os").__file__).parent)
        for branch in cov.branches:
            assert not branch.start.filename.startswith(stdlib_path), \
                f"stdlib branch found: {branch}"

    def test_filters_generated_code(self):
        """CoverageCollector filters out generated/frozen code."""
        with CoverageCollector() as cov:
            import posixpath
            posixpath.join("a", "b")

        for branch in cov.branches:
            assert not (branch.start.filename.startswith("<") and
                        branch.start.filename.endswith(">")), \
                f"generated code branch found: {branch}"

    def test_exclude_prefixes(self):
        """CoverageCollector respects custom exclude prefixes."""
        import targets
        target_file = targets.__file__

        # Without exclude: should have branches from targets.py
        with CoverageCollector() as cov_full:
            targets.classify_triangle(3, 4, 5)
        all_files_full = {b.start.filename for b in cov_full.branches}
        assert target_file in all_files_full, \
            f"Should track {target_file} without excludes. Files: {all_files_full}"

        # With exclude: should NOT have branches from targets.py
        with CoverageCollector(exclude_prefixes=[target_file]) as cov_excl:
            targets.classify_triangle(3, 4, 5)
        for branch in cov_excl.branches:
            assert branch.start.filename != target_file, \
                f"Should not track {target_file} with excludes"

    def test_reuse_resets_coverage(self):
        """Re-entering the context manager resets coverage."""
        collector = CoverageCollector()

        def target(x):
            if x > 0:
                return "positive"
            else:
                return "non-positive"

        with collector:
            target(5)
        first_branches = collector.branches.copy()
        assert len(first_branches) > 0

        with collector:
            target(-5)
        second_branches = collector.branches.copy()
        assert len(second_branches) > 0

        # If branches accumulated, first would be subset of second.
        # Since we reset, the if-true branch from the first run should
        # not appear in the second run (which takes the else path).
        assert not first_branches.issubset(second_branches), \
            "Branches from first run should not appear in second run"

    def test_branch_locations_have_columns(self):
        """Branches should have column information (Python 3.12+)."""
        def target(x):
            if x > 0:
                return 1
            return -1

        with CoverageCollector() as cov:
            target(5)

        for branch in cov.branches:
            assert branch.start.column is not None, \
                f"missing column in branch start: {branch}"
            assert branch.end.column is not None, \
                f"missing column in branch end: {branch}"

    def test_collect_from_imported_module(self):
        """CoverageCollector tracks branches in imported modules."""
        import targets

        with CoverageCollector() as cov:
            targets.classify_triangle(3, 4, 5)

        target_file = targets.__file__
        target_branches = [b for b in cov.branches if b.start.filename == target_file]
        assert len(target_branches) > 0, \
            f"No branches from {target_file} found. All: {cov.branches}"


# ===== Corpus Tests =====

class TestCorpus:

    def test_add_new_fingerprint(self):
        """Adding a new fingerprint returns True and stores input."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        result = corpus.consider(b"input1", fp)

        assert result is True
        assert b"input1" in corpus.inputs
        assert corpus.fingerprints[fp] == b"input1"
        assert corpus.behavior_counts[b1] == 1
        corpus.check_invariants()

    def test_duplicate_fingerprint_same_input(self):
        """Adding same fingerprint with same input returns False."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"input1", fp)
        result = corpus.consider(b"input1", fp)

        assert result is False
        corpus.check_invariants()

    def test_replace_with_shorter_input(self):
        """Shorter input replaces existing for same fingerprint."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"longer_input", fp)
        result = corpus.consider(b"short", fp)

        assert result is True
        assert corpus.fingerprints[fp] == b"short"
        assert b"short" in corpus.inputs
        assert b"longer_input" not in corpus.inputs
        corpus.check_invariants()

    def test_no_replace_with_longer_input(self):
        """Longer input does NOT replace existing."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"ab", fp)
        result = corpus.consider(b"abc", fp)

        assert result is False
        assert corpus.fingerprints[fp] == b"ab"
        corpus.check_invariants()

    def test_shortlex_same_length_lexicographic(self):
        """Same length: lexicographically smaller wins."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"zz", fp)
        result = corpus.consider(b"aa", fp)

        assert result is True
        assert corpus.fingerprints[fp] == b"aa"
        corpus.check_invariants()

    def test_shortlex_shorter_always_wins(self):
        """Shorter always wins regardless of lexicographic order."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"aaa", fp)
        result = corpus.consider(b"zz", fp)

        assert result is True
        assert corpus.fingerprints[fp] == b"zz"
        corpus.check_invariants()

    def test_reference_counting_no_premature_eviction(self):
        """Input covering 2 fingerprints is not evicted when one is replaced."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)
        fp1 = make_fingerprint(b1)
        fp2 = make_fingerprint(b1, b2)

        # Same input covers two fingerprints
        corpus.consider(b"shared_input", fp1)
        corpus.consider(b"shared_input", fp2)

        assert len(corpus.inputs) == 1
        assert len(corpus.fingerprints) == 2
        corpus.check_invariants()

        # Replace fp1 with shorter input - shared_input still covers fp2
        corpus.consider(b"x", fp1)

        assert b"shared_input" in corpus.inputs  # NOT evicted
        assert b"x" in corpus.inputs
        assert len(corpus.inputs) == 2
        corpus.check_invariants()

    def test_reference_counting_eviction_at_zero(self):
        """Input is evicted when its reference count reaches zero."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)
        fp1 = make_fingerprint(b1)
        fp2 = make_fingerprint(b1, b2)

        corpus.consider(b"shared_input", fp1)
        corpus.consider(b"shared_input", fp2)
        corpus.check_invariants()

        # Replace both fingerprints
        corpus.consider(b"a", fp1)
        corpus.consider(b"b", fp2)

        assert b"shared_input" not in corpus.inputs  # Evicted
        corpus.check_invariants()

    def test_behavior_count_increment_no_change(self):
        """When corpus doesn't change, behavior counts are incremented."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"input1", fp)
        assert corpus.behavior_counts[b1] == 1

        # Same fingerprint, same input -> no change, just increment
        corpus.consider(b"input1", fp)
        assert corpus.behavior_counts[b1] == 2

        # Same fingerprint, longer input -> no change, just increment
        corpus.consider(b"longer_input", fp)
        assert corpus.behavior_counts[b1] == 3

        corpus.check_invariants()

    def test_behavior_count_reset_on_new_fingerprint(self):
        """When a new fingerprint is added, behavior counts reset to 1."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)
        fp1 = make_fingerprint(b1)

        corpus.consider(b"a", fp1)
        # Simulate many observations
        corpus.behavior_counts[b1] = 100

        # Adding a new fingerprint resets counts
        fp2 = make_fingerprint(b1, b2)
        corpus.consider(b"b", fp2)

        assert corpus.behavior_counts[b1] == 1
        assert corpus.behavior_counts[b2] == 1
        corpus.check_invariants()

    def test_behavior_count_reset_on_replacement(self):
        """When input is replaced with shorter, behavior counts reset."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"long_input", fp)
        corpus.behavior_counts[b1] = 50

        # Replacing with shorter input resets counts
        corpus.consider(b"x", fp)

        assert corpus.behavior_counts[b1] == 1
        corpus.check_invariants()

    def test_empty_fingerprint_rejected(self):
        """Empty fingerprint is not added to corpus."""
        corpus = Corpus()

        result = corpus.consider(b"input", frozenset())

        assert result is False
        assert len(corpus.inputs) == 0
        assert len(corpus.fingerprints) == 0
        corpus.check_invariants()

    def test_many_fingerprints_one_input(self):
        """Multiple fingerprints can map to the same input."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)
        b3 = make_branch(5, 0, 6, 0)

        fp1 = make_fingerprint(b1)
        fp2 = make_fingerprint(b2)
        fp3 = make_fingerprint(b3)

        corpus.consider(b"x", fp1)
        corpus.consider(b"x", fp2)
        corpus.consider(b"x", fp3)

        assert len(corpus.inputs) == 1
        assert len(corpus.fingerprints) == 3
        corpus.check_invariants()

    def test_invariant_behaviors_equal_union_of_fingerprints(self):
        """Behavior counts keys match union of all fingerprint branches."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)
        b3 = make_branch(5, 0, 6, 0)

        corpus.consider(b"a", make_fingerprint(b1, b2))
        corpus.consider(b"b", make_fingerprint(b2, b3))

        expected = {b1, b2, b3}
        assert set(corpus.behavior_counts) == expected
        corpus.check_invariants()

    def test_corpus_stability_under_operations(self):
        """Corpus invariants hold through a series of mixed operations."""
        corpus = Corpus()
        branches = [make_branch(i, 0, i + 1, 0) for i in range(10)]

        # Add various fingerprints with unique inputs
        for i in range(5):
            fp = make_fingerprint(branches[i], branches[i + 1])
            corpus.consider(f"input_{i}".encode(), fp)
            corpus.check_invariants()

        # Replace all with shorter input
        for i in range(5):
            fp = make_fingerprint(branches[i], branches[i + 1])
            corpus.consider(b"x", fp)
            corpus.check_invariants()

        # All fingerprints should now map to b"x"
        assert len(corpus.inputs) == 1
        assert b"x" in corpus.inputs


# ===== Scheduler Tests =====

class TestSoftmax:

    def test_basic_properties(self):
        """Softmax output sums to 1 and preserves order."""
        result = softmax([1.0, 2.0, 3.0])

        assert len(result) == 3
        assert abs(sum(result) - 1.0) < 1e-10
        assert result[0] < result[1] < result[2]

    def test_numerical_stability(self):
        """Softmax handles large values without overflow."""
        result = softmax([1000.0, 1001.0, 1002.0])

        assert all(0.0 <= x <= 1.0 for x in result)
        assert abs(sum(result) - 1.0) < 1e-10
        assert all(math.isfinite(x) for x in result)

    def test_negative_values(self):
        """Softmax handles negative values."""
        result = softmax([-1000.0, -999.0, -998.0])

        assert abs(sum(result) - 1.0) < 1e-10
        assert all(math.isfinite(x) for x in result)

    def test_empty_list(self):
        """Softmax of empty list is empty list."""
        assert softmax([]) == []

    def test_single_element(self):
        """Softmax of single element is [1.0]."""
        result = softmax([42.0])
        assert len(result) == 1
        assert abs(result[0] - 1.0) < 1e-10

    def test_equal_values(self):
        """Equal values produce uniform distribution."""
        result = softmax([5.0, 5.0, 5.0])
        for r in result:
            assert abs(r - 1.0 / 3.0) < 1e-10


class TestFuzzScheduler:

    def test_register_target(self):
        """Registering a target creates initial state."""
        sched = FuzzScheduler()
        sched.register_target("t1")

        assert "t1" in sched.targets
        assert sched.targets["t1"].ninputs == 0
        assert sched.targets["t1"].elapsed_time == 0.0
        assert sched.targets["t1"].since_new_behavior == 0

    def test_record_execution_found_new(self):
        """Recording with found_new=True resets since_new_behavior."""
        sched = FuzzScheduler()
        sched.register_target("t1")

        sched.record_execution("t1", 0.1, False)
        sched.record_execution("t1", 0.1, False)
        assert sched.targets["t1"].since_new_behavior == 2

        sched.record_execution("t1", 0.1, True)
        assert sched.targets["t1"].since_new_behavior == 0
        assert sched.targets["t1"].ninputs == 3

    def test_behaviors_per_input_initial(self):
        """behaviors_per_input returns 1.0 when since_new_behavior == 0."""
        sched = FuzzScheduler()
        sched.register_target("t1")

        assert sched.behaviors_per_input("t1") == 1.0

    def test_behaviors_per_input_decreasing(self):
        """behaviors_per_input decreases as since_new_behavior increases."""
        sched = FuzzScheduler()
        sched.register_target("t1")
        sched.record_execution("t1", 0.1, True)
        assert sched.behaviors_per_input("t1") == 1.0

        sched.record_execution("t1", 0.1, False)  # since=1
        assert sched.behaviors_per_input("t1") == 1.0

        sched.record_execution("t1", 0.1, False)  # since=2
        assert abs(sched.behaviors_per_input("t1") - 0.5) < 1e-10

        sched.record_execution("t1", 0.1, False)  # since=3
        assert abs(sched.behaviors_per_input("t1") - 1.0 / 3.0) < 1e-10

    def test_behaviors_per_second_no_time(self):
        """behaviors_per_second returns 1.0 when no time elapsed."""
        sched = FuzzScheduler()
        sched.register_target("t1")

        assert sched.behaviors_per_second("t1") == 1.0

    def test_behaviors_per_second_with_time(self):
        """behaviors_per_second accounts for execution speed."""
        sched = FuzzScheduler()
        sched.register_target("t1")

        # 10 inputs in 1 second, all finding new behaviors
        for _ in range(10):
            sched.record_execution("t1", 0.1, True)

        # inputs_per_second = 10/1.0 = 10, bpi = 1.0, bps = 10.0
        assert abs(sched.behaviors_per_second("t1") - 10.0) < 1e-10

    def test_get_probabilities_sum_to_one(self):
        """get_probabilities returns valid probability distribution."""
        sched = FuzzScheduler()
        sched.register_target("t1")
        sched.register_target("t2")

        sched.record_execution("t1", 0.1, True)
        sched.record_execution("t2", 0.5, False)
        sched.record_execution("t2", 0.5, False)

        probs = sched.get_probabilities()
        assert abs(sum(probs.values()) - 1.0) < 1e-10
        assert "t1" in probs
        assert "t2" in probs

    def test_get_probabilities_favors_productive_target(self):
        """Target finding more behaviors gets higher probability."""
        sched = FuzzScheduler()
        sched.register_target("productive")
        sched.register_target("stale")

        # Productive: finding new behaviors every time
        for _ in range(10):
            sched.record_execution("productive", 0.01, True)

        # Stale: found one, then nothing for a long time
        sched.record_execution("stale", 0.01, True)
        for _ in range(100):
            sched.record_execution("stale", 0.01, False)

        probs = sched.get_probabilities()
        assert probs["productive"] > probs["stale"]

    def test_get_probabilities_empty(self):
        """get_probabilities with no targets returns empty dict."""
        sched = FuzzScheduler()
        assert sched.get_probabilities() == {}


class TestPowerSchedule:

    def test_basic_weights(self):
        """Power schedule produces normalized weights."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)

        corpus.consider(b"a", make_fingerprint(b1))
        corpus.consider(b"b", make_fingerprint(b2))

        weights = FuzzScheduler.power_schedule(corpus)
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_rare_branches_higher_weight(self):
        """Fingerprints with rare branches get higher weight."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)
        fp1 = make_fingerprint(b1)
        fp2 = make_fingerprint(b2)

        corpus.consider(b"a", fp1)
        corpus.consider(b"b", fp2)

        # Make b1 very common, b2 rare
        corpus.behavior_counts[b1] = 1000
        corpus.behavior_counts[b2] = 1

        weights = FuzzScheduler.power_schedule(corpus)
        assert weights[fp2] > weights[fp1]

    def test_empty_corpus(self):
        """Power schedule of empty corpus returns empty dict."""
        corpus = Corpus()
        assert FuzzScheduler.power_schedule(corpus) == {}

    def test_single_fingerprint(self):
        """Single fingerprint gets weight 1.0."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        fp = make_fingerprint(b1)

        corpus.consider(b"a", fp)

        weights = FuzzScheduler.power_schedule(corpus)
        assert abs(weights[fp] - 1.0) < 1e-10

    def test_weight_uses_rarest_branch(self):
        """Weight is determined by the rarest branch in the fingerprint."""
        corpus = Corpus()
        b1 = make_branch(1, 0, 2, 0)
        b2 = make_branch(3, 0, 4, 0)
        b3 = make_branch(5, 0, 6, 0)

        # fp1 has b1 (common) and b2 (rare)
        # fp2 has b3 (medium)
        fp1 = make_fingerprint(b1, b2)
        fp2 = make_fingerprint(b3)

        corpus.consider(b"a", fp1)
        corpus.consider(b"b", fp2)

        corpus.behavior_counts[b1] = 100
        corpus.behavior_counts[b2] = 2    # rarest in fp1 -> weight ~ 1/2
        corpus.behavior_counts[b3] = 10   # rarest in fp2 -> weight ~ 1/10

        weights = FuzzScheduler.power_schedule(corpus)
        # fp1 has rarer branch (count=2) than fp2 (count=10)
        assert weights[fp1] > weights[fp2]


# ===== Integration Test =====

class TestIntegration:

    def test_coverage_corpus_scheduler_pipeline(self):
        """Full pipeline: coverage -> corpus -> scheduler."""
        import targets

        corpus = Corpus()
        sched = FuzzScheduler()
        sched.register_target("triangle")

        test_inputs = [
            (3, 3, 3),     # equilateral
            (3, 3, 4),     # isosceles
            (3, 4, 5),     # scalene
            (-1, 2, 3),    # invalid (negative)
            (1, 2, 10),    # invalid (triangle inequality)
        ]

        for args in test_inputs:
            with CoverageCollector() as cov:
                targets.classify_triangle(*args)

            fingerprint = frozenset(cov.branches)
            changed = corpus.consider(str(args).encode(), fingerprint)
            sched.record_execution("triangle", 0.001, changed)
            corpus.check_invariants()

        # Should have multiple distinct fingerprints (different code paths)
        assert len(corpus.fingerprints) >= 3, \
            f"Expected >=3 fingerprints, got {len(corpus.fingerprints)}"

        # Scheduler probabilities are valid
        probs = sched.get_probabilities()
        assert abs(sum(probs.values()) - 1.0) < 1e-10

        # Power schedule produces valid weights
        weights = FuzzScheduler.power_schedule(corpus)
        assert len(weights) > 0
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_corpus_stability_under_mixed_operations(self):
        """Corpus invariants hold through mixed add/replace/evict operations."""
        corpus = Corpus()
        branches = [make_branch(i, 0, i + 1, 0) for i in range(20)]

        # Phase 1: add fingerprints with unique inputs
        for i in range(8):
            fp = make_fingerprint(branches[i], branches[i + 1])
            corpus.consider(f"input_{i:04d}".encode(), fp)
            corpus.check_invariants()

        # Phase 2: add overlapping fingerprint with shared input
        fp_shared = make_fingerprint(branches[0], branches[1])
        # This input already exists for fp_shared, so no change
        existing_input = corpus.fingerprints[fp_shared]
        corpus.consider(existing_input, fp_shared)
        corpus.check_invariants()

        # Phase 3: replace all with shorter inputs
        for i in range(8):
            fp = make_fingerprint(branches[i], branches[i + 1])
            corpus.consider(b"x", fp)
            corpus.check_invariants()

        assert len(corpus.inputs) == 1
        assert b"x" in corpus.inputs
        corpus.check_invariants()
