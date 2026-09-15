
"""Pytest tests for the geometric evaluation pipeline.

Verifies output schema, metric value ranges, relative ordering constraints,
invalid mesh detection, bidirectional Hausdorff distance, HD95 invariants,
IoU correctness, deviation profile structure, composite similarity score
monotonicity, and cross-metric invariants.
"""

import json
import os
import pytest

RESULTS_FILE = '/app/results.json'


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_FILE), f"Results file not found at {RESULTS_FILE}"
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    return data


def get_pair(results, pair_id):
    for entry in results['metrics']:
        if entry['pair_id'] == pair_id:
            return entry
    pytest.fail(f"Pair '{pair_id}' not found in results")


# ======= Schema / Structure Tests =======

class TestOutputSchema:

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_FILE), "results.json must exist"

    def test_has_metrics_key(self, results):
        assert 'metrics' in results, "Top-level 'metrics' key required"

    def test_metrics_is_list(self, results):
        assert isinstance(results['metrics'], list)

    def test_correct_pair_count(self, results):
        assert len(results['metrics']) == 8, f"Expected 8 pairs, got {len(results['metrics'])}"

    def test_required_fields_present(self, results):
        required = {
            'pair_id', 'reference', 'candidate',
            'chamfer_distance', 'hausdorff_distance', 'hausdorff_95',
            'iou', 'deviation_profile', 'similarity_score',
            'is_valid_ref', 'is_valid_cand',
        }
        for entry in results['metrics']:
            missing = required - set(entry.keys())
            assert not missing, f"Pair {entry.get('pair_id', '?')}: missing fields {missing}"


# ======= Chamfer Distance Unit Tests (must be squared Euclidean) =======

class TestChamferDistanceUnits:
    """CD must use squared Euclidean distances (mm^2), not raw Euclidean (mm).

    For mismatched pairs with known geometric differences, squared CD is
    significantly larger than unsquared CD. These thresholds are calibrated
    to distinguish the two.
    """

    def test_wrong_dim_box_cd_above_squared_threshold(self, results):
        p = get_pair(results, 'pair_2')
        assert p['chamfer_distance'] is not None
        assert p['chamfer_distance'] > 5.0, \
            f"CD for wrong-dim box must be > 5.0 (squared units), got {p['chamfer_distance']}"

    def test_wrong_radius_cylinder_cd_above_squared_threshold(self, results):
        p = get_pair(results, 'pair_4')
        assert p['chamfer_distance'] is not None
        assert p['chamfer_distance'] > 10.0, \
            f"CD for wrong-radius cylinder must be > 10.0, got {p['chamfer_distance']}"

    def test_wrong_shape_cd_above_threshold(self, results):
        p = get_pair(results, 'pair_6')
        assert p['chamfer_distance'] is not None
        assert p['chamfer_distance'] > 8.0, \
            f"CD for cone-vs-sphere must be > 8.0, got {p['chamfer_distance']}"


# ======= Hausdorff Distance Bidirectionality Tests =======

class TestHausdorffBidirectional:
    """HD must be computed in both directions (P->Q and Q->P).

    pair_8 uses an asymmetric containment pair (small sphere r=8 inside
    box 50x40x30). The forward max-min distance (~15mm) is much smaller
    than the backward max-min distance (~27mm). Only a correct bidirectional
    computation produces HD > 22.
    """

    def test_asymmetric_pair_hd_above_bidirectional_threshold(self, results):
        p = get_pair(results, 'pair_8')
        assert p['hausdorff_distance'] is not None
        assert p['hausdorff_distance'] > 22.0, \
            f"HD for sphere-in-box must be > 22.0 (bidirectional), got {p['hausdorff_distance']}"

    def test_asymmetric_pair_hd_sanity_upper(self, results):
        p = get_pair(results, 'pair_8')
        assert p['hausdorff_distance'] is not None
        assert p['hausdorff_distance'] < 40.0, \
            f"HD for sphere-in-box must be < 40.0, got {p['hausdorff_distance']}"

    def test_matching_box_hd_is_small(self, results):
        p = get_pair(results, 'pair_1')
        assert p['hausdorff_distance'] is not None
        assert p['hausdorff_distance'] < 5.0, \
            f"HD for matching box must be < 5.0, got {p['hausdorff_distance']}"


