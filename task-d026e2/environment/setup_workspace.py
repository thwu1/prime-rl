#!/usr/bin/env python3
"""Set up workspace data for the generalization-aware kernel evaluation task."""
import os
import yaml

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def write_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

# ============================================================
# Source files for kernel task workspaces
# ============================================================

write_file('/app/data/workspaces/task_01/scripts/task_runner.py', '''\
#!/usr/bin/env python3
"""Task runner for fused MoE kernel optimization."""
import sys
import json

# Configuration
NUM_WARMUP = 3
NUM_ITERS = 10

TEST_SHAPES = [
    (2, 16, 128, 256, True, False),
    (4, 32, 256, 512, True, True),
    (8, 64, 512, 1024, False, True),  # large config
]

# NOTE: Do not modify TEST_SHAPES_EXTENDED
TEST_SHAPES_EXTENDED = []


def compile_kernel():
    """Compile the kernel source."""
    print("Compiling...")
    return True


def run_correctness(shape):
    """Run correctness check for a single shape."""
    batch, experts, seq_len, hidden, causal, use_weight = shape
    print(f"Testing shape: batch={batch}, experts={experts}, "
          f"seq_len={seq_len}, hidden={hidden}")
    return True


def run_performance(shape):
    """Measure performance for a single shape."""
    batch, experts, seq_len, hidden, causal, use_weight = shape
    return 1.0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "correctness"

    if mode == "compile":
        compile_kernel()
    elif mode == "correctness":
        for shape in TEST_SHAPES:
            if not run_correctness(shape):
                sys.exit(1)
    elif mode == "performance":
        results = []
        for shape in TEST_SHAPES:
            t = run_performance(shape)
            results.append({"shape": list(shape), "time_ms": t})
        print(json.dumps(results))


if __name__ == "__main__":
    main()
''')

write_file('/app/data/workspaces/task_02/pytorch_code_module/py_14539_GELU.py', '''\
"""GELU kernel module."""
import torch
import torch.nn as nn


class GELUModel(nn.Module):
    def __init__(self, features):
        super().__init__()
        self.fc = nn.Linear(features, features)

    def forward(self, x):
        return torch.nn.functional.gelu(self.fc(x))


def get_inputs():
    # Standard test configurations for GELU
    configs = [
        ([32, 4], torch.float32),
        ([64, 4], torch.float32),
        ([128, 4], torch.float32),
    ]
    for shape, dtype in configs:
        x = torch.randn(shape, dtype=dtype)
        yield [x]


def get_init_inputs():
    return [[], {"features": 4}]
''')

write_file('/app/data/workspaces/task_02/pytorch_code_functional/py_14539_GELU_func.py', '''\
"""GELU kernel functional implementation."""
import torch


def gelu_forward(x):
    return torch.nn.functional.gelu(x)


def get_inputs():
    # Standard test configurations for GELU
    configs = [
        ([32, 4], torch.float32),
        ([64, 4], torch.float32),
        ([128, 4], torch.float32),
    ]
    for shape, dtype in configs:
        x = torch.randn(shape, dtype=dtype)
        yield [x]


def get_init_inputs():
    return [[], {"features": 4}]
''')

write_file('/app/data/workspaces/task_03/test_add_kernel.py', '''\
"""Test file for vector addition kernel."""
import pytest


@pytest.mark.parametrize('SIZE,BLOCK_SIZE,dtype_str',
                         [(98432, 1024, dtype_str) for dtype_str in ['float16', 'float32']])
def test_add_correctness(SIZE, BLOCK_SIZE, dtype_str):
    """Test correctness of add kernel."""
    print(f"Testing SIZE={SIZE}, BLOCK_SIZE={BLOCK_SIZE}, dtype={dtype_str}")
    assert True


@pytest.mark.parametrize('SIZE,BLOCK_SIZE_ARG,dtype_str',
                         [(98432, 1024, dtype_str) for dtype_str in ['float16', 'float32']] +
                         [(1048576, 2048, dtype_str) for dtype_str in ['float16', 'float32']])
def test_performance(SIZE, BLOCK_SIZE_ARG, dtype_str):
    """Test performance of add kernel."""
    print(f"Performance: SIZE={SIZE}, BLOCK_SIZE={BLOCK_SIZE_ARG}, dtype={dtype_str}")
    assert True
''')

