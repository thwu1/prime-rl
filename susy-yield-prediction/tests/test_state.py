"""Tests for the SUSY stop search yield prediction task.

Compares agent output at /app/results/histogram.yaml against reference
yields computed independently by /tests/reference_analysis.py.
"""

import json
import math
import os

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_reference():
    """Load reference yields produced by reference_analysis.py."""
    with open('/tmp/reference_yields.json') as f:
        return json.load(f)


def _load_agent():
    """Parse the agent's filled histogram YAML and return bin yields."""
    path = '/app/results/histogram.yaml'
    assert os.path.exists(path), f"Output file {path} not found"

    with open(path) as f:
        content = f.read()

    docs = list(yaml.safe_load_all(content))

    # Find the document containing dependent_variables
    histogram = None
    for doc in docs:
        if doc is None:
            continue
        if isinstance(doc, dict) and 'dependent_variables' in doc:
            histogram = doc
            break
        if isinstance(doc, dict):
            for v in doc.values():
                if isinstance(v, dict) and 'dependent_variables' in v:
                    histogram = v
                    break
            if histogram:
                break

    assert histogram is not None, (
        "Could not find 'dependent_variables' key in output YAML"
    )

    raw_values = histogram['dependent_variables'][0]['values']
    yields = []
    for entry in raw_values:
        if isinstance(entry, dict):
            val = entry.get('value', entry)
        else:
            val = entry
        yields.append(float(val))
    return yields


def _relative_l2(pred, ref):
    """Relative L2 distance: sqrt(sum((p-r)^2) / sum(r^2))."""
    num = sum((p - r) ** 2 for p, r in zip(pred, ref))
    den = sum(r ** 2 for r in ref)
    if den == 0:
        return float('inf')
    return math.sqrt(num / den)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_output_file_exists():
    assert os.path.exists('/app/results/histogram.yaml'), (
        "Agent must write results to /app/results/histogram.yaml"
    )


def test_bins_filled():
    """All four MET bins must contain non-negative numeric values."""
    yields = _load_agent()
    assert len(yields) == 4, f"Expected 4 bins, got {len(yields)}"
    for k, v in enumerate(yields):
        assert v is not None, f"Bin {k} is null"
        assert isinstance(v, (int, float)), f"Bin {k} not numeric: {type(v)}"
        assert v >= 0, f"Bin {k} is negative: {v}"


def test_nonzero_yield():
    """Total predicted yield must be positive (zero means analysis failed)."""
    yields = _load_agent()
    total = sum(yields)
    assert total > 0, "Total predicted yield is zero — analysis likely not implemented"


def test_relative_l2_yield():
    """Predicted yields must match reference within relative L2 < 0.10."""
    ref = _load_reference()
    pred = _load_agent()
    rel = _relative_l2(pred, ref)
    assert rel < 0.10, (
        f"Relative L2 distance on yields = {rel:.4f} (threshold 0.10). "
        f"Predicted: {pred}, Reference: {ref}"
    )


def test_shape_l2():
    """Normalized shape must match reference within relative L2 < 0.08."""
    ref = _load_reference()
    pred = _load_agent()

    pred_tot = sum(pred)
    ref_tot = sum(ref)
    assert pred_tot > 0, "Cannot compute shape with zero total yield"
    assert ref_tot > 0, "Reference total yield is zero (data issue)"

    pred_n = [p / pred_tot for p in pred]
    ref_n = [r / ref_tot for r in ref]

    shape_l2 = _relative_l2(pred_n, ref_n)
    assert shape_l2 < 0.08, (
        f"Shape L2 distance = {shape_l2:.4f} (threshold 0.08). "
        f"Pred shape: {pred_n}, Ref shape: {ref_n}"
    )