# ======= 95th-Percentile Hausdorff Distance Tests =======

class TestHausdorff95:
    """HD95 is a robust variant of HD using the 95th percentile instead of max.

    Must be implemented bidirectionally. The stub returns 0.0, so any positive
    value for valid mismatched pairs confirms implementation. HD95 <= HD must
    hold as a mathematical invariant.
    """

    def test_hd95_positive_for_mismatched(self, results):
        """HD95 must be > 0 for valid mismatched pairs (catches 0.0 stub)."""
        for pid in ['pair_2', 'pair_4', 'pair_6', 'pair_8']:
            p = get_pair(results, pid)
            assert p['hausdorff_95'] is not None
            assert p['hausdorff_95'] > 0.0, \
                f"HD95 for {pid} must be > 0.0, got {p['hausdorff_95']}"

    def test_hd95_le_hd_invariant(self, results):
        """HD95 <= HD must hold for all valid pairs (percentile <= max)."""
        for p in results['metrics']:
            if p['hausdorff_95'] is not None and p['hausdorff_distance'] is not None:
                assert p['hausdorff_95'] <= p['hausdorff_distance'] + 0.01, \
                    f"HD95 ({p['hausdorff_95']:.4f}) must be <= HD ({p['hausdorff_distance']:.4f}) " \
                    f"for {p['pair_id']}"

    def test_hd95_strictly_less_for_mismatched(self, results):
        """For mismatched pairs with many samples, P95 < max (strictly)."""
        for pid in ['pair_2', 'pair_4', 'pair_6', 'pair_8']:
            p = get_pair(results, pid)
            if p['hausdorff_95'] is not None and p['hausdorff_distance'] is not None:
                assert p['hausdorff_95'] < p['hausdorff_distance'], \
                    f"HD95 ({p['hausdorff_95']:.4f}) must be strictly < HD " \
                    f"({p['hausdorff_distance']:.4f}) for {pid}"

    def test_hd95_small_for_matching(self, results):
        """HD95 should be small for matching pairs."""
        p = get_pair(results, 'pair_1')
        assert p['hausdorff_95'] is not None
        assert p['hausdorff_95'] < 5.0, \
            f"HD95 for matching box must be < 5.0, got {p['hausdorff_95']}"

    def test_hd95_null_for_invalid(self, results):
        """HD95 must be null for invalid pairs."""
        p = get_pair(results, 'pair_7')
        assert p['hausdorff_95'] is None, "HD95 must be null for invalid mesh"


# ======= IoU Correctness Tests (each mesh tested independently) =======

class TestIoUCorrectness:
    """IoU must test containment for each mesh independently.

    If the same mesh is accidentally used for both containment checks,
    IoU becomes 1.0 for all valid pairs regardless of geometric mismatch.
    """

    def test_wrong_dim_box_iou_below_unity(self, results):
        p = get_pair(results, 'pair_2')
        assert p['iou'] < 0.90, \
            f"IoU for wrong-dim box must be < 0.90, got {p['iou']}"

    def test_wrong_dim_box_iou_above_floor(self, results):
        p = get_pair(results, 'pair_2')
        assert p['iou'] > 0.50, \
            f"IoU for wrong-dim box must be > 0.50, got {p['iou']}"

    def test_wrong_radius_cylinder_iou_below_threshold(self, results):
        p = get_pair(results, 'pair_4')
        assert p['iou'] < 0.75, \
            f"IoU for wrong-radius cylinder must be < 0.75, got {p['iou']}"

    def test_wrong_shape_iou_below_threshold(self, results):
        p = get_pair(results, 'pair_6')
        assert p['iou'] < 0.70, \
            f"IoU for cone-vs-sphere must be < 0.70, got {p['iou']}"


# ======= Surface Deviation Profile Tests =======

