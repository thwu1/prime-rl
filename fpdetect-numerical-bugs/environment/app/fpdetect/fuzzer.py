"""Grey-box fuzzer for floating-point inputs using IEEE 754 bit-level mutations."""

import random
import struct
import math
from .ieee754 import float32_to_bits, bits_to_float32


class FPFuzzer:
    """Fuzzer that generates floating-point test inputs via bit-level mutations."""

    def __init__(self, seed_value=0.5):
        self.current = seed_value

    def is_within_range(self, value):
        """Check if value is within representable float32 range."""
        return not (value < -3.40E38 or value > 3.40E38)

    def mutate(self):
        """Apply a random bit-level mutation to the current value."""
        float_bits = float32_to_bits(self.current)

        mutation = random.choice([
            'bitflip_s', 'bitflip_e', 'bitflip_m',
            'add_e', 'add_m', 'dec_e', 'dec_m'
        ])

        if mutation == 'bitflip_s':
            sign_bit = (float_bits >> 31) & 0x1
            flipped = 1 - sign_bit
            modified_bits = (float_bits & 0x7FFFFFFF) | (flipped << 31)

        elif mutation == 'bitflip_e':
            exponent = (float_bits >> 23) & 0xFF
            bit_pos = random.randint(0, 7)
            flipped_exp = exponent ^ (1 << bit_pos)
            modified_bits = (float_bits & 0x807FFFFF) | (flipped_exp << 23)

        elif mutation == 'bitflip_m':
            mantissa = float_bits & 0x007FFFFF
            bit_pos = random.randint(0, 22)
            flipped_man = mantissa ^ (1 << bit_pos)
            modified_bits = (float_bits & 0xFF800000) | flipped_man

        elif mutation == 'add_e':
            exponent = (float_bits >> 23) & 0xFF
            increment = random.randint(1, 32)
            new_exp = min(exponent + increment, 254)
            modified_bits = (float_bits & 0x807FFFFF) | (new_exp << 23)

        elif mutation == 'add_m':
            mantissa = float_bits & 0x007FFFFF
            p = random.randint(1, 20)
            increment = 2 ** (p - 1)
            new_man = min(mantissa + increment, 0x007FFFFF)
            modified_bits = (float_bits & 0xFF800000) | new_man

        elif mutation == 'dec_e':
            exponent = (float_bits >> 23) & 0xFF
            decrement = random.randint(1, 32)
            new_exp = max(exponent - decrement, 0)
            modified_bits = (float_bits & 0x807FFFFF) | (new_exp << 23)

        elif mutation == 'dec_m':
            mantissa = float_bits & 0x007FFFFF
            p = random.randint(1, 20)
            decrement = 2 ** (p - 1)
            new_man = max(mantissa - decrement, 0)
            modified_bits = (float_bits & 0xFF800000) | new_man

        modified_value = bits_to_float32(modified_bits)

        if self.is_within_range(modified_value):
            self.current = modified_value
            return modified_value
        else:
            self.current = self.current + 0.5
            return self.current

    def generate_inputs(self, n):
        """Generate n mutated inputs."""
        inputs = [self.current]
        for _ in range(n - 1):
            inputs.append(self.mutate())
        return inputs
