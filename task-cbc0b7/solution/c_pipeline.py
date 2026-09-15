
"""C-style LED command processing pipeline.

Faithfully reproduces the behavior of the C (ESP-IDF/FreeRTOS) firmware
from the Neon Beat Buzzer project, including integer truncation semantics,
the hardcoded wave table, and pattern timing formulas.
"""

import math
import json


# Hardcoded wave table from c_ubt_led.c:33-38
C_WAVE_TABLE = [
    0,   16,  31,  47,  63,  78,  93,  108, 122, 136, 149, 162, 174,
    185, 196, 206, 215, 223, 230, 237, 242, 246, 250, 252, 254, 255,
    254, 252, 250, 246, 242, 237, 230, 223, 215, 206, 196, 185, 174,
    162, 149, 136, 122, 108, 93,  78,  63,  47,  31,  16,  0,
]

LED_REFRESH_PERIOD_MS = 20


def process_hsv(h: float, s: float, v: float) -> tuple:
    """Process HSV color the C way.

    From ws_commands.c:
      hue = (int)(h > 0 ? h : 360 + h)
      saturation = (int)(s * 255)
      value = (int)(v * 255)

    Then passed to ESP-IDF led_strip_set_pixel_hsv which internally
    normalizes hue (% 360) and does standard HSV-to-RGB with s,v in 0-255.
    """
    # C-style hue preprocessing (ws_commands.c:36, 69)
    if h > 0:
        hue = int(h)
    else:
        hue = int(360 + h)

    # C-style saturation/value: float 0-1 -> int 0-255
    sat = int(s * 255)
    val = int(v * 255)

    # ESP-IDF led_strip_set_pixel_hsv wraps hue to 0-359
    hue = hue % 360

    # Normalize back to 0.0-1.0 for HSV-to-RGB (ESP-IDF internal)
    s_norm = sat / 255.0
    v_norm = val / 255.0

    # Standard HSV-to-RGB algorithm
    c = v_norm * s_norm
    x = c * (1.0 - abs(math.fmod(hue / 60.0, 2.0) - 1.0))
    m = v_norm - c

    if 0 <= hue < 60:
        r, g, b = c, x, 0.0
    elif 60 <= hue < 120:
        r, g, b = x, c, 0.0
    elif 120 <= hue < 180:
        r, g, b = 0.0, c, x
    elif 180 <= hue < 240:
        r, g, b = 0.0, x, c
    elif 240 <= hue < 300:
        r, g, b = x, 0.0, c
    elif 300 <= hue < 360:
        r, g, b = c, 0.0, x
    else:
        r, g, b = 0.0, 0.0, 0.0

    return (int((r + m) * 255.0), int((g + m) * 255.0), int((b + m) * 255.0))


def generate_wave_table() -> list:
    """Return the hardcoded C wave table from ubt_led.c."""
    return list(C_WAVE_TABLE)


def compute_pattern_timing(period_ms: int, duty_cycle_pct: int, pattern: str) -> dict:
    """Compute pattern timing the C way.

    Blink: on_time = period * dc / 100, off_time = period * (100 - dc) / 100
    Wave: tick = 20ms, gap = LED_REFRESH_PERIOD_MS * 50 * 100 / dc
    """
    if pattern == "blink":
        on_ms = period_ms * duty_cycle_pct // 100
        off_ms = period_ms * (100 - duty_cycle_pct) // 100
        return {
            "on_ms": on_ms,
            "off_ms": off_ms,
            "total_cycle_ms": period_ms,
        }
    elif pattern == "wave":
        wave_len = len(C_WAVE_TABLE)
        wave_phase_ms = wave_len * LED_REFRESH_PERIOD_MS
        # C gap formula from ubt_led.c:108
        # wait_delay_ticks = pdMS_TO_TICKS(LED_REFRESH_PERIOD_MS*50 * 100 / current_cmd.duty_cycle)
        if duty_cycle_pct > 0:
            gap_ms = LED_REFRESH_PERIOD_MS * 50 * 100 // duty_cycle_pct
        else:
            gap_ms = 0
        return {
            "tick_ms": LED_REFRESH_PERIOD_MS,
            "table_entries": wave_len,
            "wave_phase_ms": wave_phase_ms,
            "gap_ms": gap_ms,
            "total_cycle_ms": wave_phase_ms + gap_ms,
        }
    elif pattern == "off":
        return {"total_cycle_ms": 0}
    else:
        return {"error": f"unknown pattern: {pattern}"}


def process_command(json_str: str) -> dict:
    """Parse a JSON command the C way (cJSON manual extraction)."""
    data = json.loads(json_str)
    pattern = data.get("pattern", {})
    ptype = pattern.get("type", "")

    if ptype == "off":
        return {"pattern": "off"}

    details = pattern.get("details", {})
    if not details:
        return {"error": "missing details"}

    color = details.get("color", {})
    h = color.get("h", 0)
    s_val = color.get("s", 0)
    v_val = color.get("v", 0)

    # C-style conversion
    if h > 0:
        hue = int(h)
    else:
        hue = int(360 + h)
    saturation = int(s_val * 255)
    value = int(v_val * 255)

    return {
        "pattern": ptype,
        "hue": hue,
        "saturation": saturation,
        "value": value,
        "duration_ms": details.get("duration_ms", 0),
        "period_ms": details.get("period_ms", 0),
        "duty_cycle": int(details.get("dc", 0) * 100),
    }
