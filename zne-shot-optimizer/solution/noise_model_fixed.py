"""
Deterministic noise model for quantum error mitigation benchmarking — FIXED.

Adds the generate_measurements function required by run_analysis.py.
"""


import math


def exponential_decay(ideal, scale_factor, decay_rate, asymptote=0.0):
    """
    Exponential noise model:
        E(lambda) = asymptote + (ideal - asymptote) * exp(-decay_rate * lambda)
    """
    return asymptote + (ideal - asymptote) * math.exp(-decay_rate * scale_factor)


def polynomial_noise(ideal, scale_factor, coefficients):
    """
    Polynomial noise model:
        E(lambda) = ideal + c_1*lambda + c_2*lambda^2 + ...

    coefficients[k] corresponds to lambda^(k+1).
    """
    result = ideal
    for k, c in enumerate(coefficients):
        result += c * scale_factor ** (k + 1)
    return result


def generate_scenario_data(scenario):
    """Generate deterministic noisy measurements for a benchmark scenario."""
    sf = scenario["scale_factors"]
    ideal = scenario["ideal_value"]
    noise_type = scenario["noise_type"]

    values = []
    for s in sf:
        if noise_type == "exponential":
            v = exponential_decay(
                ideal, s, scenario["decay_rate"],
                scenario.get("asymptote", 0.0)
            )
        elif noise_type == "polynomial":
            v = polynomial_noise(ideal, s, scenario["poly_coefficients"])
        else:
            raise ValueError(f"Unknown noise type: {noise_type}")
        values.append(v)
    return values


def generate_measurements(ideal_value, scale_factors, decay_rate, asymptote=0.0):
    """Generate exponential decay measurements for given parameters."""
    return [exponential_decay(ideal_value, s, decay_rate, asymptote) for s in scale_factors]