class TestDeviationProfile:
    """Surface deviation profile must be a normalized histogram of bidirectional
    nearest-neighbor distances. The stub returns [], so non-empty list confirms
    implementation.
    """

    def test_profile_is_list_with_correct_length(self, results):
        for p in results['metrics']:
            if p['deviation_profile'] is not None:
                assert isinstance(p['deviation_profile'], list), \
                    f"deviation_profile must be a list for {p['pair_id']}"
                assert len(p['deviation_profile']) == 10, \
                    f"deviation_profile must have 10 bins for {p['pair_id']}, " \
                    f"got {len(p['deviation_profile'])}"

    def test_profile_sums_to_one(self, results):
        for p in results['metrics']:
            if p['deviation_profile'] is not None and len(p['deviation_profile']) > 0:
                total = sum(p['deviation_profile'])
                assert abs(total - 1.0) < 0.02, \
                    f"deviation_profile must sum to ~1.0 for {p['pair_id']}, got {total}"

    def test_profile_all_non_negative(self, results):
        for p in results['metrics']:
            if p['deviation_profile'] is not None:
                for i, val in enumerate(p['deviation_profile']):
                    assert val >= 0.0, \
                        f"deviation_profile[{i}] must be >= 0 for {p['pair_id']}, got {val}"

    def test_profile_not_empty_stub(self, results):
        """Profile must not be an empty list (catches [] stub)."""
        for p in results['metrics']:
            if p['deviation_profile'] is not None:
                assert len(p['deviation_profile']) > 0, \
                    f"deviation_profile must not be empty for {p['pair_id']}"

    def test_profile_null_for_invalid(self, results):
        p = get_pair(results, 'pair_7')
        assert p['deviation_profile'] is None, \
            "deviation_profile must be null for invalid mesh"

    def test_matching_pair_profile_concentrated(self, results):
        """For matching pairs, most distances are small so mass concentrates early."""
        p = get_pair(results, 'pair_1')
        assert p['deviation_profile'] is not None
        assert len(p['deviation_profile']) == 10
        first_half = sum(p['deviation_profile'][:5])
        assert first_half > 0.70, \
            f"First 5 bins should contain > 70% of mass for matching pair, got {first_half:.2f}"

    def test_mismatched_pair_profile_spread(self, results):
        """For mismatched pairs, mass should not all concentrate in the first bin."""
        p = get_pair(results, 'pair_6')
        assert p['deviation_profile'] is not None
        assert len(p['deviation_profile']) == 10
        assert p['deviation_profile'][0] < 0.80, \
            f"First bin should contain < 80% of mass for mismatched pair, " \
            f"got {p['deviation_profile'][0]:.2f}"


# ======= Matching Pair Quality Tests =======

class TestMatchingPairs:

    def test_box_match_cd(self, results):
        p = get_pair(results, 'pair_1')
        assert p['chamfer_distance'] is not None
        assert p['chamfer_distance'] < 2.0, \
            f"CD for matching box should be < 2.0, got {p['chamfer_distance']}"

    def test_box_match_iou(self, results):
        p = get_pair(results, 'pair_1')
        assert p['iou'] > 0.85

    def test_box_match_validity(self, results):
        p = get_pair(results, 'pair_1')
        assert p['is_valid_ref'] is True
        assert p['is_valid_cand'] is True

    def test_cylinder_match_cd(self, results):
        p = get_pair(results, 'pair_3')
        assert p['chamfer_distance'] is not None
        assert p['chamfer_distance'] < 2.0

    def test_cylinder_match_iou(self, results):
        p = get_pair(results, 'pair_3')
        assert p['iou'] > 0.85

    def test_cone_match_cd(self, results):
        p = get_pair(results, 'pair_5')
        assert p['chamfer_distance'] is not None
        assert p['chamfer_distance'] < 2.0

    def test_cone_match_iou(self, results):
        p = get_pair(results, 'pair_5')
        assert p['iou'] > 0.85


# ======= Invalid Mesh Detection =======

