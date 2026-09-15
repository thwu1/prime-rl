#!/usr/bin/env python3
"""Solution: fix MiniNPU simulator bugs and generate assembly kernels.

"""

import os

VLEN = 16
N = 64
NUM_CHUNKS = N // VLEN  # 4


def fix_simulator():
    """Patch the three bugs in simulator.py by comparing to the ISA spec."""
    with open('/opt/npu/simulator.py', 'r') as f:
        content = f.read()

    # Bug 1 — VSUB has operands swapped: computes vs2 - vs1 instead of vs1 - vs2
    # The spec says: VSUB vd, vs1, vs2 → vd[i] = vs1[i] - vs2[i]
    content = content.replace(
        'self.vregs[vd] = self.vregs[vs2] - self.vregs[vs1]',
        'self.vregs[vd] = self.vregs[vs1] - self.vregs[vs2]',
    )

    # Bug 2 — VREDSUM only sums first VLEN-1 elements instead of all VLEN
    # The spec says: sd = sum of vs[i] for i in 0..15 (all 16 elements)
    content = content.replace(
        'self.vregs[vs][:VLEN - 1]',
        'self.vregs[vs][:VLEN]',
    )

    # Bug 3 — VMAC overwrites instead of accumulating
    # The spec says: VMAC vd, vs1, vs2 → vd[i] = vd[i] + vs1[i] * vs2[i]
    # The bug: vd = vs1 * vs2 (same as VMUL, missing the += accumulation)
    # Both VMUL and VMAC have "self.vregs[vd] = self.vregs[vs1] * self.vregs[vs2]"
    # so we must target only the VMAC handler (the second occurrence).
    lines = content.split('\n')
    in_vmac_handler = False
    fixed_lines = []
    for line in lines:
        if "'VMAC'" in line:
            in_vmac_handler = True
        if (in_vmac_handler and
                'self.vregs[vd] = self.vregs[vs1] * self.vregs[vs2]' in line):
            line = line.replace(
                'self.vregs[vd] = self.vregs[vs1] * self.vregs[vs2]',
                'self.vregs[vd] = self.vregs[vd] + self.vregs[vs1] * self.vregs[vs2]',
            )
            in_vmac_handler = False
        fixed_lines.append(line)

    content = '\n'.join(fixed_lines)

    with open('/opt/npu/simulator.py', 'w') as f:
        f.write(content)
    print("[fix] Patched 3 simulator bugs (VSUB operand order, VREDSUM range, VMAC accumulation)")


def generate_dotproduct():
    """Dot product of two 64-element vectors using tiled VMUL/VMAC + VREDSUM."""
    lines = [
        '# Dot product: a[0:63] · b[64:127] → result at addr 128',
        '# Initialize accumulator vector to zero',
        'VBCAST v10, s0',
    ]
    for chunk in range(NUM_CHUNKS):
        a_addr = chunk * VLEN
        b_addr = N + chunk * VLEN
        lines.append(f'VLD v0, {a_addr}')
        lines.append(f'VLD v1, {b_addr}')
        if chunk == 0:
            lines.append('VMUL v10, v0, v1')
        else:
            lines.append('VMAC v10, v0, v1')
    lines.extend([
        '# Horizontal sum of partial products',
        'VREDSUM s1, v10',
        'SST s1, 128',
        'HALT',
    ])
    return '\n'.join(lines)


def generate_softmax():
    """Numerically-stable softmax over 64 elements: max → sub → exp → sum → div."""
    lines = ['# Softmax: input[0:63] → output[64:127]']
    # Load all chunks
    for i in range(NUM_CHUNKS):
        lines.append(f'VLD v{i}, {i * VLEN}')

    # Find global maximum
    lines.append('VREDMAX s1, v0')
    for i in range(1, NUM_CHUNKS):
        lines.append(f'VREDMAX s2, v{i}')
        lines.append('SMAX s1, s1, s2')

    # Subtract max for stability
    lines.append('VBCAST v8, s1')
    for i in range(NUM_CHUNKS):
        lines.append(f'VSUB v{i}, v{i}, v8')

    # Exponentials
    for i in range(NUM_CHUNKS):
        lines.append(f'VEXP v{i}, v{i}')

    # Sum of exponentials
    lines.append('VREDSUM s1, v0')
    for i in range(1, NUM_CHUNKS):
        lines.append(f'VREDSUM s2, v{i}')
        lines.append('SADD s1, s1, s2')

    # Normalize
    lines.append('VBCAST v8, s1')
    for i in range(NUM_CHUNKS):
        lines.append(f'VDIV v{i}, v{i}, v8')

    # Store output
    for i in range(NUM_CHUNKS):
        lines.append(f'VST v{i}, {N + i * VLEN}')
    lines.append('HALT')
    return '\n'.join(lines)


def generate_rmsnorm():
    """RMSNorm: output = (x / rms(x)) * w, rms = sqrt(mean(x^2) + eps)."""
    lines = ['# RMSNorm: x[0:63], w[64:127] → output[128:191], eps=1e-6']
    # Load input x
    for i in range(NUM_CHUNKS):
        lines.append(f'VLD v{i}, {i * VLEN}')

    # Compute x^2 in v4-v7
    for i in range(NUM_CHUNKS):
        lines.append(f'VMUL v{i + NUM_CHUNKS}, v{i}, v{i}')

    # Sum of squares
    lines.append(f'VREDSUM s1, v{NUM_CHUNKS}')
    for i in range(1, NUM_CHUNKS):
        lines.append(f'VREDSUM s2, v{NUM_CHUNKS + i}')
        lines.append('SADD s1, s1, s2')

    # Mean of squares
    lines.append(f'SMOV s2, #{float(N)}')
    lines.append('SDIV s1, s1, s2')

    # sqrt(mean + epsilon)
    lines.append('SMOV s3, #1e-6')
    lines.append('SADD s1, s1, s3')
    lines.append('SSQRT s1, s1')

    # 1 / rms
    lines.append('SMOV s2, #1.0')
    lines.append('SDIV s2, s2, s1')

    # Normalize x
    lines.append('VBCAST v8, s2')
    for i in range(NUM_CHUNKS):
        lines.append(f'VMUL v{i}, v{i}, v8')

    # Load weights and apply
    for i in range(NUM_CHUNKS):
        lines.append(f'VLD v{i + NUM_CHUNKS}, {N + i * VLEN}')
    for i in range(NUM_CHUNKS):
        lines.append(f'VMUL v{i}, v{i}, v{i + NUM_CHUNKS}')

    # Store output
    for i in range(NUM_CHUNKS):
        lines.append(f'VST v{i}, {2 * N + i * VLEN}')
    lines.append('HALT')
    return '\n'.join(lines)


def main():
    # Phase 1: patch the simulator
    fix_simulator()

    # Phase 2: generate assembly kernels
    os.makedirs('/opt/npu/programs', exist_ok=True)
    kernels = {
        'dotproduct.asm': generate_dotproduct(),
        'softmax.asm': generate_softmax(),
        'rmsnorm.asm': generate_rmsnorm(),
    }
    for name, code in kernels.items():
        path = f'/opt/npu/programs/{name}'
        with open(path, 'w') as f:
            f.write(code)
        print(f"[gen] {path}  ({len(code.splitlines())} lines)")


if __name__ == '__main__':
    main()