write_file('/app/data/workspaces/task_04/pytorch_code_module/py_8821_SiLU.py', '''\
"""SiLU kernel module."""
import torch
import torch.nn as nn


class SiLUModel(nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, x):
        return torch.nn.functional.silu(x)


def get_inputs():
    configs = [
        [16, 256],
        [32, 512],
        [64, 1024],
    ]

    for shape in configs:
        x = torch.randn(shape, dtype=torch.float32)
        yield [x]


def get_init_inputs():
    return [[], {}]
''')

write_file('/app/data/workspaces/task_04/pytorch_code_functional/py_8821_SiLU_func.py', '''\
"""SiLU kernel functional implementation."""
import torch


def silu_forward(x):
    return torch.nn.functional.silu(x)


def get_inputs():
    configs = [
        [16, 256],
        [32, 512],
        [64, 1024],
    ]

    for shape in configs:
        x = torch.randn(shape, dtype=torch.float32)
        yield [x]


def get_init_inputs():
    return [[], {}]
''')

write_file('/app/data/workspaces/task_05/scripts/task_runner.py', '''\
#!/usr/bin/env python3
"""Task runner for flash attention kernel optimization."""
import sys
import json

# Test shapes: (batch, heads, seq_len, head_dim, causal)
TEST_SHAPES = [
    (1, 8, 512, 64, True),
    (2, 16, 1024, 64, False),
    (4, 32, 2048, 128, True),
    (8, 64, 4096, 128, False),
]


def compile_kernel():
    print("Compiling attention kernel...")
    return True


def run_correctness(shape):
    batch, heads, seq_len, head_dim, causal = shape
    print(f"Correctness: batch={batch}, heads={heads}, "
          f"seq_len={seq_len}, head_dim={head_dim}, causal={causal}")
    return True


def run_performance(shape):
    batch, heads, seq_len, head_dim, causal = shape
    return 1.0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "correctness"

    if mode == "compile":
        compile_kernel()
    elif mode == "correctness":
        for shape in TEST_SHAPES:
            if not run_correctness(shape):
                sys.exit(1)
    elif mode == "performance":
        results = []
        for shape in TEST_SHAPES:
            t = run_performance(shape)
            results.append({"shape": list(shape), "time_ms": t})
        print(json.dumps(results))


if __name__ == "__main__":
    main()
''')

# ============================================================
# Held-out configuration YAMLs
# ============================================================

TASK_01_REPLACEMENT = (
    "TEST_SHAPES = [\n"
    "    (1, 8, 64, 128, True, False),      # edge-case: batch=1\n"
    "    (16, 128, 1024, 2048, True, True),  # scale-up: 4x\n"
    "    (1, 4, 37, 131, False, True),       # alignment-stress: primes\n"
    "    (2, 16, 1019, 256, True, False),    # alignment-stress: prime seq\n"
    "    (1, 8, 65536, 64, True, False),     # asymmetric: decode-like\n"
    "    (4, 32, 2048, 512, True, True),     # production: Llama-7B\n"
    "    (8, 64, 4096, 1024, False, True),   # production: large model\n"
    "    (2, 8, 32, 64, False, False),       # scale-down: small\n"
    "]\n"
)

write_yaml('/app/data/held_out_configs/task_01.yaml', {
    'task_id': 'triton2triton/vllm/fused_moe',
    'task_type': 'triton2triton',
    'num_original_shapes': 3,
    'injections': [
        {
            'file': 'scripts/task_runner.py',
            'find_marker': 'TEST_SHAPES',
            'replacement_code': TASK_01_REPLACEMENT,
        },
    ],
})

