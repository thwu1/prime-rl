#!/usr/bin/env python3

"""
Process all data streams and produce detection results.
"""

import json
import os
import sys
import numpy as np

sys.path.insert(0, '/app')

from evalue.martingales import TwoSidedNormalMixture, BetaBinomialMixture
from evalue.cusum import CusumDetector
from evalue.confseq import ConfidenceSequence


def process_normal_stream(data, null_mean, null_std, v_opt=100, alpha_opt=0.05, threshold=20):
    mixture = TwoSidedNormalMixture(v_opt=v_opt, alpha_opt=alpha_opt)
    detector = CusumDetector(threshold=threshold)

    s_t = 0.0
    prev_log_M = 0.0

    for i, x in enumerate(data):
        s_t += (x - null_mean) / null_std
        v_t = float(i + 1)

        log_M = mixture.log_superMG(s_t, v_t)
        log_e = log_M - prev_log_M
        e_val = np.exp(log_e)
        prev_log_M = log_M

        detector.update(e_val)

    alarms = detector.get_alarms()
    return {
        'change_detected': len(alarms) > 0,
        'change_points': alarms,
        'final_e_process': float(np.exp(prev_log_M)) if np.isfinite(prev_log_M) else None,
        'n_alarms': len(alarms),
    }


def process_bernoulli_stream(data, null_p, v_opt=50, alpha_opt=0.05, threshold=20):
    mixture = BetaBinomialMixture(
        g=null_p, h=1 - null_p, v_opt=v_opt, alpha_opt=alpha_opt, is_one_sided=False
    )
    detector = CusumDetector(threshold=threshold)

    s_t = 0.0
    prev_log_M = 0.0

    for i, x in enumerate(data):
        s_t += x - null_p
        v_t = float(i + 1) * null_p * (1 - null_p)

        log_M = mixture.log_superMG(s_t, v_t)

        if np.isfinite(log_M):
            log_e = log_M - prev_log_M
            e_val = np.exp(log_e)
            prev_log_M = log_M
        else:
            e_val = 1.0

        detector.update(e_val)

    alarms = detector.get_alarms()
    final_val = float(np.exp(prev_log_M)) if np.isfinite(prev_log_M) else None
    return {
        'change_detected': len(alarms) > 0,
        'change_points': alarms,
        'final_e_process': final_val,
        'n_alarms': len(alarms),
    }


def main():
    with open('/app/data/streams.json') as f:
        streams = json.load(f)
    with open('/app/data/manifest.json') as f:
        manifest = json.load(f)

    results = {}

    for name in sorted(streams.keys()):
        data = streams[name]
        info = manifest[name]

        if info['family'] == 'normal':
            results[name] = process_normal_stream(
                data, info['null_mean'], info['null_std']
            )
        elif info['family'] == 'bernoulli':
            results[name] = process_bernoulli_stream(data, info['null_proportion'])

    # Confidence sequence on stream_1
    cs = ConfidenceSequence(alpha=0.05, v_opt=100, c=1.0, alpha_opt=0.05)
    cs_bounds = {}
    checkpoints = {50, 100, 200, 500, 1000}

    for i, x in enumerate(streams['stream_1']):
        lower, upper = cs.update(x)
        n = i + 1
        if n in checkpoints:
            cs_bounds[str(n)] = {
                'lower': float(lower),
                'upper': float(upper),
                'mean': float(cs.mean),
            }

    results['confidence_sequence'] = cs_bounds

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Detection complete. Results written to /app/results.json")


if __name__ == '__main__':
    main()
