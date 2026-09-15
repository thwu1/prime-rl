"""
Nuclear-grade graphite thermal properties.

Based on irradiated IG-110 graphite data for pebble fuel.
"""


def conductivity(T, k_a, k_b):
    """
    Thermal conductivity of irradiated graphite [W/(m·K)].

    k(T) = 1 / (k_a + k_b * T)

    Parameters
    ----------
    T : float or array
        Temperature [K]
    k_a : float
        Constant coefficient [m·K/W]
    k_b : float
        Linear temperature coefficient [m/W]
    """
    return 1.0 / (k_a + k_b * T)
