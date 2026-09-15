#!/usr/bin/env python3
"""Validate predictor output against expected results."""
import json
import sys
import os


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compare_results(expected, actual):
    """Compare actual results against expected, return list of failure messages."""
    failures = []

    exp_keys = set(expected.keys())
    act_keys = set(actual.keys())

    if exp_keys != act_keys:
        missing = exp_keys - act_keys
        extra = act_keys - exp_keys
        if missing:
            failures.append(f"Missing workloads: {missing}")
        if extra:
            failures.append(f"Unexpected workloads: {extra}")
        return failures

    for wk_key in sorted(expected.keys()):
        exp_configs = expected[wk_key]
        act_configs = actual[wk_key]

        if len(exp_configs) != len(act_configs):
            failures.append(f"{wk_key}: expected {len(exp_configs)} configs, got {len(act_configs)}")
            continue

        for idx, (ec, ac) in enumerate(zip(exp_configs, act_configs)):
            prefix = f"{wk_key} rank {idx}"

            # Check config_id (sort order)
            if ec['config_id'] != ac['config_id']:
                failures.append(
                    f"{prefix}: wrong config at this rank — expected config_id {ec['config_id']}, "
                    f"got {ac['config_id']}")

            # Check validity
            if ec['is_valid'] != ac['is_valid']:
                failures.append(
                    f"{prefix} (config {ac['config_id']}): validity mismatch — "
                    f"expected {ec['is_valid']}, got {ac['is_valid']}")

            # Check shared_mem_bytes
            if ec['shared_mem_bytes'] != ac['shared_mem_bytes']:
                failures.append(
                    f"{prefix} (config {ac['config_id']}): shared_mem_bytes — "
                    f"expected {ec['shared_mem_bytes']}, got {ac['shared_mem_bytes']}")

            # Check occupancy
            if ec['occupancy'] != ac['occupancy']:
                failures.append(
                    f"{prefix} (config {ac['config_id']}): occupancy — "
                    f"expected {ec['occupancy']}, got {ac['occupancy']}")

            # Check performance values
            ep = ec['performance']
            ap = ac['performance']

            for field in ['total_flops', 'total_bytes', 'is_compute_bound']:
                if ep[field] != ap[field]:
                    failures.append(
                        f"{prefix} (config {ac['config_id']}): {field} — "
                        f"expected {ep[field]}, got {ap[field]}")

            for field in ['arithmetic_intensity', 'attainable_tflops',
                          'estimated_time_ms', 'wave_utilization', 'ridge_point']:
                ev = ep[field]
                av = ap[field]
                if ev == 0 and av == 0:
                    continue
                if ev == 0 or abs(ev - av) / max(abs(ev), 1e-15) > 0.001:
                    failures.append(
                        f"{prefix} (config {ac['config_id']}): {field} — "
                        f"expected {ev:.6g}, got {av:.6g}")

            # Check schedule_info for valid configs
            if ec['is_valid'] and ac['is_valid']:
                es = ec['schedule_info']
                as_ = ac['schedule_info']
                if as_ is None:
                    failures.append(f"{prefix}: schedule_info missing for valid config")
                else:
                    for field in ['num_pid_m', 'num_pid_n', 'num_tiles',
                                  'active_sms', 'tiles_per_sm_max']:
                        if es[field] != as_[field]:
                            failures.append(
                                f"{prefix} (config {ac['config_id']}): schedule {field} — "
                                f"expected {es[field]}, got {as_[field]}")

    return failures


def main():
    expected_path = '/app/expected_output.json'
    results_path = '/app/results.json'

    if not os.path.exists(results_path):
        print("ERROR: /app/results.json not found. Run: python3 /app/predict.py")
        sys.exit(1)

    expected = load_json(expected_path)
    actual = load_json(results_path)

    failures = compare_results(expected, actual)

    if not failures:
        print("PASS: All predictions match expected output.")
        sys.exit(0)
    else:
        print(f"FAIL: {len(failures)} discrepancies found:\n")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == '__main__':
    main()
