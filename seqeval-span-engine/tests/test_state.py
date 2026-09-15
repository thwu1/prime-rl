
import json
import os
import re
import subprocess
import tempfile
import warnings

import pytest
import numpy as np
from seqeval.scheme import (
    IOB1, IOB2, IOE1, IOE2, IOBES, BILOU,
    Tokens, Entities, auto_detect
)
from seqeval.metrics.sequence_labeling import get_entities
from seqeval.metrics.v1 import precision_recall_fscore_support as prfs_strict
from seqeval.metrics.sequence_labeling import (
    precision_recall_fscore_support as prfs_default,
)

SCHEME_MAP = {
    'IOB1': IOB1, 'IOB2': IOB2, 'IOE1': IOE1, 'IOE2': IOE2,
    'IOBES': IOBES, 'BILOU': BILOU,
}

TOL = 1e-6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_tool(config):
    """Run the student tool with the given config dict and return parsed JSON."""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False, dir='/tmp'
    ) as f:
        json.dump(config, f)
        input_path = f.name
    try:
        result = subprocess.run(
            ['python3', '/app/span_eval.py', input_path],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"Tool exited with code {result.returncode}.\n"
            f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
        )
        return json.loads(result.stdout)
    finally:
        os.unlink(input_path)


def run_tool_expect_error(config):
    """Run tool expecting non-zero exit code (ValueError)."""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False, dir='/tmp'
    ) as f:
        json.dump(config, f)
        input_path = f.name
    try:
        result = subprocess.run(
            ['python3', '/app/span_eval.py', input_path],
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode
    finally:
        os.unlink(input_path)


def ref_entities_strict(sequences, scheme_name, suffix=False, delimiter='-'):
    """Get expected entities using seqeval strict mode."""
    scheme_cls = SCHEME_MAP[scheme_name]
    result = {}
    for sent_id, tags in enumerate(sequences):
        if not tags:
            continue
        tokens = Tokens(tags, scheme_cls, suffix=suffix, delimiter=delimiter,
                        sent_id=sent_id)
        for entity in tokens.entities:
            result.setdefault(entity.tag, []).append(
                [entity.sent_id, entity.start, entity.end]
            )
    for k in result:
        result[k].sort()
    return result


def ref_entities_default(sequences, suffix=False):
    """Get expected entities using seqeval default mode, per-sentence."""
    result = {}
    for sent_id, tags in enumerate(sequences):
        if not tags:
            continue
        for type_name, start, end_incl in get_entities(tags, suffix):
            result.setdefault(type_name, []).append(
                [sent_id, start, end_incl + 1]
            )
    for k in result:
        result[k].sort()
    return result


def ref_metrics_strict(y_true, y_pred, scheme_name, suffix=False):
    """Compute expected metrics using seqeval strict mode."""
    scheme_cls = SCHEME_MAP[scheme_name]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p, r, f, s = prfs_strict(
            y_true, y_pred, average=None, scheme=scheme_cls,
            suffix=suffix, zero_division=0,
        )
        mp, mr, mf, ms = prfs_strict(
            y_true, y_pred, average='micro', scheme=scheme_cls,
            suffix=suffix, zero_division=0,
        )
        ap, ar, af, a_s = prfs_strict(
            y_true, y_pred, average='macro', scheme=scheme_cls,
            suffix=suffix, zero_division=0,
        )
        wp, wr, wf, ws = prfs_strict(
            y_true, y_pred, average='weighted', scheme=scheme_cls,
            suffix=suffix, zero_division=0,
        )
    entities_t = Entities(y_true, scheme_cls, suffix)
    entities_p = Entities(y_pred, scheme_cls, suffix)
    types = sorted(entities_t.unique_tags | entities_p.unique_tags)

    per_type = {}
    for i, t in enumerate(types):
        per_type[t] = {
            'precision': float(p[i]), 'recall': float(r[i]),
            'f1': float(f[i]), 'support': int(s[i]),
        }
    return {
        'per_type': per_type,
        'micro_avg': _avg_dict(mp, mr, mf, ms),
        'macro_avg': _avg_dict(ap, ar, af, a_s),
        'weighted_avg': _avg_dict(wp, wr, wf, ws),
    }


def ref_metrics_default(y_true, y_pred, suffix=False):
    """Compute expected metrics using seqeval default mode."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p, r, f, s = prfs_default(
            y_true, y_pred, average=None, suffix=suffix, zero_division=0,
        )
        mp, mr, mf, ms = prfs_default(
            y_true, y_pred, average='micro', suffix=suffix, zero_division=0,
        )
        ap, ar, af, a_s = prfs_default(
            y_true, y_pred, average='macro', suffix=suffix, zero_division=0,
        )
        wp, wr, wf, ws = prfs_default(
            y_true, y_pred, average='weighted', suffix=suffix, zero_division=0,
        )
    all_true = get_entities(y_true, suffix)
    all_pred = get_entities(y_pred, suffix)
    types = sorted(
        set(t for t, _, _ in all_true) | set(t for t, _, _ in all_pred)
    )
    per_type = {}
    for i, t in enumerate(types):
        per_type[t] = {
            'precision': float(p[i]), 'recall': float(r[i]),
            'f1': float(f[i]), 'support': int(s[i]),
        }
    return {
        'per_type': per_type,
        'micro_avg': _avg_dict(mp, mr, mf, ms),
        'macro_avg': _avg_dict(ap, ar, af, a_s),
        'weighted_avg': _avg_dict(wp, wr, wf, ws),
    }


def _avg_dict(p, r, f, s):
    return {
        'precision': float(p), 'recall': float(r),
        'f1': float(f), 'support': int(s),
    }


def assert_metrics_match(actual, expected):
    """Assert that metric dicts match within tolerance."""
    assert set(actual['per_type'].keys()) == set(expected['per_type'].keys()), (
        f"Type keys differ: {sorted(actual['per_type'])} vs "
        f"{sorted(expected['per_type'])}"
    )
    for t in expected['per_type']:
        for k in ('precision', 'recall', 'f1'):
            assert abs(actual['per_type'][t][k] - expected['per_type'][t][k]) < TOL, (
                f"per_type[{t}][{k}]: got {actual['per_type'][t][k]}, "
                f"expected {expected['per_type'][t][k]}"
            )
        assert actual['per_type'][t]['support'] == expected['per_type'][t]['support']

    for avg_key in ('micro_avg', 'macro_avg', 'weighted_avg'):
        for k in ('precision', 'recall', 'f1'):
            assert abs(actual[avg_key][k] - expected[avg_key][k]) < TOL, (
                f"{avg_key}[{k}]: got {actual[avg_key][k]}, "
                f"expected {expected[avg_key][k]}"
            )
        assert actual[avg_key]['support'] == expected[avg_key]['support']


def assert_entities_match(actual, expected):
    """Assert that entity dicts match."""
    assert set(actual.keys()) == set(expected.keys()), (
        f"Entity type keys differ: {sorted(actual.keys())} vs "
        f"{sorted(expected.keys())}"
    )
    for t in expected:
        a_sorted = sorted(tuple(e) for e in actual[t])
        e_sorted = sorted(tuple(e) for e in expected[t])
        assert a_sorted == e_sorted, (
            f"Entities[{t}]: got {a_sorted}, expected {e_sorted}"
        )


# ===========================================================================
# Test: IOB2 Strict Mode
# ===========================================================================

class TestIOB2Strict:
    def test_basic_entity_extraction_and_metrics(self):
        y_true = [['O', 'B-PER', 'I-PER', 'O', 'B-LOC']]
        y_pred = [['O', 'B-PER', 'O', 'O', 'B-LOC']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_m = ref_metrics_strict(y_true, y_pred, 'IOB2')
        assert_metrics_match(result, expected_m)
        expected_e = ref_entities_strict(y_true, 'IOB2')
        assert_entities_match(result['entities_true'], expected_e)

    def test_i_without_b_yields_no_entity(self):
        """In IOB2 strict, I without preceding B forms no entity."""
        y_true = [['I-PER', 'I-PER', 'O']]
        y_pred = [['B-PER', 'I-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['entities_true'] == {}
        assert 'PER' in result['entities_pred']
        assert result['entities_pred']['PER'] == [[0, 0, 2]]

    def test_consecutive_b_creates_separate_entities(self):
        y_true = [['B-PER', 'B-PER', 'B-ORG']]
        y_pred = [['B-PER', 'B-PER', 'B-ORG']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_m = ref_metrics_strict(y_true, y_pred, 'IOB2')
        assert_metrics_match(result, expected_m)
        assert result['micro_avg']['f1'] == pytest.approx(1.0)

    def test_b_per_then_i_org_splits(self):
        """B-PER followed by I-ORG: PER entity of length 1, I-ORG orphaned."""
        y_true = [['B-PER', 'I-ORG', 'O']]
        y_pred = [['B-PER', 'I-ORG', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOB2')
        assert_entities_match(result['entities_true'], expected_e)
        # PER entity from B-PER only (length 1), I-ORG orphaned
        assert result['entities_true'] == {'PER': [[0, 0, 1]]}

    def test_i_after_o_orphaned_strict(self):
        """I-PER after O must NOT create entity in IOB2 strict."""
        y_true = [['O', 'I-PER', 'I-PER', 'O']]
        y_pred = [['O', 'I-PER', 'I-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        # No valid entities in IOB2 strict — I without B is orphaned
        assert result['entities_true'] == {}
        assert result['entities_pred'] == {}

    def test_i_diff_type_after_b_orphaned(self):
        """I-ORG after B-PER: PER(0,1) entity, I-ORG orphaned."""
        y_true = [['B-PER', 'I-ORG', 'I-ORG', 'O']]
        y_pred = [['B-PER', 'I-ORG', 'I-ORG', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOB2')
        assert_entities_match(result['entities_true'], expected_e)
        assert result['entities_true'] == {'PER': [[0, 0, 1]]}


# ===========================================================================
# Test: IOB1 Strict Mode
# ===========================================================================

class TestIOB1Strict:
    def test_i_starts_entity_after_o(self):
        """In IOB1, I after O starts an entity."""
        y_true = [['I-PER', 'I-PER', 'O']]
        y_pred = [['I-PER', 'I-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB1', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOB1')
        assert_entities_match(result['entities_true'], expected_e)
        # Should be a single PER entity [0, 0, 2]
        assert result['entities_true'] == {'PER': [[0, 0, 2]]}
        assert result['micro_avg']['f1'] == pytest.approx(1.0)

    def test_b_disambiguates_same_type(self):
        """B separates consecutive same-type entities in IOB1."""
        y_true = [['I-PER', 'B-PER', 'O']]
        y_pred = [['I-PER', 'I-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB1', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e_true = ref_entities_strict(y_true, 'IOB1')
        expected_e_pred = ref_entities_strict(y_pred, 'IOB1')
        assert_entities_match(result['entities_true'], expected_e_true)
        assert_entities_match(result['entities_pred'], expected_e_pred)
        # y_true: two PER entities, y_pred: one PER entity
        assert len(result['entities_true']['PER']) == 2
        assert len(result['entities_pred']['PER']) == 1

    def test_b_alone_after_o_not_entity(self):
        """B-PER after O does NOT start an entity in IOB1."""
        y_true = [['B-PER']]
        y_pred = [['B-PER']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB1', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['entities_true'] == {}
        assert result['entities_pred'] == {}

    def test_metrics_against_reference(self):
        y_true = [['I-PER', 'I-PER', 'O', 'I-LOC']]
        y_pred = [['I-PER', 'B-PER', 'O', 'I-LOC']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB1', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_m = ref_metrics_strict(y_true, y_pred, 'IOB1')
        assert_metrics_match(result, expected_m)

    def test_i_diff_type_starts_new(self):
        """I-ORG after I-PER starts a new entity in IOB1."""
        y_true = [['I-PER', 'I-ORG', 'O']]
        y_pred = [['I-PER', 'I-ORG', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB1', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOB1')
        assert_entities_match(result['entities_true'], expected_e)
        assert 'PER' in result['entities_true']
        assert 'ORG' in result['entities_true']


# ===========================================================================
# Test: IOBES Strict Mode
# ===========================================================================

class TestIOBESStrict:
    def test_singleton_and_be_span(self):
        y_true = [['S-PER', 'O', 'B-LOC', 'I-LOC', 'E-LOC']]
        y_pred = [['S-PER', 'O', 'B-LOC', 'E-LOC', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOBES', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOBES')
        assert_entities_match(result['entities_true'], expected_e)
        expected_m = ref_metrics_strict(y_true, y_pred, 'IOBES')
        assert_metrics_match(result, expected_m)

    def test_b_without_e_yields_nothing(self):
        """B-PER without matching E-PER yields no entity in IOBES strict."""
        y_true = [['B-PER', 'O']]
        y_pred = [['B-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOBES', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['entities_true'] == {}

    def test_consecutive_singletons(self):
        y_true = [['S-PER', 'S-ORG', 'S-PER']]
        y_pred = [['S-PER', 'S-ORG', 'S-PER']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOBES', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['micro_avg']['f1'] == pytest.approx(1.0)
        assert len(result['entities_true']['PER']) == 2
        assert len(result['entities_true']['ORG']) == 1

    def test_bie_span_with_type_mismatch(self):
        """B-PER I-PER E-ORG: type mismatch breaks the span in IOBES."""
        y_true = [['B-PER', 'I-PER', 'E-ORG']]
        y_pred = [['B-PER', 'I-PER', 'E-ORG']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOBES', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOBES')
        assert_entities_match(result['entities_true'], expected_e)


# ===========================================================================
# Test: BILOU Strict Mode
# ===========================================================================

class TestBILOUStrict:
    def test_basic(self):
        y_true = [['U-PER', 'O', 'B-LOC', 'I-LOC', 'L-LOC']]
        y_pred = [['U-PER', 'O', 'B-LOC', 'L-LOC', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'BILOU', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'BILOU')
        assert_entities_match(result['entities_true'], expected_e)
        expected_m = ref_metrics_strict(y_true, y_pred, 'BILOU')
        assert_metrics_match(result, expected_m)

    def test_unit_entities(self):
        y_true = [['U-PER', 'U-ORG']]
        y_pred = [['U-PER', 'U-ORG']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'BILOU', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['micro_avg']['f1'] == pytest.approx(1.0)
        assert result['entities_true'] == {
            'ORG': [[0, 1, 2]], 'PER': [[0, 0, 1]]
        }

    def test_b_without_l_yields_nothing(self):
        """B-PER without matching L-PER yields no entity in BILOU strict."""
        y_true = [['B-PER', 'O']]
        y_pred = [['B-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'BILOU', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['entities_true'] == {}


# ===========================================================================
# Test: IOE2 Strict Mode
# ===========================================================================

class TestIOE2Strict:
    def test_basic(self):
        y_true = [['I-PER', 'E-PER', 'O', 'E-LOC']]
        y_pred = [['I-PER', 'E-PER', 'O', 'E-LOC']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOE2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOE2')
        assert_entities_match(result['entities_true'], expected_e)
        assert result['micro_avg']['f1'] == pytest.approx(1.0)

    def test_consecutive_e_creates_separate(self):
        y_true = [['E-PER', 'E-PER']]
        y_pred = [['E-PER', 'E-PER']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOE2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOE2')
        assert_entities_match(result['entities_true'], expected_e)
        assert len(result['entities_true']['PER']) == 2


# ===========================================================================
# Test: IOE1 Strict Mode
# ===========================================================================

class TestIOE1Strict:
    def test_basic(self):
        y_true = [['I-PER', 'I-PER', 'O']]
        y_pred = [['I-PER', 'I-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOE1', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOE1')
        assert_entities_match(result['entities_true'], expected_e)
        assert result['micro_avg']['f1'] == pytest.approx(1.0)

    def test_diff_type_splits(self):
        """Different type I after I starts new entity in IOE1."""
        y_true = [['I-PER', 'I-ORG', 'O']]
        y_pred = [['I-PER', 'I-ORG', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOE1', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOE1')
        assert_entities_match(result['entities_true'], expected_e)
        assert 'PER' in result['entities_true']
        assert 'ORG' in result['entities_true']

    def test_e_disambiguates_same_type(self):
        """E marks end of same-type entity before next same-type in IOE1."""
        y_true = [['I-PER', 'E-PER', 'I-PER', 'O']]
        y_pred = [['I-PER', 'I-PER', 'I-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOE1', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e_true = ref_entities_strict(y_true, 'IOE1')
        expected_e_pred = ref_entities_strict(y_pred, 'IOE1')
        assert_entities_match(result['entities_true'], expected_e_true)
        assert_entities_match(result['entities_pred'], expected_e_pred)
        # y_true has 2 PER entities (E disambiguates), y_pred has 1
        assert len(result['entities_true']['PER']) == 2
        assert len(result['entities_pred']['PER']) == 1


# ===========================================================================
# Test: Default (conlleval-compatible) Mode
# ===========================================================================

class TestDefaultMode:
    def test_seqeval_readme_example(self):
        """The seqeval README example."""
        y_true = [
            ['O', 'O', 'O', 'B-MISC', 'I-MISC', 'I-MISC', 'O'],
            ['B-PER', 'I-PER', 'O'],
        ]
        y_pred = [
            ['O', 'O', 'B-MISC', 'I-MISC', 'I-MISC', 'I-MISC', 'O'],
            ['B-PER', 'I-PER', 'O'],
        ]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'default',
        }
        result = run_tool(config)
        expected_m = ref_metrics_default(y_true, y_pred)
        assert_metrics_match(result, expected_m)

    def test_i_after_o_creates_entity(self):
        """In default mode, I after O starts a new entity."""
        y_true = [['I-NP', 'I-NP', 'O']]
        y_pred = [['B-NP', 'I-NP', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'default',
        }
        result = run_tool(config)
        # Both should match in default mode
        assert result['micro_avg']['f1'] == pytest.approx(1.0)

    def test_default_vs_strict_key_difference(self):
        """The canonical example showing default vs strict difference."""
        y_true = [['B-NP', 'I-NP', 'O']]
        y_pred = [['I-NP', 'I-NP', 'O']]

        # Default mode: both have NP entity, F1=1.0
        config_d = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'default',
        }
        result_d = run_tool(config_d)
        assert result_d['micro_avg']['f1'] == pytest.approx(1.0)

        # Strict IOB2: y_pred has no valid entities, F1=0.0
        config_s = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result_s = run_tool(config_s)
        assert result_s['micro_avg']['f1'] == pytest.approx(0.0)

    def test_default_entity_extraction(self):
        y_true = [['B-PER', 'I-PER', 'O', 'B-LOC']]
        y_pred = [['B-PER', 'I-PER', 'O', 'B-LOC']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'default',
        }
        result = run_tool(config)
        expected_e = ref_entities_default(y_true)
        assert_entities_match(result['entities_true'], expected_e)

    def test_default_mode_iobes_tags(self):
        """Default mode should handle S and E prefixes via conlleval logic."""
        y_true = [['S-PER', 'O', 'B-LOC', 'E-LOC']]
        y_pred = [['S-PER', 'O', 'B-LOC', 'E-LOC']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOBES', 'mode': 'default',
        }
        result = run_tool(config)
        expected_m = ref_metrics_default(y_true, y_pred)
        assert_metrics_match(result, expected_m)

    def test_default_type_change_between_i_tags(self):
        """I-PER followed by I-LOC in default mode: two separate entities."""
        y_true = [['I-PER', 'I-LOC', 'O']]
        y_pred = [['I-PER', 'I-LOC', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'default',
        }
        result = run_tool(config)
        expected_e = ref_entities_default(y_true)
        assert_entities_match(result['entities_true'], expected_e)
        assert 'PER' in result['entities_true']
        assert 'LOC' in result['entities_true']


# ===========================================================================
# Test: Auto-Detection
# ===========================================================================

class TestAutoDetect:
    def test_iob2_detection(self):
        y_true = [['B-PER', 'I-PER', 'O']]
        y_pred = [['B-PER', 'I-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'auto', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['detected_scheme'] == 'IOB2'
        assert result['micro_avg']['f1'] == pytest.approx(1.0)

    def test_iobes_detection(self):
        y_true = [['S-PER', 'B-LOC', 'E-LOC']]
        y_pred = [['S-PER', 'B-LOC', 'E-LOC']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'auto', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['detected_scheme'] == 'IOBES'

    def test_bilou_detection(self):
        y_true = [['U-PER', 'B-LOC', 'L-LOC']]
        y_pred = [['U-PER', 'B-LOC', 'L-LOC']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'auto', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['detected_scheme'] == 'BILOU'

    def test_ioe2_detection(self):
        y_true = [['I-PER', 'E-PER', 'O']]
        y_pred = [['I-PER', 'E-PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'auto', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['detected_scheme'] == 'IOE2'

    def test_unrecognizable_prefix_raises(self):
        """Unknown prefix combinations should raise ValueError."""
        config = {
            'y_true': [['X-PER']],
            'y_pred': [['X-PER']],
            'scheme': 'auto', 'mode': 'strict',
        }
        rc = run_tool_expect_error(config)
        assert rc != 0


# ===========================================================================
# Test: Suffix Mode
# ===========================================================================

class TestSuffixMode:
    def test_suffix_iob2_strict(self):
        y_true = [['PER-B', 'PER-I', 'O']]
        y_pred = [['PER-B', 'PER-I', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
            'suffix': True,
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOB2', suffix=True)
        assert_entities_match(result['entities_true'], expected_e)
        assert result['micro_avg']['f1'] == pytest.approx(1.0)

    def test_suffix_default_mode(self):
        y_true = [['PER-B', 'PER-I', 'O', 'LOC-B']]
        y_pred = [['PER-B', 'O', 'O', 'LOC-B']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'default',
            'suffix': True,
        }
        result = run_tool(config)
        expected_m = ref_metrics_default(y_true, y_pred, suffix=True)
        assert_metrics_match(result, expected_m)


# ===========================================================================
# Test: Multi-Sentence with Multiple Entity Types
# ===========================================================================

class TestMultiSentence:
    def test_multi_sentence_multi_type(self):
        y_true = [
            ['B-PER', 'I-PER', 'O', 'B-LOC'],
            ['O', 'B-ORG', 'I-ORG', 'O'],
            ['B-PER', 'O', 'B-LOC', 'I-LOC'],
        ]
        y_pred = [
            ['B-PER', 'I-PER', 'O', 'B-LOC'],
            ['O', 'B-ORG', 'O', 'O'],
            ['O', 'O', 'B-LOC', 'I-LOC'],
        ]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_m = ref_metrics_strict(y_true, y_pred, 'IOB2')
        assert_metrics_match(result, expected_m)
        expected_e = ref_entities_strict(y_true, 'IOB2')
        assert_entities_match(result['entities_true'], expected_e)

    def test_complex_realistic(self):
        """Realistic NER evaluation with many types and sentences."""
        y_true = [
            ['O', 'B-PER', 'I-PER', 'O', 'O', 'B-ORG', 'I-ORG', 'I-ORG', 'O'],
            ['B-LOC', 'I-LOC', 'O', 'B-PER', 'O'],
            ['O', 'O', 'B-MISC', 'O', 'B-PER', 'I-PER', 'O'],
        ]
        y_pred = [
            ['O', 'B-PER', 'I-PER', 'O', 'O', 'B-ORG', 'I-ORG', 'O', 'O'],
            ['B-LOC', 'I-LOC', 'O', 'B-PER', 'O'],
            ['O', 'B-ORG', 'B-MISC', 'O', 'B-PER', 'I-PER', 'O'],
        ]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_m = ref_metrics_strict(y_true, y_pred, 'IOB2')
        assert_metrics_match(result, expected_m)


# ===========================================================================
# Test: Edge Cases
# ===========================================================================

class TestEdgeCases:
    def test_empty_sequences(self):
        y_true = [[]]
        y_pred = [[]]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['entities_true'] == {}
        assert result['entities_pred'] == {}
        assert result['per_type'] == {}

    def test_all_outside(self):
        y_true = [['O', 'O', 'O']]
        y_pred = [['O', 'O', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        assert result['entities_true'] == {}
        assert result['per_type'] == {}

    def test_tagless_tokens_use_underscore(self):
        """Bare prefix tokens (like 'B' without type) should use type '_'."""
        y_true = [['B', 'I', 'O']]
        y_pred = [['B', 'I', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOB2')
        assert_entities_match(result['entities_true'], expected_e)
        assert '_' in result['entities_true']

    def test_invalid_prefix_strict_raises(self):
        """Invalid prefix E in IOB2 strict mode should cause error."""
        config = {
            'y_true': [['B-PER', 'E-PER']],
            'y_pred': [['B-PER', 'I-PER']],
            'scheme': 'IOB2', 'mode': 'strict',
        }
        rc = run_tool_expect_error(config)
        assert rc != 0, "Should have raised error for invalid prefix E in IOB2"

    def test_weighted_avg_with_zero_support(self):
        """Entity type in pred but not in true has support=0."""
        y_true = [['B-PER', 'O', 'O']]
        y_pred = [['O', 'O', 'B-ORG']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
        }
        result = run_tool(config)
        expected_m = ref_metrics_strict(y_true, y_pred, 'IOB2')
        assert_metrics_match(result, expected_m)
        # ORG has support=0 (only in pred), PER has support=1 (only in true)
        assert result['per_type']['ORG']['support'] == 0
        assert result['per_type']['PER']['support'] == 1

    def test_custom_delimiter(self):
        """Test with non-default delimiter."""
        y_true = [['B_PER', 'I_PER', 'O']]
        y_pred = [['B_PER', 'I_PER', 'O']]
        config = {
            'y_true': y_true, 'y_pred': y_pred,
            'scheme': 'IOB2', 'mode': 'strict',
            'delimiter': '_',
        }
        result = run_tool(config)
        expected_e = ref_entities_strict(y_true, 'IOB2', delimiter='_')
        assert_entities_match(result['entities_true'], expected_e)
        assert result['micro_avg']['f1'] == pytest.approx(1.0)


# ===========================================================================
# Test: Cross-Validation Against conlleval.pl
# ===========================================================================

class TestConllevalCrossValidation:
    """Cross-validate default mode output against the reference conlleval.pl."""

    def _make_conll(self, y_true, y_pred):
        """Write y_true/y_pred to a temp CoNLL file."""
        path = '/tmp/_cross_val.conll'
        with open(path, 'w') as f:
            for tags_t, tags_p in zip(y_true, y_pred):
                for j, (t, p) in enumerate(zip(tags_t, tags_p)):
                    f.write(f'w{j} {t} {p}\n')
                f.write('\n')
        return path

    def _run_conlleval(self, path):
        """Run conlleval.pl and parse output counts."""
        with open(path) as f:
            data = f.read()
        r = subprocess.run(
            ['perl', '/app/conlleval.pl'], input=data,
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"conlleval.pl error: {r.stderr}"
        m = re.search(
            r'with (\d+) phrases; found: (\d+) phrases; correct: (\d+)',
            r.stdout,
        )
        assert m is not None, f"Could not parse conlleval output: {r.stdout}"
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    def _tool_counts(self, result):
        """Extract gold/found/correct counts from tool result."""
        gold = sum(len(v) for v in result.get('entities_true', {}).values())
        found = sum(len(v) for v in result.get('entities_pred', {}).values())
        correct = 0
        for etype in set(result.get('entities_true', {})) & set(result.get('entities_pred', {})):
            true_set = {tuple(e) for e in result['entities_true'][etype]}
            pred_set = {tuple(e) for e in result['entities_pred'][etype]}
            correct += len(true_set & pred_set)
        return gold, found, correct

    def test_basic_iob2_crossval(self):
        y_true = [['O', 'B-PER', 'I-PER', 'O', 'B-LOC'], ['B-ORG', 'I-ORG', 'O']]
        y_pred = [['O', 'B-PER', 'O', 'O', 'B-LOC'], ['B-ORG', 'I-ORG', 'O']]
        config = {'y_true': y_true, 'y_pred': y_pred, 'scheme': 'IOB2', 'mode': 'default'}
        result = run_tool(config)
        p = self._make_conll(y_true, y_pred)
        try:
            ce_gold, ce_found, ce_correct = self._run_conlleval(p)
            t_gold, t_found, t_correct = self._tool_counts(result)
            assert t_gold == ce_gold, f"Gold: tool={t_gold}, conlleval={ce_gold}"
            assert t_found == ce_found, f"Found: tool={t_found}, conlleval={ce_found}"
            assert t_correct == ce_correct, f"Correct: tool={t_correct}, conlleval={ce_correct}"
        finally:
            os.unlink(p)

    def test_i_after_o_crossval(self):
        """I-after-O in default mode must match conlleval.pl entity counting."""
        y_true = [['I-NP', 'I-NP', 'O', 'B-NP', 'I-NP']]
        y_pred = [['I-NP', 'I-NP', 'O', 'I-NP', 'I-NP']]
        config = {'y_true': y_true, 'y_pred': y_pred, 'scheme': 'IOB2', 'mode': 'default'}
        result = run_tool(config)
        p = self._make_conll(y_true, y_pred)
        try:
            ce_gold, ce_found, _ = self._run_conlleval(p)
            t_gold, t_found, _ = self._tool_counts(result)
            assert t_gold == ce_gold
            assert t_found == ce_found
            # Both true and pred should have 2 entities each
            assert t_gold == 2
            assert t_found == 2
        finally:
            os.unlink(p)

    def test_multi_type_crossval(self):
        y_true = [
            ['B-PER', 'I-PER', 'O', 'B-LOC', 'I-LOC', 'I-LOC'],
            ['O', 'B-ORG', 'O'],
            ['B-MISC', 'O', 'B-PER'],
        ]
        y_pred = [
            ['B-PER', 'I-PER', 'O', 'B-LOC', 'O', 'O'],
            ['O', 'B-ORG', 'O'],
            ['B-MISC', 'O', 'O'],
        ]
        config = {'y_true': y_true, 'y_pred': y_pred, 'scheme': 'IOB2', 'mode': 'default'}
        result = run_tool(config)
        p = self._make_conll(y_true, y_pred)
        try:
            ce_gold, ce_found, ce_correct = self._run_conlleval(p)
            t_gold, t_found, t_correct = self._tool_counts(result)
            assert t_gold == ce_gold
            assert t_found == ce_found
            assert t_correct == ce_correct
            # Cross-validate metrics
            if ce_found > 0:
                assert abs(result['micro_avg']['precision'] - ce_correct / ce_found) < TOL
            if ce_gold > 0:
                assert abs(result['micro_avg']['recall'] - ce_correct / ce_gold) < TOL
        finally:
            os.unlink(p)

    def test_type_change_between_i_crossval(self):
        """Type change between I tags must match conlleval.pl."""
        y_true = [['I-PER', 'I-LOC', 'O']]
        y_pred = [['I-PER', 'I-LOC', 'O']]
        config = {'y_true': y_true, 'y_pred': y_pred, 'scheme': 'IOB2', 'mode': 'default'}
        result = run_tool(config)
        p = self._make_conll(y_true, y_pred)
        try:
            ce_gold, ce_found, _ = self._run_conlleval(p)
            t_gold = sum(len(v) for v in result['entities_true'].values())
            assert t_gold == ce_gold
            assert t_gold == 2  # type change creates two entities
        finally:
            os.unlink(p)

    def test_iobes_default_crossval(self):
        """IOBES tags processed in default mode should match conlleval.pl."""
        y_true = [['S-PER', 'O', 'B-LOC', 'I-LOC', 'E-LOC', 'O']]
        y_pred = [['S-PER', 'O', 'B-LOC', 'E-LOC', 'O', 'O']]
        config = {'y_true': y_true, 'y_pred': y_pred, 'scheme': 'IOBES', 'mode': 'default'}
        result = run_tool(config)
        p = self._make_conll(y_true, y_pred)
        try:
            ce_gold, ce_found, ce_correct = self._run_conlleval(p)
            t_gold, t_found, t_correct = self._tool_counts(result)
            assert t_gold == ce_gold
            assert t_found == ce_found
            assert t_correct == ce_correct
        finally:
            os.unlink(p)


# ===========================================================================
# Test: Sample CoNLL Data Cross-Validation
# ===========================================================================

class TestSampleData:
    """Verify tool output against the provided sample.conll / sample.eval."""

    def test_sample_conll_entity_counts(self):
        """Parse sample.conll, run tool in default mode, compare vs sample.eval."""
        # Parse sample.conll
        y_true_all = []
        y_pred_all = []
        cur_t = []
        cur_p = []
        with open('/app/data/sample.conll') as f:
            for line in f:
                line = line.strip()
                if not line:
                    if cur_t:
                        y_true_all.append(cur_t)
                        y_pred_all.append(cur_p)
                        cur_t, cur_p = [], []
                    continue
                parts = line.split()
                cur_t.append(parts[1])
                cur_p.append(parts[2])
        if cur_t:
            y_true_all.append(cur_t)
            y_pred_all.append(cur_p)

        # Run tool in default mode
        config = {
            'y_true': y_true_all, 'y_pred': y_pred_all,
            'scheme': 'IOB2', 'mode': 'default',
        }
        result = run_tool(config)

        # Parse expected conlleval output
        with open('/app/data/sample.eval') as f:
            eval_output = f.read()
        m = re.search(
            r'with (\d+) phrases; found: (\d+) phrases; correct: (\d+)',
            eval_output,
        )
        exp_gold = int(m.group(1))
        exp_found = int(m.group(2))
        exp_correct = int(m.group(3))

        # Compare entity counts
        tool_gold = sum(len(v) for v in result['entities_true'].values())
        tool_found = sum(len(v) for v in result['entities_pred'].values())
        tool_correct = 0
        for etype in set(result.get('entities_true', {})) & set(result.get('entities_pred', {})):
            true_set = {tuple(e) for e in result['entities_true'][etype]}
            pred_set = {tuple(e) for e in result['entities_pred'][etype]}
            tool_correct += len(true_set & pred_set)

        assert tool_gold == exp_gold, f"Gold: got {tool_gold}, expected {exp_gold}"
        assert tool_found == exp_found, f"Found: got {tool_found}, expected {exp_found}"
        assert tool_correct == exp_correct, f"Correct: got {tool_correct}, expected {exp_correct}"

    def test_sample_conll_metrics(self):
        """Verify micro-avg metrics from sample.conll match conlleval output."""
        # Parse sample.conll
        y_true_all = []
        y_pred_all = []
        cur_t = []
        cur_p = []
        with open('/app/data/sample.conll') as f:
            for line in f:
                line = line.strip()
                if not line:
                    if cur_t:
                        y_true_all.append(cur_t)
                        y_pred_all.append(cur_p)
                        cur_t, cur_p = [], []
                    continue
                parts = line.split()
                cur_t.append(parts[1])
                cur_p.append(parts[2])
        if cur_t:
            y_true_all.append(cur_t)
            y_pred_all.append(cur_p)

        config = {
            'y_true': y_true_all, 'y_pred': y_pred_all,
            'scheme': 'IOB2', 'mode': 'default',
        }
        result = run_tool(config)

        # Parse precision/recall from sample.eval
        with open('/app/data/sample.eval') as f:
            eval_output = f.read()
        pm = re.search(r'precision:\s+([\d.]+)%', eval_output)
        rm = re.search(r'recall:\s+([\d.]+)%', eval_output)
        expected_p = float(pm.group(1)) / 100.0
        expected_r = float(rm.group(1)) / 100.0

        assert abs(result['micro_avg']['precision'] - expected_p) < 0.005
        assert abs(result['micro_avg']['recall'] - expected_r) < 0.005