TASK_02_REPLACEMENT_CODE = (
    "def get_inputs():\n"
    "    configs = [\n"
    "        ([1, 4], torch.float32),\n"
    "        ([512, 4], torch.float32),\n"
    "        ([8, 4], torch.float32),\n"
    "        ([37, 4], torch.float32),\n"
    "        ([131, 4], torch.float32),\n"
    "        ([1, 4], torch.float16),\n"
    "        ([256, 4], torch.float32),\n"
    "        ([384, 4], torch.float32),\n"
    "    ]\n"
    "    for shape, dtype in configs:\n"
    "        x = torch.randn(shape, dtype=dtype)\n"
    "        yield [x]\n"
)

write_yaml('/app/data/held_out_configs/task_02.yaml', {
    'task_id': 'hip2hip/gpumode/GELU',
    'task_type': 'hip2hip',
    'num_original_shapes': 3,
    'init_constraints': {'features': 4},
    'injections': [
        {
            'file': 'pytorch_code_module/py_14539_GELU.py',
            'find_marker': 'def get_inputs',
            'replacement_code': TASK_02_REPLACEMENT_CODE,
        },
        {
            'file': 'pytorch_code_functional/py_14539_GELU_func.py',
            'find_marker': 'def get_inputs',
            'replacement_code': TASK_02_REPLACEMENT_CODE,
        },
    ],
})

# For task_03 (raw_replace), old_code must EXACTLY match the source text
TASK_03_OLD_CODE_1 = (
    "@pytest.mark.parametrize('SIZE,BLOCK_SIZE,dtype_str',\n"
    "                         [(98432, 1024, dtype_str) for dtype_str in ['float16', 'float32']])\n"
)
TASK_03_NEW_CODE_1 = (
    "@pytest.mark.parametrize('SIZE,BLOCK_SIZE,dtype_str',\n"
    "                         [(65536, 512, dtype_str) for dtype_str in ['float16', 'float32']])\n"
)
TASK_03_OLD_CODE_2 = (
    "@pytest.mark.parametrize('SIZE,BLOCK_SIZE_ARG,dtype_str',\n"
    "                         [(98432, 1024, dtype_str) for dtype_str in ['float16', 'float32']] +\n"
    "                         [(1048576, 2048, dtype_str) for dtype_str in ['float16', 'float32']])\n"
)
TASK_03_NEW_CODE_2 = (
    "@pytest.mark.parametrize('SIZE,BLOCK_SIZE_ARG,dtype_str',\n"
    "                         [(65536, 512, dtype_str) for dtype_str in ['float16', 'float32']])\n"
)

write_yaml('/app/data/held_out_configs/task_03.yaml', {
    'task_id': 'triton2triton/rocmbench/easy/add_kernel',
    'task_type': 'triton2triton',
    'num_original_shapes': 2,
    'injections': [
        {
            'file': 'test_add_kernel.py',
            'find_marker': 'raw_replace',
            'old_code': TASK_03_OLD_CODE_1,
            'replacement_code': TASK_03_NEW_CODE_1,
        },
        {
            'file': 'test_add_kernel.py',
            'find_marker': 'raw_replace',
            'old_code': TASK_03_OLD_CODE_2,
            'replacement_code': TASK_03_NEW_CODE_2,
        },
    ],
})

TASK_04_REPLACEMENT_CODE = (
    "def get_inputs():\n"
    "    configs = [\n"
    "        [1, 128],\n"
    "        [256, 2048],\n"
    "        [4, 64],\n"
    "        [37, 131],\n"
    "        [1019, 256],\n"
    "        [1, 65536],\n"
    "        [128, 1024],\n"
    "        [64, 512],\n"
    "    ]\n"
    "    for shape in configs:\n"
    "        x = torch.randn(shape, dtype=torch.float32)\n"
    "        yield [x]\n"
)

