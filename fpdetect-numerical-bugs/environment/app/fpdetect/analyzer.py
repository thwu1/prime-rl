"""Main analysis driver for numerical anomaly detection."""

import math
import random
from .ieee754 import to_float32
from .detection import classify_anomaly
from .fuzzer import FPFuzzer

# Supported math functions and their signatures
MATH_FUNCTIONS = {
    'exp': (math.exp, 1),
    'log': (math.log, 1),
    'sin': (math.sin, 1),
    'cos': (math.cos, 1),
    'tan': (math.tan, 1),
    'asin': (math.asin, 1),
    'acos': (math.acos, 1),
    'atan': (math.atan, 1),
    'sinh': (math.sinh, 1),
    'cosh': (math.cosh, 1),
    'tanh': (math.tanh, 1),
    'sqrt': (math.sqrt, 1),
    'erf': (math.erf, 1),
    'erfc': (math.erfc, 1),
    'lgamma': (math.lgamma, 1),
    'expm1': (math.expm1, 1),
    'log1p': (math.log1p, 1),
    'log2': (math.log2, 1),
    'log10': (math.log10, 1),
}


def evaluate_function(func, x):
    """Evaluate a math function, returning (result, error_string)."""
    try:
        return func(x), None
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        return float('nan'), str(e)


def analyze_function(func_name, func, iterations, seed_value=0.5):
    """Analyze a single math function for numerical anomalies."""
    fuzzer = FPFuzzer(seed_value)
    inputs = fuzzer.generate_inputs(iterations)

    anomalies = []

    for idx in range(len(inputs)):
        x = inputs[idx]

        # Skip NaN inputs
        if math.isnan(x):
            continue

        # Evaluate at float64 precision
        f64_result, f64_error = evaluate_function(func, x)

        # Evaluate at float32 precision (truncate input, compute, truncate output)
        x_f32 = to_float32(x)
        f32_result_raw, f32_error = evaluate_function(func, x_f32)
        if f32_error is None:
            f32_result = to_float32(f32_result_raw)
        else:
            f32_result = f32_result_raw

        # Classify anomaly
        anomaly = classify_anomaly(f32_result, f64_result)
        if anomaly:
            anomalies.append({
                'input': x,
                'f32_result': f32_result if not math.isnan(f32_result) else 'NaN',
                'f64_result': f64_result if not math.isnan(f64_result) else 'NaN',
                'anomaly_type': anomaly,
                'input_f32': x_f32,
            })

    return anomalies


def run_analysis(functions_to_test, iterations=200, seed=42):
    """Run analysis on all specified functions."""
    random.seed(seed)

    results = {}
    for func_name in functions_to_test:
        if func_name not in MATH_FUNCTIONS:
            continue
        func, nargs = MATH_FUNCTIONS[func_name]
        anomalies = analyze_function(func_name, func, iterations)

        # Summarize
        type_counts = {}
        for a in anomalies:
            t = a['anomaly_type']
            type_counts[t] = type_counts.get(t, 0) + 1

        results[func_name] = {
            'total_anomalies': len(anomalies),
            'anomaly_types': type_counts,
            'sample_anomalies': anomalies[:5],
        }

    return results
