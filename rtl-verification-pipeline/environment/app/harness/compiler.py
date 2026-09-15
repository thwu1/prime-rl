"""Compiles mutated RTL with Verilator."""
import os
import subprocess
from harness.config import VERILATOR_CMD, VERILATOR_FLAGS, RTL_SOURCE, TESTBENCH, BUILD_DIR


def compile_mutation(mutation_id, mutated_rtl_path):
    """Compile a mutated RTL file with Verilator."""
    obj_dir = os.path.join(BUILD_DIR, mutation_id, "obj_dir")
    os.makedirs(os.path.dirname(obj_dir), exist_ok=True)

    cmd = [VERILATOR_CMD] + VERILATOR_FLAGS + [obj_dir, mutated_rtl_path]

    result = subprocess.run(cmd, capture_output=True, text=True)

    binary_path = os.path.join(obj_dir, "Valu")
    return {
        "success": result.returncode == 0,
        "binary": binary_path if os.path.exists(binary_path) else None,
        "stderr": result.stderr,
    }