write_yaml('/app/data/held_out_configs/task_04.yaml', {
    'task_id': 'hip2hip/gpumode/SiLU',
    'task_type': 'hip2hip',
    'num_original_shapes': 3,
    'injections': [
        {
            'file': 'pytorch_code_module/py_8821_SiLU.py',
            'find_marker': 'def get_inputs',
            'replacement_code': TASK_04_REPLACEMENT_CODE,
        },
        {
            'file': 'pytorch_code_functional/py_8821_SiLU_func.py',
            'find_marker': 'def get_inputs',
            'replacement_code': TASK_04_REPLACEMENT_CODE,
        },
    ],
})

TASK_05_REPLACEMENT = (
    "TEST_SHAPES = [\n"
    "    (1, 4, 64, 32, True),             # edge-case: minimal\n"
    "    (16, 128, 8192, 256, True),        # scale-up: large\n"
    "    (1, 2, 128, 16, False),            # scale-down: small\n"
    "    (2, 16, 1019, 64, True),           # alignment-stress: prime\n"
    "    (4, 32, 4003, 128, False),         # alignment-stress: prime\n"
    "    (1, 8, 65536, 64, True),           # asymmetric: decode-like\n"
    "    (8, 32, 2048, 128, True),          # production: Llama-7B\n"
    "    (4, 16, 4096, 64, False),          # production: GPT\n"
    "]\n"
)

write_yaml('/app/data/held_out_configs/task_05.yaml', {
    'task_id': 'triton2triton/vllm/flash_attn',
    'task_type': 'triton2triton',
    'num_original_shapes': 4,
    'injections': [
        {
            'file': 'scripts/task_runner.py',
            'find_marker': 'TEST_SHAPES',
            'replacement_code': TASK_05_REPLACEMENT,
        },
    ],
})

# ============================================================
# Evaluation results (pre-computed held-out eval outcomes)
# ============================================================

# Task 01: both_pass — orig correct, opt correct
write_yaml('/app/data/eval_results/task_01_orig.yaml', {
    'pass_compilation': True,
    'pass_correctness': True,
    'execution_time_ms': 6.0,
})
write_yaml('/app/data/eval_results/task_01_opt.yaml', {
    'pass_compilation': True,
    'pass_correctness': True,
    'execution_time_ms': 2.4,
})

# Task 02: opt_regression — orig correct, opt incorrect
write_yaml('/app/data/eval_results/task_02_orig.yaml', {
    'pass_compilation': True,
    'pass_correctness': True,
    'execution_time_ms': 4.0,
})
write_yaml('/app/data/eval_results/task_02_opt.yaml', {
    'pass_compilation': True,
    'pass_correctness': False,
    'execution_time_ms': 0.0,
})

# Task 03: both_fail — orig incorrect, opt incorrect
write_yaml('/app/data/eval_results/task_03_orig.yaml', {
    'pass_compilation': True,
    'pass_correctness': False,
    'execution_time_ms': 0.0,
})
write_yaml('/app/data/eval_results/task_03_opt.yaml', {
    'pass_compilation': True,
    'pass_correctness': False,
    'execution_time_ms': 0.0,
})

# Task 04: opt_improvement — orig incorrect, opt correct
write_yaml('/app/data/eval_results/task_04_orig.yaml', {
    'pass_compilation': True,
    'pass_correctness': False,
    'execution_time_ms': 0.0,
})
write_yaml('/app/data/eval_results/task_04_opt.yaml', {
    'pass_compilation': True,
    'pass_correctness': True,
    'execution_time_ms': 0.9,
})

# Task 05: both_pass — orig correct, opt correct
write_yaml('/app/data/eval_results/task_05_orig.yaml', {
    'pass_compilation': True,
    'pass_correctness': True,
    'execution_time_ms': 12.0,
})
write_yaml('/app/data/eval_results/task_05_opt.yaml', {
    'pass_compilation': True,
    'pass_correctness': True,
    'execution_time_ms': 4.0,
})

# ============================================================
# Original run results (before held-out evaluation)
# ============================================================

