#!/usr/bin/env python3
"""Pipeline Validator: verifies evaluation pipeline compliance with spec.md.

Programmatically checks that the pipeline implementation at /app/ conforms
to the evaluation protocol specification. Each check tests a distinct
aspect of the pipeline. Exits 0 if all pass, non-zero otherwise.
"""


import json
import math
import os
import re
import sys

sys.path.insert(0, '/app')

import numpy as np


class ValidationResult:
    def __init__(self):
        self.results = []

    def check(self, name, passed, detail=""):
        self.results.append((name, passed, detail))
        status = "PASS" if passed else "FAIL"
        msg = f"[{status}] {name}"
        if detail and not passed:
            msg += f" -- {detail}"
        print(msg)
        return passed

    def summary(self):
        total = len(self.results)
        passed = sum(1 for _, p, _ in self.results if p)
        failed = total - passed
        print(f"\n{'=' * 50}")
        print(f"Validation: {passed}/{total} checks passed, {failed} failed")
        return failed == 0


def main():
    v = ValidationResult()

    # Check 1: Range filter uses Euclidean L2 norm (not L-inf)
    from pipeline.preprocessing import filter_by_range
    # (107, 107, 0): L-inf=107 < 150, but L2=sqrt(107^2+107^2)=151.3 > 150
    r = filter_by_range([{'tx': 107.0, 'ty': 107.0, 'tz': 0.0}], 150.0)
    v.check("Range filter uses L2 norm",
            len(r) == 0,
            "Object at (107,107,0) has L2=151.3 but was not excluded")

    # Check 2: Range filter keeps objects within range
    r = filter_by_range([{'tx': 100.0, 'ty': 100.0, 'tz': 0.0}], 150.0)
    v.check("Range filter keeps objects within L2 range",
            len(r) == 1,
            "Object at (100,100,0) with L2=141.4 should be kept")

    # Check 3: Config tp_threshold_m matches spec
    from pipeline.config import load_config
    config = load_config()
    tp_thresh = config['evaluation']['tp_threshold_m']
    v.check("Config tp_threshold_m == 2.0",
            tp_thresh == 2.0,
            f"Got {tp_thresh}, spec Section 5 requires 2.0")

    # Check 4: Greedy assignment processes high-confidence first
    from pipeline.assignment import greedy_assign
    dts = [
        {'tx': 1.0, 'ty': 0.0, 'tz': 0.0, 'score': 0.3},
        {'tx': 1.2, 'ty': 0.0, 'tz': 0.0, 'score': 0.9},
    ]
    gts = [{'tx': 1.1, 'ty': 0.0, 'tz': 0.0}]
    asgn = greedy_assign(dts, gts, 2.0)
    v.check("Assignment: descending score order",
            1 in asgn and 0 not in asgn,
            "High-score detection (idx 1) should claim the match")

    # Check 5: VOC precision envelope direction
    from pipeline.metrics import compute_average_precision
    tps = np.array([False, False, True, True], dtype=bool)
    ap = compute_average_precision(tps, 2)
    v.check("VOC precision envelope applied in reverse",
            ap > 0.40,
            f"AP={ap:.4f}, correct reverse envelope should give > 0.40")

    # Check 6: Orientation error handles circular wrapping
    from pipeline.metrics import compute_orientation_error
    err = compute_orientation_error(3.1, -3.1)
    v.check("Orientation error wraps near +/-pi",
            err < 0.2,
            f"Error={err:.4f} for yaws 3.1/-3.1, expected < 0.2")

    # Check 7: CDS uses arithmetic mean of TP measures
    from pipeline.metrics import compute_composite_score
    tp_norms = {'ATE': 2.0, 'ASE': 1.0, 'AOE': math.pi}
    cds = compute_composite_score(1.0, 1.0, 0.5, math.pi / 2, tp_norms)
    v.check("CDS uses mean (value in [0,1])",
            0 <= cds <= 1.0 + 1e-6,
            f"CDS={cds:.4f}, > 1.0 indicates sum instead of mean")

    # Check 8: Makefile EVAL_NUM_RECALL_SAMPLES value
    with open('/app/Makefile') as f:
        mf = f.read()
    matches = re.findall(r'EVAL_NUM_RECALL_SAMPLES\s*[:?]?=\s*(\d+)', mf)
    wrong = [int(x) for x in matches if int(x) != 101]
    v.check("Makefile EVAL_NUM_RECALL_SAMPLES == 101",
            len(wrong) == 0,
            f"Found wrong value(s): {wrong}")

    # Check 9: Config num_recall_samples is 101 after all overrides
    num_recall = config['evaluation'].get('num_recall_samples', None)
    v.check("Effective num_recall_samples == 101",
            num_recall == 101,
            f"Got {num_recall} after config loading")

    # Check 10: Affinity thresholds match spec defaults
    expected_aff = [0.5, 1.0, 2.0, 4.0]
    v.check("Affinity thresholds match spec",
            config['evaluation']['affinity_thresholds_m'] == expected_aff,
            f"Got {config['evaluation']['affinity_thresholds_m']}")

    if v.summary():
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
