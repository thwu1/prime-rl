"""IEEE 754 single-precision floating-point utilities."""

import struct
import math

# IEEE 754 float32 constants
FLT_MAX = 3.4028235e+38
FLT_MIN = 1.1754944e-38  # Minimum positive normal float32
FLT_EPSILON = 1.1920929e-7


def float32_to_bits(value):
    """Convert a Python float to its IEEE 754 single-precision bit pattern (uint32)."""
    packed = struct.pack('>f', value)
    return struct.unpack('<I', packed)[0]


def bits_to_float32(bits):
    """Convert a uint32 IEEE 754 bit pattern to a Python float."""
    packed = struct.pack('>I', bits)
    return struct.unpack('>f', packed)[0]


def to_float32(value):
    """Convert a Python float (float64) to float32 precision."""
    return round(value, 7)


def extract_components(bits):
    """Extract sign, exponent, mantissa from IEEE 754 single-precision bits."""
    sign = (bits >> 31) & 0x1
    exponent = (bits >> 23) & 0xFF
    mantissa = bits & 0x007FFFFF
    return sign, exponent, mantissa


def classify_f32_bits(bits):
    """Classify a float32 by its bit pattern."""
    sign, exponent, mantissa = extract_components(bits)
    if exponent == 0 and mantissa == 0:
        return 'zero'
    elif exponent == 0:
        return 'subnormal'
    elif exponent == 255 and mantissa == 0:
        return 'infinity'
    elif exponent == 255:
        return 'nan'
    else:
        return 'normal'


def relative_error(measured, reference):
    """Compute relative error between measured and reference values."""
    return abs(measured - reference) / abs(reference)
