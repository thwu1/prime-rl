
"""Roofline model analyzer using PyTorch's TorchDispatchMode.

Intercepts ATen-level matmul operations during a forward pass, computes
FLOPs, memory bytes, arithmetic intensity, and classifies each operation
as compute-bound or memory-bound using the roofline model.  Also tracks
per-module attribution and analyzes operand memory alignment.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
from torch.utils._python_dispatch import TorchDispatchMode


# ---------------------------------------------------------------------------
# FLOP formulas
# ---------------------------------------------------------------------------

def _mm_flops(args: Tuple, out: Any) -> int:
    # aten.mm(A, B) : A=[M,K], B=[K,N]
    a, b = args[0], args[1]
    M, K = a.shape
    _, N = b.shape
    return 2 * M * K * N


def _addmm_flops(args: Tuple, out: Any) -> int:
    # aten.addmm(bias, A, B) : A=[M,K], B=[K,N]
    a, b = args[1], args[2]
    M, K = a.shape
    _, N = b.shape
    return 2 * M * K * N


def _bmm_flops(args: Tuple, out: Any) -> int:
    # aten.bmm(A, B) : A=[B,M,K], B=[B,K,N]
    a, b = args[0], args[1]
    B, M, K = a.shape
    _, _, N = b.shape
    return 2 * B * M * K * N


# Map from OpOverload -> FLOP counting function
_FLOP_MAP = {}


def _populate_flop_map():
    """Lazily populate the FLOP map with aten op references."""
    if _FLOP_MAP:
        return
    _FLOP_MAP[torch.ops.aten.mm.default] = _mm_flops
    _FLOP_MAP[torch.ops.aten.addmm.default] = _addmm_flops
    _FLOP_MAP[torch.ops.aten.bmm.default] = _bmm_flops


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tensor_bytes(t: Any) -> int:
    """Return total bytes for a tensor, 0 for non-tensors."""
    if isinstance(t, torch.Tensor):
        return t.nelement() * t.element_size()
    return 0


def _total_arg_bytes(args: Tuple, kwargs: Optional[Dict], out: Any) -> int:
    """Sum bytes of all tensor arguments and outputs."""
    total = 0
    for a in args:
        total += _tensor_bytes(a)
    if kwargs:
        for v in kwargs.values():
            total += _tensor_bytes(v)
    if isinstance(out, torch.Tensor):
        total += _tensor_bytes(out)
    elif isinstance(out, (tuple, list)):
        for o in out:
            total += _tensor_bytes(o)
    return total


def _physical_innermost_size(tensor: torch.Tensor) -> int:
    """Size of the dimension with stride 1 (physically innermost)."""
    if tensor.dim() == 0:
        return 1
    strides = tensor.stride()
    min_stride = min(strides)
    idx = list(strides).index(min_stride)
    return tensor.shape[idx]


def _get_matrix_operands(func, args):
    """Return the two matrix operand tensors for a matmul op."""
    if func is torch.ops.aten.addmm.default:
        return args[1], args[2]  # skip bias
    return args[0], args[1]  # mm / bmm


def _next_multiple(value: int, multiple: int) -> int:
    return math.ceil(value / multiple) * multiple


def _compute_alignment(func, args):
    """Analyze alignment of matrix operands."""
    a, b = _get_matrix_operands(func, args)
    dim_a = _physical_innermost_size(a)
    dim_b = _physical_innermost_size(b)
    dims = [dim_a, dim_b]
    aligned = all(d % 8 == 0 for d in dims)
    if aligned:
        suggested = None
    else:
        suggested = [_next_multiple(d, 8) for d in dims]
    return {
        "aligned": aligned,
        "operand_innermost_dims": dims,
        "suggested_padding": suggested,
    }


# ---------------------------------------------------------------------------
# RooflineAnalyzer
# ---------------------------------------------------------------------------

class RooflineAnalyzer(TorchDispatchMode):
    """TorchDispatchMode-based roofline model analyzer."""

    def __init__(
        self,
        hardware_spec: Dict[str, float],
        model: Optional[nn.Module] = None,
    ):
        super().__init__()
        _populate_flop_map()

        self.hardware_spec = hardware_spec
        peak_flops = hardware_spec["peak_flops_per_second"]
        peak_bw = hardware_spec["peak_memory_bandwidth_bytes_per_second"]
        self.ridge_point: float = peak_flops / peak_bw

        self.ops: List[Dict[str, Any]] = []
        self._module_stack: List[str] = []
        self._hooks: list = []

        if model is not None:
            self._register_module_hooks(model)

    # -- module tracking ---------------------------------------------------

    def _register_module_hooks(self, model: nn.Module):
        for name, mod in model.named_modules():
            if name == "":
                continue  # skip root
            pre = mod.register_forward_pre_hook(
                self._make_pre_hook(name)
            )
            post = mod.register_forward_hook(
                self._make_post_hook(name)
            )
            self._hooks.extend([pre, post])

    def _make_pre_hook(self, name: str):
        def hook(module, args):
            self._module_stack.append(name)
        return hook

    def _make_post_hook(self, name: str):
        def hook(module, args, output):
            if self._module_stack and self._module_stack[-1] == name:
                self._module_stack.pop()
        return hook

    def remove_hooks(self):
        for h in self._hooks:
            h.remove()
        self._hooks.clear()

    # -- dispatch interception ---------------------------------------------

    def __torch_dispatch__(self, func, types, args=(), kwargs=None):
        kwargs = kwargs or {}
        out = func(*args, **kwargs)

        if func in _FLOP_MAP:
            flops = _FLOP_MAP[func](args, out)
            mem_bytes = _total_arg_bytes(args, kwargs, out)
            ai = flops / mem_bytes if mem_bytes > 0 else float("inf")
            classification = (
                "compute_bound" if ai >= self.ridge_point else "memory_bound"
            )
            alignment = _compute_alignment(func, args)
            module_name = (
                self._module_stack[-1] if self._module_stack else ""
            )
            self.ops.append(
                {
                    "op": str(func.name()),
                    "module": module_name,
                    "flops": flops,
                    "memory_bytes": mem_bytes,
                    "arithmetic_intensity": ai,
                    "classification": classification,
                    "alignment": alignment,
                }
            )

        return out

    # -- report generation -------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        # per-module aggregation
        per_module: Dict[str, Dict[str, Any]] = {}
        for op in self.ops:
            mod = op["module"]
            if mod not in per_module:
                per_module[mod] = {
                    "total_flops": 0,
                    "total_memory_bytes": 0,
                    "num_matmul_ops": 0,
                    "all_aligned": True,
                }
            per_module[mod]["total_flops"] += op["flops"]
            per_module[mod]["total_memory_bytes"] += op["memory_bytes"]
            per_module[mod]["num_matmul_ops"] += 1
            if not op["alignment"]["aligned"]:
                per_module[mod]["all_aligned"] = False

        # finalise per-module entries
        per_module_out: Dict[str, Dict[str, Any]] = {}
        for name, stats in per_module.items():
            flops = stats["total_flops"]
            mem = stats["total_memory_bytes"]
            ai = flops / mem if mem > 0 else 0.0
            per_module_out[name] = {
                "total_flops": flops,
                "total_memory_bytes": mem,
                "arithmetic_intensity": ai,
                "classification": (
                    "compute_bound" if ai >= self.ridge_point else "memory_bound"
                ),
                "num_matmul_ops": stats["num_matmul_ops"],
                "aligned": stats["all_aligned"],
            }

        # overall stats
        total_flops = sum(op["flops"] for op in self.ops)
        total_mem = sum(op["memory_bytes"] for op in self.ops)
        overall_ai = total_flops / total_mem if total_mem > 0 else 0.0
        overall_class = (
            "compute_bound" if overall_ai >= self.ridge_point else "memory_bound"
        )

        return {
            "total_matmul_flops": total_flops,
            "total_memory_bytes": total_mem,
            "overall_arithmetic_intensity": overall_ai,
            "overall_classification": overall_class,
            "ridge_point": self.ridge_point,
            "per_module": per_module_out,
            "operations": self.ops,
        }