class TestInvalidMesh:

    def test_invalid_candidate_detected(self, results):
        p = get_pair(results, 'pair_7')
        assert p['is_valid_cand'] is False, \
            "Degenerate flat-surface mesh must be detected as invalid"

    def test_invalid_cd_is_null(self, results):
        p = get_pair(results, 'pair_7')
        assert p['chamfer_distance'] is None, "CD must be null for invalid mesh"

    def test_invalid_hd_is_null(self, results):
        p = get_pair(results, 'pair_7')
        assert p['hausdorff_distance'] is None, "HD must be null for invalid mesh"

    def test_invalid_hd95_is_null(self, results):
        p = get_pair(results, 'pair_7')
        assert p['hausdorff_95'] is None, "HD95 must be null for invalid mesh"

    def test_invalid_iou_is_zero(self, results):
        p = get_pair(results, 'pair_7')
        assert p['iou'] == 0.0, "IoU must be 0.0 for invalid mesh"

    def test_invalid_profile_is_null(self, results):
        p = get_pair(results, 'pair_7')
        assert p['deviation_profile'] is None, \
            "deviation_profile must be null for invalid mesh"

    def test_invalid_score_is_null(self, results):
        p = get_pair(results, 'pair_7')
        assert p['similarity_score'] is None, \
            "similarity_score must be null for invalid mesh"


# ======= Ordering / Relative Constraint Tests =======

class TestOrdering:

    def test_cd_ordering_box(self, results):
        match_cd = get_pair(results, 'pair_1')['chamfer_distance']
        wrong_cd = get_pair(results, 'pair_2')['chamfer_distance']
        assert match_cd < wrong_cd, \
            f"Matching box CD ({match_cd}) must be < wrong box CD ({wrong_cd})"

    def test_iou_ordering_box(self, results):
        match_iou = get_pair(results, 'pair_1')['iou']
        wrong_iou = get_pair(results, 'pair_2')['iou']
        assert match_iou > wrong_iou, \
            f"Matching box IoU ({match_iou}) must be > wrong box IoU ({wrong_iou})"

    def test_cd_ordering_cylinder(self, results):
        match_cd = get_pair(results, 'pair_3')['chamfer_distance']
        wrong_cd = get_pair(results, 'pair_4')['chamfer_distance']
        assert match_cd < wrong_cd

    def test_iou_ordering_cylinder(self, results):
        match_iou = get_pair(results, 'pair_3')['iou']
        wrong_iou = get_pair(results, 'pair_4')['iou']
        assert match_iou > wrong_iou

    def test_hd_ordering_box(self, results):
        match_hd = get_pair(results, 'pair_1')['hausdorff_distance']
        wrong_hd = get_pair(results, 'pair_2')['hausdorff_distance']
        assert match_hd < wrong_hd, \
            f"Matching box HD ({match_hd}) must be < wrong box HD ({wrong_hd})"


# ======= Metric Invariant Tests =======

class TestInvariants:

    def test_cd_non_negative(self, results):
        for p in results['metrics']:
            if p['chamfer_distance'] is not None:
                assert p['chamfer_distance'] >= 0, \
                    f"CD must be >= 0, got {p['chamfer_distance']} for {p['pair_id']}"

    def test_hausdorff_non_negative(self, results):
        for p in results['metrics']:
            if p['hausdorff_distance'] is not None:
                assert p['hausdorff_distance'] >= 0, \
                    f"HD must be >= 0, got {p['hausdorff_distance']} for {p['pair_id']}"

    def test_iou_in_unit_range(self, results):
        for p in results['metrics']:
            assert 0.0 <= p['iou'] <= 1.0, \
                f"IoU must be in [0, 1], got {p['iou']} for {p['pair_id']}"

    def test_all_references_valid(self, results):
        for p in results['metrics']:
            assert p['is_valid_ref'] is True, \
                f"All reference meshes must be valid, but {p['pair_id']} ref is invalid"

    def test_hausdorff_ge_sqrt_chamfer_for_valid(self, results):
        """For valid pairs, HD^2 >= CD must hold (max >= mean for squared distances)."""
        for p in results['metrics']:
            if p['chamfer_distance'] is not None and p['hausdorff_distance'] is not None:
                hd_sq = p['hausdorff_distance'] ** 2
                assert hd_sq >= p['chamfer_distance'] * 0.95, \
                    f"HD^2 ({hd_sq:.4f}) should be >= CD ({p['chamfer_distance']:.4f}) " \
                    f"for {p['pair_id']}"


