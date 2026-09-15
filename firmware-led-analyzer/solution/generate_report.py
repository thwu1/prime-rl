#!/usr/bin/env python3

"""
Generate audit_report.json by comparing reference.py against corrected.py
to detect and document all behavioral discrepancies.
"""

import importlib.util
import json
import sys


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ref = load_module("/app/reference.py", "reference")
    cor = load_module("/app/corrected.py", "corrected")

    bugs = []

    # Bug 1: C hue normalization for h=0
    ref_h, _, _ = ref.CProcessor().normalize_color(0.0, 1.0, 1.0)
    cor_h, _, _ = cor.CProcessor().normalize_color(0.0, 1.0, 1.0)
    if ref_h != cor_h:
        bugs.append({
            "bug_id": "c_hue_zero_comparison",
            "location": "CProcessor.normalize_color",
            "description": (
                "Uses h >= 0 comparison instead of h > 0. The C source code has "
                "'h->valuedouble > 0 ? h->valuedouble : 360 + h->valuedouble' which "
                "evaluates 0.0 > 0 as false, mapping hue=0 to 360. The reference "
                "incorrectly uses >= causing hue=0 to remain 0."
            ),
            "impact": f"normalize_color(0.0, s, v) returns hue={ref_h} instead of {cor_h}",
        })

    # Bug 2: C wave pause constant
    ref_t = ref.CProcessor().compute_wave_cycle_timing(50)
    cor_t = cor.CProcessor().compute_wave_cycle_timing(50)
    if ref_t["pause_ms"] != cor_t["pause_ms"]:
        bugs.append({
            "bug_id": "c_wave_pause_constant",
            "location": "CProcessor.compute_wave_cycle_timing",
            "description": (
                "Uses len(WAVE_TABLE) which is 51 (sizeof(wave)) instead of the "
                "hardcoded constant 50 found in the C source: "
                "'LED_REFRESH_PERIOD_MS*50*100/current_cmd.duty_cycle'. The 50 and "
                "sizeof(wave)=51 are distinct values in the firmware."
            ),
            "impact": f"pause_ms for dc=50 is {ref_t['pause_ms']} instead of {cor_t['pause_ms']}",
        })

    # Bug 3: Rust HSV-to-RGB rounding
    ref_rgb = ref.RustProcessor().hsv_to_rgb(0.0, 0.5, 1.0)
    cor_rgb = cor.RustProcessor().hsv_to_rgb(0.0, 0.5, 1.0)
    if ref_rgb != cor_rgb:
        bugs.append({
            "bug_id": "rust_hsv_rounding_vs_truncation",
            "location": "RustProcessor.hsv_to_rgb",
            "description": (
                "Uses round() for final RGB conversion instead of int() (truncation). "
                "Rust's 'as u8' cast truncates the float toward zero, equivalent to "
                "Python's int() for positive values. round() applies banker's rounding "
                "which differs for fractional values >= 0.5."
            ),
            "impact": f"hsv_to_rgb(0, 0.5, 1.0) returns {ref_rgb} instead of {cor_rgb}",
        })

    # Bug 4: Rust wave cosine formula offset
    ref_table = ref.RustProcessor().compute_wave_table(3000)
    cor_table = cor.RustProcessor().compute_wave_table(3000)
    if ref_table[35][0] != cor_table[35][0]:
        bugs.append({
            "bug_id": "rust_wave_cosine_phase_offset",
            "location": "RustProcessor.compute_wave_table",
            "description": (
                "Cosine argument uses (2*i - N + 1) instead of (2*i - N). The Rust "
                "source has 'cos(PI * (2.0 * index as f64 - MAX_BRIGHTNESS_TABLE_LEN "
                "as f64) / MAX_BRIGHTNESS_TABLE_LEN as f64)' with no +1 term. The "
                "offset shifts the entire wave phase."
            ),
            "impact": (
                f"Peak brightness at index 35 is {ref_table[35][0]} instead of "
                f"{cor_table[35][0]}; all non-boundary entries are shifted"
            ),
        })

    # Bug 5: Rust wave table last entry duration
    if ref_table[69][1] != cor_table[69][1]:
        bugs.append({
            "bug_id": "rust_wave_last_entry_duration",
            "location": "RustProcessor.compute_wave_table",
            "description": (
                "Last entry duration subtracts (N-1)*tick_period instead of N*tick_period. "
                "The Rust source computes 'period - Duration::from_millis("
                "MAX_BRIGHTNESS_TABLE_LEN as u64 * WAVE_TICK_PERIOD_MS)' which uses "
                "N=70, not N-1=69."
            ),
            "impact": (
                f"Last entry duration for period=3000 is {ref_table[69][1]}ms "
                f"instead of {cor_table[69][1]}ms"
            ),
        })

    # Bug 6: Rust blink off-time calculation
    ref_blink = ref.RustProcessor().compute_blink_timing(7, 33)
    cor_blink = cor.RustProcessor().compute_blink_timing(7, 33)
    if ref_blink != cor_blink:
        bugs.append({
            "bug_id": "rust_blink_off_calculation",
            "location": "RustProcessor.compute_blink_timing",
            "description": (
                "Computes off_ms using independent integer division "
                "(period*(100-dc)//100) instead of subtraction (period - on_ms). "
                "The Rust source computes 'table[1].duration = p - table[0].duration' "
                "which guarantees on+off==period. Independent division can lose "
                "a millisecond to truncation."
            ),
            "impact": f"Blink timing for period=7, dc=33 is {ref_blink} instead of {cor_blink}",
        })

    with open("/app/audit_report.json", "w") as f:
        json.dump(bugs, f, indent=2)

    print(f"Audit complete: found {len(bugs)} bugs")


if __name__ == "__main__":
    main()
