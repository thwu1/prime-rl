
"""Migration divergence analyzer.

Compares the C (ESP-IDF) and Rust (no_std/embassy) LED command processing
pipelines and produces a structured divergence report.
"""

import json
import sys

sys.path.insert(0, "/app")

from c_pipeline import (
    process_hsv as c_hsv,
    generate_wave_table as c_wave,
    compute_pattern_timing as c_timing,
)
from rust_pipeline import (
    process_hsv as r_hsv,
    generate_wave_table as r_wave,
    compute_pattern_timing as r_timing,
)

divergences = []


def add_divergence(div_id, category, severity, description,
                   c_behavior, rust_behavior, test_input):
    divergences.append({
        "id": div_id,
        "category": category,
        "severity": severity,
        "description": description,
        "c_behavior": c_behavior,
        "rust_behavior": rust_behavior,
        "test_input": test_input,
    })


# ── 1. Wave table length ───────────────────────────────────────────────

c_table = c_wave()
r_table = r_wave()

add_divergence(
    "wave_table_length",
    "wave_table",
    "high",
    "Wave brightness tables have different lengths: C uses 51 hardcoded "
    "entries, Rust computes 70 entries dynamically using a cosine formula. "
    "This changes the wave shape resolution and minimum period.",
    f"Hardcoded uint8_t wave[] with {len(c_table)} entries",
    f"Computed table with {len(r_table)} entries via "
    "trunc(127.5 * (1 + cos(pi*(2i-70)/70)))",
    {"c_length": len(c_table), "rust_length": len(r_table)},
)

# ── 2. Wave table values ──────────────────────────────────────────────

matching = sum(1 for a, b in zip(c_table, r_table) if a == b)
add_divergence(
    "wave_table_values",
    "wave_table",
    "high",
    "Wave table values differ between C (hand-crafted symmetric table) "
    "and Rust (cosine-based computation). Only "
    f"{matching}/{min(len(c_table), len(r_table))} overlapping entries "
    "match. The C table appears to be a manually constructed approximation "
    "while Rust uses the analytical formula.",
    f"Hand-crafted values: {c_table[:10]}...",
    f"Cosine-computed values: {r_table[:10]}...",
    {"c_first_10": c_table[:10], "rust_first_10": r_table[:10]},
)

# ── 3. Wave tick period ───────────────────────────────────────────────

add_divergence(
    "wave_tick_period",
    "pattern_timing",
    "medium",
    "Wave pattern tick period differs: C uses LED_REFRESH_PERIOD_MS=20ms, "
    "Rust uses WAVE_TICK_PERIOD_MS=30ms. This means the C wave animates "
    "faster (51*20=1020ms minimum) vs Rust (70*30=2100ms minimum).",
    "LED_REFRESH_PERIOD_MS = 20ms, minimum wave cycle = 1020ms",
    "WAVE_TICK_PERIOD_MS = 30ms, MIN_WAVE_PERIOD_MS = 2100ms",
    {"c_tick_ms": 20, "rust_tick_ms": 30,
     "c_min_cycle_ms": 1020, "rust_min_cycle_ms": 2100},
)

# ── 4. Wave gap calculation ──────────────────────────────────────────

c_tm = c_timing(3000, 50, "wave")
r_tm = r_timing(3000, 50, "wave")

add_divergence(
    "wave_gap_formula",
    "pattern_timing",
    "high",
    "The rest period between wave cycles uses fundamentally different "
    "formulas. C: gap = LED_REFRESH_PERIOD_MS * 50 * 100 / duty_cycle "
    "(duty-cycle-dependent, period-independent). Rust: gap = period - "
    "TABLE_LEN * TICK_PERIOD (period-dependent, duty-cycle-independent). "
    "For period=3000ms, dc=50%: C gap="
    f"{c_tm['gap_ms']}ms, Rust gap={r_tm['gap_ms']}ms.",
    f"Gap = 20*50*100/dc = {c_tm['gap_ms']}ms (dc=50, period=3000)",
    f"Gap = period - 70*30 = {r_tm['gap_ms']}ms (dc=50, period=3000)",
    {"period_ms": 3000, "duty_cycle_pct": 50,
     "c_gap_ms": c_tm["gap_ms"], "rust_gap_ms": r_tm["gap_ms"]},
)

# ── 5. Off-by-one bug in C wave indexing ─────────────────────────────

add_divergence(
    "c_wave_off_by_one",
    "bug",
    "critical",
    "C code has an off-by-one bug in wave table indexing (ubt_led.c). "
    "The condition 'if (i > wave_len)' should be 'if (i >= wave_len)'. "
    "wave_len = sizeof(wave) = 51, valid indices are 0-50. After "
    "wave[i++] with i=50, i becomes 51. Then '51 > 51' is false, so "
    "the next iteration reads wave[51] — one byte past the array — "
    "before i becomes 52 and '52 > 51' triggers the reset. This is "
    "an out-of-bounds read on every wave cycle.",
    "wave[i++] then 'if (i > wave_len)' — reads wave[51] (undefined "
    "memory) because 51 > 51 is false, only resets when i reaches 52",
    "Rust uses iter().cycle() on a slice, which safely wraps around "
    "the brightness table with no manual index arithmetic",
    {"c_code": "wave[i++]...if (i > wave_len)",
     "wave_len": 51, "bug_type": "out-of-bounds read",
     "bad_index": 51, "valid_range": "0-50"},
)

# ── 6. HSV integer truncation ────────────────────────────────────────

test_h, test_s, test_v = 0.0, 0.5, 1.0
c_rgb = c_hsv(test_h, test_s, test_v)
r_rgb = r_hsv(test_h, test_s, test_v)