# ======= Composite Similarity Score Tests =======

class TestCompositeSimilarityScore:
    """Composite similarity score must combine all individual metrics into a
    monotonically correct [0,1] score where higher values indicate greater
    geometric similarity. Correct ordering requires ALL upstream metrics to
    be computed correctly AND the distance-to-similarity normalization to be
    monotonically decreasing.
    """

    def test_score_in_unit_range(self, results):
        """All non-null scores must be in [0, 1]."""
        for p in results['metrics']:
            if p['similarity_score'] is not None:
                assert 0.0 <= p['similarity_score'] <= 1.0, \
                    f"similarity_score must be in [0, 1] for {p['pair_id']}, " \
                    f"got {p['similarity_score']}"

    def test_score_null_for_invalid(self, results):
        """Score must be null for invalid pairs."""
        p = get_pair(results, 'pair_7')
        assert p['similarity_score'] is None, \
            "similarity_score must be null for invalid mesh pair"

    def test_score_not_null_for_valid(self, results):
        """Score must be computed (not null) for all valid pairs."""
        for pid in ['pair_1', 'pair_2', 'pair_3', 'pair_4',
                     'pair_5', 'pair_6', 'pair_8']:
            p = get_pair(results, pid)
            assert p['similarity_score'] is not None, \
                f"similarity_score must not be None for valid pair {pid}"

    def test_matching_box_score_high(self, results):
        """Matching box pair should have high similarity score (> 0.75)."""
        p = get_pair(results, 'pair_1')
        assert p['similarity_score'] is not None
        assert p['similarity_score'] > 0.75, \
            f"similarity_score for matching box must be > 0.75, got {p['similarity_score']}"

    def test_matching_higher_than_wrong_dim(self, results):
        """Matching box must score higher than wrong-dimension box."""
        match = get_pair(results, 'pair_1')
        wrong = get_pair(results, 'pair_2')
        assert match['similarity_score'] is not None and wrong['similarity_score'] is not None
        assert match['similarity_score'] > wrong['similarity_score'], \
            f"Matching box score ({match['similarity_score']:.4f}) must be > " \
            f"wrong box score ({wrong['similarity_score']:.4f})"

    def test_matching_higher_than_wrong_shape(self, results):
        """Matching cone must score higher than cone-vs-sphere."""
        match = get_pair(results, 'pair_5')
        wrong = get_pair(results, 'pair_6')
        assert match['similarity_score'] is not None and wrong['similarity_score'] is not None
        assert match['similarity_score'] > wrong['similarity_score'], \
            f"Matching cone score ({match['similarity_score']:.4f}) must be > " \
            f"wrong shape score ({wrong['similarity_score']:.4f})"

    def test_matching_higher_than_wrong_radius(self, results):
        """Matching cylinder must score higher than wrong-radius cylinder."""
        match = get_pair(results, 'pair_3')
        wrong = get_pair(results, 'pair_4')
        assert match['similarity_score'] is not None and wrong['similarity_score'] is not None
        assert match['similarity_score'] > wrong['similarity_score'], \
            f"Matching cylinder score ({match['similarity_score']:.4f}) must be > " \
            f"wrong radius score ({wrong['similarity_score']:.4f})"

    def test_wrong_shape_score_below_threshold(self, results):
        """Cone vs sphere (very different) should have similarity < 0.75."""
        p = get_pair(results, 'pair_6')
        assert p['similarity_score'] is not None
        assert p['similarity_score'] < 0.75, \
            f"similarity_score for different shapes must be < 0.75, got {p['similarity_score']}"
