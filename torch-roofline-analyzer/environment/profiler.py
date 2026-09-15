"""Performance profiler for PyTorch models.

Uses module-level forward hooks to estimate computational cost of each layer.
"""

import torch
import torch.nn as nn


class ModelProfiler:
    """Profiles a PyTorch model by attaching forward hooks to each module."""

    def __init__(self, hardware_spec, model):
        self.hardware_spec = hardware_spec
        self.model = model
        self.peak_flops = hardware_spec["peak_flops_per_second"]
        self.peak_bw = hardware_spec["peak_memory_bandwidth_bytes_per_second"]
        self.ridge_point = self.peak_flops / self.peak_bw
        self._data = {}
        self._hooks = []

    def _make_hook(self, name):
        def hook(module, input, output):
            info = {"module_name": name}
            if hasattr(module, "weight"):
                w = module.weight
                # Estimate FLOPs from weight dimensions (multiply-accumulate)
                info["flops"] = w.shape[0] * w.shape[1] * 2
                # Memory estimate from weight tensor
                info["memory_bytes"] = w.nelement() * w.element_size()
            else:
                info["flops"] = 0
                info["memory_bytes"] = 0

            if info["memory_bytes"] > 0:
                ai = info["flops"] / info["memory_bytes"]
                info["arithmetic_intensity"] = ai
                info["classification"] = (
                    "compute_bound" if ai >= self.ridge_point else "memory_bound"
                )
            else:
                info["arithmetic_intensity"] = 0
                info["classification"] = "unknown"

            self._data[name] = info
        return hook

    def run(self, input_tensor):
        """Profile a forward pass and return per-module metrics."""
        for name, mod in self.model.named_modules():
            if name == "":
                continue
            h = mod.register_forward_hook(self._make_hook(name))
            self._hooks.append(h)

        with torch.no_grad():
            _ = self.model(input_tensor)

        for h in self._hooks:
            h.remove()
        self._hooks.clear()

        total_flops = sum(d["flops"] for d in self._data.values())
        total_mem = sum(d["memory_bytes"] for d in self._data.values())

        return {
            "per_module": self._data,
            "total_flops": total_flops,
            "total_memory_bytes": total_mem,
            "overall_arithmetic_intensity": (
                total_flops / total_mem if total_mem > 0 else 0
            ),
            "overall_classification": (
                "compute_bound"
                if (total_flops / total_mem if total_mem > 0 else 0) >= self.ridge_point
                else "memory_bound"
            ),
        }