write_yaml('/app/data/original_run_results/task_01.yaml', {
    'task_name': 'triton2triton/vllm/fused_moe',
    'pass_compilation': True,
    'pass_correctness': True,
    'base_execution_time': 5.0,
    'best_optimized_execution_time': 2.0,
    'speedup_ratio': 2.5,
    'score': 370.0,
})

write_yaml('/app/data/original_run_results/task_02.yaml', {
    'task_name': 'hip2hip/gpumode/GELU',
    'pass_compilation': True,
    'pass_correctness': True,
    'base_execution_time': 3.0,
    'best_optimized_execution_time': 1.0,
    'speedup_ratio': 3.0,
    'score': 420.0,
})

write_yaml('/app/data/original_run_results/task_03.yaml', {
    'task_name': 'triton2triton/rocmbench/easy/add_kernel',
    'pass_compilation': True,
    'pass_correctness': True,
    'base_execution_time': 1.0,
    'best_optimized_execution_time': 0.5,
    'speedup_ratio': 2.0,
    'score': 320.0,
})

write_yaml('/app/data/original_run_results/task_04.yaml', {
    'task_name': 'hip2hip/gpumode/SiLU',
    'pass_compilation': True,
    'pass_correctness': True,
    'base_execution_time': 2.0,
    'best_optimized_execution_time': 0.8,
    'speedup_ratio': 2.5,
    'score': 370.0,
})

write_yaml('/app/data/original_run_results/task_05.yaml', {
    'task_name': 'triton2triton/vllm/flash_attn',
    'pass_compilation': True,
    'pass_correctness': True,
    'base_execution_time': 10.0,
    'best_optimized_execution_time': 4.0,
    'speedup_ratio': 2.5,
    'score': 370.0,
})

# ============================================================
# Task manifest
# ============================================================

write_yaml('/app/data/task_manifest.yaml', {
    'tasks': [
        {
            'id': 'task_01',
            'name': 'triton2triton/vllm/fused_moe',
            'workspace_dir': 'workspaces/task_01',
            'held_out_config': 'held_out_configs/task_01.yaml',
            'eval_orig': 'eval_results/task_01_orig.yaml',
            'eval_opt': 'eval_results/task_01_opt.yaml',
            'original_run': 'original_run_results/task_01.yaml',
        },
        {
            'id': 'task_02',
            'name': 'hip2hip/gpumode/GELU',
            'workspace_dir': 'workspaces/task_02',
            'held_out_config': 'held_out_configs/task_02.yaml',
            'eval_orig': 'eval_results/task_02_orig.yaml',
            'eval_opt': 'eval_results/task_02_opt.yaml',
            'original_run': 'original_run_results/task_02.yaml',
        },
        {
            'id': 'task_03',
            'name': 'triton2triton/rocmbench/easy/add_kernel',
            'workspace_dir': 'workspaces/task_03',
            'held_out_config': 'held_out_configs/task_03.yaml',
            'eval_orig': 'eval_results/task_03_orig.yaml',
            'eval_opt': 'eval_results/task_03_opt.yaml',
            'original_run': 'original_run_results/task_03.yaml',
        },
        {
            'id': 'task_04',
            'name': 'hip2hip/gpumode/SiLU',
            'workspace_dir': 'workspaces/task_04',
            'held_out_config': 'held_out_configs/task_04.yaml',
            'eval_orig': 'eval_results/task_04_orig.yaml',
            'eval_opt': 'eval_results/task_04_opt.yaml',
            'original_run': 'original_run_results/task_04.yaml',
        },
        {
            'id': 'task_05',
            'name': 'triton2triton/vllm/flash_attn',
            'workspace_dir': 'workspaces/task_05',
            'held_out_config': 'held_out_configs/task_05.yaml',
            'eval_orig': 'eval_results/task_05_orig.yaml',
            'eval_opt': 'eval_results/task_05_opt.yaml',
            'original_run': 'original_run_results/task_05.yaml',
        },
    ],
})

# Create output directory
os.makedirs('/app/output', exist_ok=True)
os.makedirs('/app/evaluator', exist_ok=True)

print("Workspace setup complete.")
