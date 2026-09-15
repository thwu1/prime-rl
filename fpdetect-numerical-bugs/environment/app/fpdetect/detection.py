"""Numerical anomaly detection oracles."""

import math


def detect_overflow(f32_result):
    """Detect if a float32 result has overflowed."""
    return math.isinf(f32_result)


def detect_underflow(f32_result, f64_result):
    """Detect if a float32 result has underflowed (lost precision near zero)."""
    if f32_result == 0.0 and f64_result != 0.0 and abs(f64_result) > 0:
        return True
    return False


def detect_special_value(value):
    """Detect special floating-point values."""
    if math.isnan(value):
        return 'nan'
    if math.isinf(value) and value > 0:
        return 'inf'
    return None


def detect_precision_loss(f32_result, f64_result, threshold=1e-5):
    """Detect significant precision loss between float32 and float64 results."""
    if math.isnan(f32_result) or math.isnan(f64_result):
        return False, 0.0
    if math.isinf(f32_result) or math.isinf(f64_result):
        return False, 0.0

    diff = abs(f32_result - f64_result)
    if diff > threshold:
        return True, diff
    return False, diff


def classify_anomaly(f32_result, f64_result):
    """Classify the type of numerical anomaly detected."""
    # Check for special values first
    f32_special = detect_special_value(f32_result)
    f64_special = detect_special_value(f64_result)

    if f32_special == 'nan' and f64_special != 'nan':
        return 'nan_divergence'
    if f32_special == 'nan' and f64_special == 'nan':
        return 'nan_both'
    if f32_special == 'inf':
        return 'overflow'

    # Check underflow
    if detect_underflow(f32_result, f64_result):
        return 'underflow'

    # Check precision loss
    has_loss, error = detect_precision_loss(f32_result, f64_result)
    if has_loss:
        return 'precision_loss'

    return None
