#!/usr/bin/env python3
"""Generate deterministic NNUE network weights for the evaluation task."""
import random
import struct

random.seed(42)

INPUT_SIZE = 768
HIDDEN_SIZE = 32
NUM_BUCKETS = 4

with open('/app/network.bin', 'wb') as f:
    # Input weights: [NUM_BUCKETS, INPUT_SIZE, HIDDEN_SIZE] in row-major order
    # Use asymmetric range to produce interesting (sometimes negative) evaluations
    for _ in range(NUM_BUCKETS * INPUT_SIZE * HIDDEN_SIZE):
        f.write(struct.pack('<h', random.randint(-8, 12)))

    # Input biases: [HIDDEN_SIZE]
    for _ in range(HIDDEN_SIZE):
        f.write(struct.pack('<h', random.randint(5, 40)))

    # Output weights: [2 * HIDDEN_SIZE]
    for _ in range(2 * HIDDEN_SIZE):
        f.write(struct.pack('<h', random.randint(-50, 50)))

    # Output bias: [1]
    f.write(struct.pack('<h', 15))