add_divergence(
    "hsv_integer_truncation",
    "color_conversion",
    "medium",
    "C converts saturation and value from float (0.0-1.0) to integer "
    "(0-255) via int(x*255) before passing to led_strip_set_pixel_hsv, "
    "losing precision. Rust keeps float precision throughout hsv_to_rgb. "
    "Example: s=0.5 → C: int(127.5)=127 → 127/255≈0.498, Rust: 0.5. "
    f"This produces C RGB={c_rgb} vs Rust RGB={r_rgb} — a ±1 difference "
    "in the green and blue channels.",
    f"s=0.5 → int(0.5*255)=127, normalize 127/255≈0.498, RGB={c_rgb}",
    f"s=0.5 (float, no truncation), RGB={r_rgb}",
    {"h": test_h, "s": test_s, "v": test_v,
     "c_rgb": list(c_rgb), "rust_rgb": list(r_rgb)},
)

# ── 7. Hue zero mapping ─────────────────────────────────────────────

add_divergence(
    "hue_zero_mapping",
    "color_conversion",
    "low",
    "C maps hue=0 to 360 because 'h > 0' is false (0 is not > 0), so "
    "the branch '360 + h' produces 360. ESP-IDF then wraps 360 → 0 "
    "internally. Rust maps hue=0 via fmod(0, 360) = 0 directly. "
    "Same visual output after wrapping, but different code paths — "
    "a latent semantic bug that could surface if ESP-IDF changes.",
    "h=0.0 → int(360 + 0) = 360, ESP-IDF wraps to 0",
    "h=0.0 → fmod(0, 360) = 0 directly",
    {"h": 0.0, "s": 1.0, "v": 1.0,
     "c_internal_hue": 360, "rust_internal_hue": 0.0},
)

# ── 8. Hue overflow handling ────────────────────────────────────────

add_divergence(
    "hue_overflow",
    "color_conversion",
    "medium",
    "C does not apply modulo to positive hue values in ws_commands.c — "
    "it passes the raw integer (e.g., 720) to ESP-IDF, relying on the "
    "library to normalize. Rust explicitly applies fmod(h, 360) for "
    "positive values. Both produce the same result if ESP-IDF wraps "
    "correctly, but C's behavior depends on library internals.",
    "h=720.0 → int(720) = 720, passed raw to led_strip_set_pixel_hsv",
    "h=720.0 → fmod(720, 360) = 0.0, normalized before conversion",
    {"h": 720.0, "s": 1.0, "v": 1.0},
)

# ── 9. Duty cycle validation ────────────────────────────────────────

add_divergence(
    "duty_cycle_validation",
    "input_validation",
    "medium",
    "Rust validates that duty cycle is in [0.0, 1.0] and returns "
    "PatternError::InvalidDutyCycle if not. C performs no validation — "
    "values outside the range produce potentially dangerous behavior "
    "(e.g., dc=1.5 → duty_cycle=150, causing on_time > period).",
    "No validation. dc=1.5 → duty_cycle=150, "
    "on_time = period*150/100 = 1.5x period (integer overflow risk)",
    "dc=1.5 → Err(PatternError::InvalidDutyCycle), pattern rejected",
    {"dc": 1.5, "pattern": "blink"},
)

# ── 10. Wave minimum period validation ──────────────────────────────

add_divergence(
    "wave_min_period_validation",
    "input_validation",
    "medium",
    "Rust enforces a minimum wave period of MIN_WAVE_PERIOD_MS = "
    f"{70 * 30}ms (TABLE_LEN * TICK_PERIOD). If period is too short, "
    "it returns PatternError::WavePeriodTooShort. C has no minimum "
    "period check — very short periods cause rapid uncontrolled "
    "iteration through the wave table.",
    "No minimum period check. period=100ms causes rapid 20ms tick "
    "cycling through 51-entry table",
    f"period < {70 * 30}ms → Err(PatternError::WavePeriodTooShort "
    f"{{ min_ms: {70 * 30} }})",
    {"period_ms": 100, "pattern": "wave"},
)

# ── 11. Color representation and wave modulation ────────────────────

add_divergence(
    "wave_color_modulation",
    "color_conversion",
    "high",
    "C stores colors in HSV and modulates the V (value) component by "
    "the wave table: led_strip_set_pixel_hsv(h, s, wave[i]*v/255). "
    "Rust converts HSV→RGB at command parse time and modulates "
    "brightness uniformly across all RGB channels via "
    "SmartLedsWrite::brightness(rgb, wave[i]). For desaturated colors, "
    "V-modulation in HSV space produces different visual results than "
    "uniform RGB brightness scaling.",
    "HSV stored, V modulated: led_strip_set_pixel_hsv(h, s, "
    "wave[i]*v/255). Hue preserved during dimming.",
    "RGB stored at parse time, brightness scaled uniformly: "
    "brightness([rgb], wave[i]). All channels dim equally.",
    {"h": 30.0, "s": 0.5, "v": 1.0, "wave_index": 25,
     "note": "For desaturated colors, HSV V-modulation preserves "
             "hue while RGB brightness scaling dims all channels equally"},
)

# ── Write report ────────────────────────────────────────────────────

report = {"divergences": divergences}
with open("/app/divergence_report.json", "w") as f:
    json.dump(report, f, indent=2)

print(f"Analysis complete. Found {len(divergences)} divergences.")
for d in divergences:
    print(f"  [{d['severity']:>8}] {d['category']}: {d['id']}")
print(f"Report written to /app/divergence_report.json")
