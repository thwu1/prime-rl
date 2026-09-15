
import json
import os
import pytest

RESULTS_FILE = '/tmp/crdt_test_results.json'


@pytest.fixture(scope='session')
def test_results():
    """Load test results produced by the TypeScript test runner."""
    if not os.path.exists(RESULTS_FILE):
        pytest.fail(
            "Test results file not found at {}. "
            "TypeScript compilation or runtime may have failed.".format(RESULTS_FILE)
        )
    with open(RESULTS_FILE) as f:
        content = f.read().strip()
        if not content:
            pytest.fail("Test results file is empty")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            pytest.fail("Invalid JSON in results file: {}".format(e))


def _get(results, name):
    matches = [r for r in results if r['name'] == name]
    if not matches:
        pytest.fail("Test '{}' not found in results".format(name))
    return matches[0]


class TestEncodingRoundtrips:
    def test_varuint_roundtrip(self, test_results):
        r = _get(test_results, 'varuint_roundtrip')
        assert r['passed'], r.get('error', '')

    def test_varstring_roundtrip(self, test_results):
        r = _get(test_results, 'varstring_roundtrip')
        assert r['passed'], r.get('error', '')


class TestUpdateParsing:
    def test_simple_update_roundtrip(self, test_results):
        r = _get(test_results, 'simple_update_roundtrip')
        assert r['passed'], r.get('error', '')

    def test_update_with_origin_only(self, test_results):
        r = _get(test_results, 'update_with_origin_only')
        assert r['passed'], r.get('error', '')

    def test_update_with_both_origins(self, test_results):
        r = _get(test_results, 'update_with_both_origins')
        assert r['passed'], r.get('error', '')

    def test_update_with_right_origin_only(self, test_results):
        r = _get(test_results, 'update_with_right_origin_only')
        assert r['passed'], r.get('error', '')

    def test_multi_client_descending_order(self, test_results):
        r = _get(test_results, 'multi_client_descending_order')
        assert r['passed'], r.get('error', '')

    def test_multiple_structs_per_client(self, test_results):
        r = _get(test_results, 'multiple_structs_per_client')
        assert r['passed'], r.get('error', '')

    def test_delete_set_roundtrip(self, test_results):
        r = _get(test_results, 'delete_set_roundtrip')
        assert r['passed'], r.get('error', '')

    def test_gc_and_deleted_content_types(self, test_results):
        r = _get(test_results, 'gc_and_deleted_content_types')
        assert r['passed'], r.get('error', '')


class TestDeleteSetMerge:
    def test_overlapping(self, test_results):
        r = _get(test_results, 'delete_range_merge_overlapping')
        assert r['passed'], r.get('error', '')

    def test_adjacent(self, test_results):
        r = _get(test_results, 'delete_range_merge_adjacent')
        assert r['passed'], r.get('error', '')

    def test_disjoint(self, test_results):
        r = _get(test_results, 'delete_range_merge_disjoint')
        assert r['passed'], r.get('error', '')

    def test_complex(self, test_results):
        r = _get(test_results, 'delete_range_merge_complex')
        assert r['passed'], r.get('error', '')


class TestMergeUpdates:
    def test_non_overlapping_clients(self, test_results):
        r = _get(test_results, 'merge_non_overlapping_clients')
        assert r['passed'], r.get('error', '')

    def test_same_client_sequential(self, test_results):
        r = _get(test_results, 'merge_same_client_sequential')
        assert r['passed'], r.get('error', '')

    def test_duplicate_structs(self, test_results):
        r = _get(test_results, 'merge_duplicate_structs')
        assert r['passed'], r.get('error', '')

    def test_with_delete_sets(self, test_results):
        r = _get(test_results, 'merge_with_delete_sets')
        assert r['passed'], r.get('error', '')

    def test_three_updates(self, test_results):
        r = _get(test_results, 'merge_three_updates')
        assert r['passed'], r.get('error', '')

    def test_idempotent(self, test_results):
        r = _get(test_results, 'merge_idempotent')
        assert r['passed'], r.get('error', '')

    def test_empty_updates(self, test_results):
        r = _get(test_results, 'merge_empty_updates')
        assert r['passed'], r.get('error', '')

    def test_preserves_all_content_types(self, test_results):
        r = _get(test_results, 'merge_preserves_all_content_types')
        assert r['passed'], r.get('error', '')


class TestStateVector:
    def test_sv_single_client(self, test_results):
        r = _get(test_results, 'sv_single_client')
        assert r['passed'], r.get('error', '')

    def test_sv_multi_client(self, test_results):
        r = _get(test_results, 'sv_multi_client')
        assert r['passed'], r.get('error', '')

    def test_sv_encode_decode_roundtrip(self, test_results):
        r = _get(test_results, 'sv_encode_decode_roundtrip')
        assert r['passed'], r.get('error', '')

    def test_diff_missing_client(self, test_results):
        r = _get(test_results, 'diff_missing_client')
        assert r['passed'], r.get('error', '')

    def test_diff_partial_overlap(self, test_results):
        r = _get(test_results, 'diff_partial_overlap')
        assert r['passed'], r.get('error', '')


class TestCLI:
    def test_cli_inspect(self, test_results):
        r = _get(test_results, 'cli_inspect')
        assert r['passed'], r.get('error', '')

    def test_cli_merge_files(self, test_results):
        r = _get(test_results, 'cli_merge_files')
        assert r['passed'], r.get('error', '')

    def test_cli_state_vector(self, test_results):
        r = _get(test_results, 'cli_state_vector')
        assert r['passed'], r.get('error', '')

    def test_cli_diff(self, test_results):
        r = _get(test_results, 'cli_diff')
        assert r['passed'], r.get('error', '')


class TestOverall:
    def test_no_failures(self, test_results):
        failed = [r for r in test_results if not r['passed']]
        assert len(failed) == 0, \
            "Failed tests: {}".format(
                [(r['name'], r.get('error', '')) for r in failed]
            )
