#!/usr/bin/env python3
"""Generate deterministic 200-cycle trace for hazard unit analysis.
Uses SHA-256 hashing for reproducible, platform-independent randomness."""
import hashlib
import csv

INPUT_NAMES = ['BPWrongE', 'CSRWriteFenceM', 'RetM', 'TrapM', 'StructuralStallD',
               'LSUStallM', 'IFUStallF', 'FPUStallD', 'ExternalStall',
               'DivBusyE', 'FDivBusyE', 'wfiM', 'IntPendingM']

# Base probabilities (out of 10000) for each input signal
BASE_PROBS = [800, 200, 150, 250, 400, 800, 600, 350, 150, 500, 250, 200, 400]


def gen_bit(cycle, input_idx):
    """Deterministically generate a single bit using SHA-256."""
    h = hashlib.sha256(f"hazard_trace_v1:{cycle}:{input_idx}".encode()).hexdigest()
    val = int(h[:8], 16)
    return 1 if (val % 10000) < BASE_PROBS[input_idx] else 0


def generate_trace(path='/app/trace.csv', n_cycles=200):
    rows = []
    for cycle in range(n_cycles):
        row = [gen_bit(cycle, i) for i in range(13)]

        # Scenario overrides for interesting corner cases

        # Division scenario: cycles 50-58, DivBusyE sustained
        if 50 <= cycle <= 58:
            row[9] = 1   # DivBusyE
            row[10] = 0  # FDivBusyE off
        # Branch misprediction during active division (tests division protection)
        if cycle == 55:
            row[0] = 1   # BPWrongE

        # WFI scenario: cycles 100-108
        if 100 <= cycle <= 108:
            row[11] = 1  # wfiM
            row[12] = 0  # IntPendingM = 0 initially
        # Interrupt arrival during WFI triggers trap
        if cycle == 105:
            row[12] = 1  # IntPendingM arrives
            row[3] = 1   # TrapM triggered

        # Stall-flush conflict: trap + external stall
        if cycle == 150:
            row[3] = 1   # TrapM
            row[8] = 1   # ExternalStall

        # Division protection override: trap overrides div protection
        if cycle == 160:
            row[0] = 1   # BPWrongE
            row[9] = 1   # DivBusyE
            row[3] = 1   # TrapM overrides division protection

        rows.append(row)

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['cycle'] + INPUT_NAMES)
        for i, row in enumerate(rows):
            writer.writerow([i] + row)


if __name__ == '__main__':
    generate_trace()
