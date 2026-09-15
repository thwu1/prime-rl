"""Roofline Performance Model — Python wrapper for C shared library.

Loads libroofline.so via ctypes and delegates core roofline
computations (bandwidth conversion, achievable performance,
ridge point) to the native implementation.
"""
import ctypes
import os


class RooflineModel:
    """Models GPU performance using the roofline framework.

    The core math is implemented in roofline_core.c and compiled
    to libroofline.so. This wrapper manages the ctypes interface.
    """

    def __init__(self, hw_config):
        """Initialize with hardware specifications.

        Args:
            hw_config: dict with 'peak_tflops' and 'bandwidth_gb_s' keys.
        """
        lib_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "libroofline.so"
        )
        self._lib = ctypes.CDLL(lib_path)

        # Set up C function signatures
        self._lib.gb_to_bytes.argtypes = [ctypes.c_double]
        self._lib.gb_to_bytes.restype = ctypes.c_double

        self._lib.achievable_flops.argtypes = [
            ctypes.c_double, ctypes.c_double, ctypes.c_double
        ]
        self._lib.achievable_flops.restype = ctypes.c_double

        self._lib.compute_ridge_point.argtypes = [
            ctypes.c_double, ctypes.c_double
        ]
        self._lib.compute_ridge_point.restype = ctypes.c_double

        self.peak_tflops = hw_config["peak_tflops"]
        self.bandwidth_gb_s = hw_config["bandwidth_gb_s"]
        self._bandwidth_bytes = self._lib.gb_to_bytes(self.bandwidth_gb_s)
        self._peak_flops = self.peak_tflops * 1e12

    def ridge_point(self):
        """Compute the ridge point in FLOP/byte."""
        return self._lib.compute_ridge_point(
            self._peak_flops, self._bandwidth_bytes
        )

    def achievable_tflops(self, arithmetic_intensity):
        """Predict achievable performance in TFLOP/s."""
        result = self._lib.achievable_flops(
            float(arithmetic_intensity),
            self._bandwidth_bytes,
            self._peak_flops,
        )
        return result / 1e12

    def is_memory_bound(self, arithmetic_intensity):
        """Determine if a kernel is memory-bound on this hardware."""
        return arithmetic_intensity < self.ridge_point()
