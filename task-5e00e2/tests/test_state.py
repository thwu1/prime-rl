
"""
Test suite for the Z3-based component program synthesizer.
Generates benchmark specifications, runs the synthesizer, and verifies
correctness on held-out test inputs.
"""

import json
import os
import random
import subprocess
import pytest

BW = 16
MASK = (1 << BW) - 1

OPERATORS = ['add', 'sub', 'mul', 'band', 'bor', 'bxor', 'shl', 'lshr']
CONSTANTS = {'c0': 0, 'c1': 1, 'c65535': MASK}


def eval_op(op, a, b):
    """Evaluate a DSL operation on 16-bit unsigned values."""
    if op == 'add':
        return (a + b) & MASK
    elif op == 'sub':
        return (a - b) & MASK
    elif op == 'mul':
        return (a * b) & MASK
    elif op == 'band':
        return a & b
    elif op == 'bor':
        return a | b
    elif op == 'bxor':
        return a ^ b
    elif op == 'shl':
        return (a << (b & 0xF)) & MASK
    elif op == 'lshr':
        return a >> (b & 0xF)
    raise ValueError(f"Unknown op: {op}")


def eval_program(program, result_var, inputs):
    """Evaluate a DSL program on concrete inputs."""
    env = {}
    for i, v in enumerate(inputs):
        env[f'x{i}'] = v & MASK
    for name, val in CONSTANTS.items():
        env[name] = val
    for step in program:
        a = env[step['arg1']]
        b = env[step['arg2']]
        env[step['dest']] = eval_op(step['op'], a, b)
    return env[result_var]


# ---- Oracle functions (ground truth) ----

def oracle_0(x0, x1):
    """x0 ^ x1"""
    return x0 ^ x1


def oracle_1(x0, x1):
    """(x0 + x1) * x0"""
    return (((x0 + x1) & MASK) * x0) & MASK


def oracle_2(x0, x1, x2):
    """(x0 * x1) + (x1 ^ x2)"""
    return (((x0 * x1) & MASK) + (x1 ^ x2)) & MASK


def oracle_3(x0, x1, x2):
    """((x0 + x1) * x2) ^ (x0 & x2)"""
    t0 = (x0 + x1) & MASK
    t1 = (t0 * x2) & MASK
    t2 = x0 & x2
    return t1 ^ t2


BENCHMARKS = [
    {'oracle': oracle_0, 'num_inputs': 2, 'max_ops': 2, 'timeout': 60},
    {'oracle': oracle_1, 'num_inputs': 2, 'max_ops': 3, 'timeout': 90},
    {'oracle': oracle_2, 'num_inputs': 3, 'max_ops': 4, 'timeout': 180},
    {'oracle': oracle_3, 'num_inputs': 3, 'max_ops': 4, 'timeout': 240},
]


def generate_io_pairs(oracle, num_inputs, count, rng):
    """Generate deterministic I/O pairs from an oracle."""
    pairs = []
    seen = set()
    while len(pairs) < count:
        inputs = tuple(rng.randint(0, MASK) for _ in range(num_inputs))
        if inputs in seen:
            continue
        seen.add(inputs)
        output = oracle(*inputs)
        pairs.append([list(inputs), output])
    return pairs


def run_benchmark(bench_idx):
    """Run synthesizer on a benchmark and verify correctness."""
    bench = BENCHMARKS[bench_idx]
    rng = random.Random(42 + bench_idx)
    timeout = bench['timeout']

    # Generate training I/O pairs
    train_pairs = generate_io_pairs(
        bench['oracle'], bench['num_inputs'], 15, rng
    )

    spec = {
        'num_inputs': bench['num_inputs'],
        'max_ops': bench['max_ops'],
        'bit_width': BW,
        'io_pairs': train_pairs,
    }

    spec_file = f'/tmp/bench_{bench_idx}.json'
    output_file = f'/tmp/solution_{bench_idx}.json'

    with open(spec_file, 'w') as f:
        json.dump(spec, f)

    # Run synthesizer with per-benchmark timeout
    result = subprocess.run(
        ['python3', '/app/synthesizer.py', spec_file, output_file],
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Synthesizer failed on benchmark {bench_idx} "
        f"(exit code {result.returncode}):\n{result.stderr[-1000:]}"
    )

    # Load solution
    assert os.path.exists(output_file), (
        f"Output file {output_file} not created for benchmark {bench_idx}"
    )
    with open(output_file) as f:
        solution = json.load(f)

    assert 'program' in solution, "Solution JSON missing 'program' key"
    assert 'result' in solution, "Solution JSON missing 'result' key"
    assert isinstance(solution['program'], list), "'program' must be a list"
    assert len(solution['program']) > 0, "'program' must be non-empty"

    for i, step in enumerate(solution['program']):
        assert 'op' in step, f"Step {i} missing 'op'"
        assert step['op'] in OPERATORS, f"Step {i} has unknown op '{step['op']}'"
        assert 'arg1' in step, f"Step {i} missing 'arg1'"
        assert 'arg2' in step, f"Step {i} missing 'arg2'"
        assert 'dest' in step, f"Step {i} missing 'dest'"

    # Verify on held-out test inputs
    test_rng = random.Random(99999 + bench_idx)
    num_test = 500
    for trial in range(num_test):
        inputs = [test_rng.randint(0, MASK)
                  for _ in range(bench['num_inputs'])]
        expected = bench['oracle'](*inputs)
        try:
            actual = eval_program(
                solution['program'], solution['result'], inputs
            )
        except (KeyError, ValueError) as e:
            pytest.fail(
                f"Benchmark {bench_idx}, trial {trial}: "
                f"program evaluation error: {e}"
            )
        assert actual == expected, (
            f"Benchmark {bench_idx}, trial {trial}: "
            f"inputs={inputs}, expected={expected}, got={actual}"
        )


def test_benchmark_0_xor():
    """Benchmark 0: f(x0, x1) = x0 ^ x1  (1 op, 2 inputs)"""
    run_benchmark(0)


def test_benchmark_1_addmul():
    """Benchmark 1: f(x0, x1) = (x0+x1)*x0  (2 ops, 2 inputs)"""
    run_benchmark(1)


def test_benchmark_2_mulxor():
    """Benchmark 2: f(x0,x1,x2) = (x0*x1)+(x1^x2)  (3 ops, 3 inputs)"""
    run_benchmark(2)


def test_benchmark_3_complex():
    """Benchmark 3: f(x0,x1,x2) = ((x0+x1)*x2)^(x0&x2)  (4 ops, 3 inputs)"""
    run_benchmark(3)
